from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.activity_store import ActivityStore
from backend.app import create_app
from backend.admin_probe import stable_url_id
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import write_v2_record


TOKEN = "activity-test-token-123456"


def make_record(platform: str, version: str, urls: list[dict], *, provenance: str = "official_sync") -> dict:
    game_id = "hk4e"
    disk_platform = "android" if platform == "android" else "pc"
    record = {
        "schema_version": 2,
        "vendor": "mihoyo",
        "game_id": game_id,
        "domain_id": f"{game_id}-{disk_platform}",
        "platform": platform,
        "channel": "official",
        "version": version,
        "version_code": 1 if platform == "android" else None,
        "file_time": "2026-09-28T00:00:00Z",
        "artifacts": [{
            "kind": "apk" if platform == "android" else "package",
            "component": "game",
            "package_type": "full",
            "delivery_mode": "direct",
            "name": f"game.{ 'apk' if platform == 'android' else 'zip' }",
            "size": 100,
            "checksum": {"md5": hashlib.md5(version.encode()).hexdigest()},
            "urls": urls,
        }],
        "references": [],
        "provenance": {"source_kind": provenance, "source_name": "test fixture"},
    }
    identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    for artifact in record["artifacts"]:
        artifact["artifact_id"] = artifact_id(artifact, record_identity=identity)
    validate_v2_record(record)
    return record


def url_candidate(url: str, *, state: str | None = None, checked_at: str | None = None) -> dict:
    candidate = {"url": url, "provider": "mihoyo", "source_kind": "official", "priority": 0}
    if state is not None:
        candidate["current"] = {
            "state": state,
            "http_code": 206 if state == "available" else 404,
            "checked_at": checked_at,
        }
    return candidate


class ActivityHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.data = base / "data"
        self.state = base / "state"
        self.data.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def client(self, **kwargs):
        return TestClient(create_app(self.data, state_root=self.state, admin_token=TOKEN, **kwargs))

    @staticmethod
    def auth():
        return {"Authorization": f"Bearer {TOKEN}"}

    def wait_for_operation(self, client: TestClient, job_id: str) -> dict:
        for _ in range(300):
            response = client.get(f"/api/v1/admin/operations/{job_id}", headers=self.auth())
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            if value["status"] not in {"running", "cancelling"}:
                return value
            time.sleep(0.01)
        self.fail("operation did not finish")

    def start_discovery(self, client: TestClient, scope: str) -> dict:
        response = client.post(
            "/api/v1/admin/operations/start",
            headers=self.auth(),
            json={"actions": ["discover"], "scope": scope, "all_games": False, "game_ids": ["hk4e"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return self.wait_for_operation(client, response.json()["job_id"])

    def test_batch_discovery_records_only_newer_android_latest(self):
        old = make_record("android", "1.0.0", [url_candidate("https://example.invalid/old.apk")])
        write_v2_record(old, self.data)
        discovered = {"version": "1.1.0", "provenance": "official_sync"}

        def discovery(game_ids, root, timeout, workers, **kwargs):
            version = discovered["version"]
            newest = make_record(
                "android", version, [url_candidate(f"https://example.invalid/{version}.apk")],
                provenance=discovered["provenance"],
            )
            path = write_v2_record(newest, root)
            item = {
                "game_id": "hk4e", "platform": "android", "ok": True,
                "supported": True, "status": "finished", "version": version,
                "new": True, "available": True, "path": str(path), "error": None,
            }
            return {"selected": 1, "succeeded": 1, "failed": 0, "new_versions": 1, "items": [item], "cancelled": False}

        client = self.client(discovery=discovery)
        result = self.start_discovery(client, "android")
        self.assertEqual(result["status"], "finished")
        response = client.get("/api/v1/games/hk4e/activity")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(
            {key: item[key] for key in ("game_id", "domain_id", "platform", "version", "type")},
            {"game_id": "hk4e", "domain_id": "hk4e-android", "platform": "android", "version": "1.1.0", "type": "version_update"},
        )
        self.assertEqual(set(item), {"id", "game_id", "domain_id", "platform", "version", "type", "occurred_at"})
        self.assertIsInstance(item["id"], int)
        self.assertEqual(client.get("/api/v1/activity?limit=20").json(), payload)

        discovered.update(version="1.2.0", provenance="historical_import")
        self.assertEqual(self.start_discovery(client, "android")["status"], "finished")
        self.assertEqual(len(client.get("/api/v1/games/hk4e/activity").json()["items"]), 1)

    def test_empty_global_activity_does_not_create_database_and_hides_disabled_games(self):
        visible_record = make_record("android", "1.0.0", [url_candidate("https://example.invalid/visible.apk")])
        write_v2_record(visible_record, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "android")
        client = self.client()
        empty = client.get("/api/v1/activity")
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json(), {"items": []})
        self.assertFalse((self.state / "activity.sqlite3").exists())

        store = ActivityStore(self.state)
        for game_id in ("hk4e", "ghost"):
            store.append(
                game_id=game_id, domain_id=f"{game_id}-android", platform="android",
                version="1.0.0", event_type="version_update",
            )
        store.append(
            game_id="hk4e", domain_id="hk4e-android", platform="android",
            version="2.0.0", event_type="version_update",
        )
        visible = client.get("/api/v1/activity")
        self.assertEqual([item["game_id"] for item in visible.json()["items"]], ["hk4e"])
        per_game = client.get("/api/v1/games/hk4e/activity")
        self.assertEqual([item["version"] for item in per_game.json()["items"]], ["1.0.0"])
        disabled_catalog = [{"id": "hk4e", "is_enabled": False}]
        with patch.object(client.app.state.contract, "_catalog_games", return_value=disabled_catalog):
            hidden = client.get("/api/v1/activity")
        self.assertEqual(hidden.status_code, 200, hidden.text)
        self.assertEqual(hidden.json(), {"items": []})

    def test_pc_stage_is_used_when_aggregate_version_is_none(self):
        previous = make_record("windows", "1.0.0", [url_candidate("https://example.invalid/old.zip")])
        write_v2_record(previous, self.data)

        def discovery(game_ids, root, timeout, workers, **kwargs):
            newest = make_record("windows", "1.1.0", [url_candidate("https://example.invalid/new.zip")])
            new_path = write_v2_record(newest, root)
            older = make_record("windows", "0.9.0", [url_candidate("https://example.invalid/older.zip")])
            older_path = write_v2_record(older, root)
            item = {
                "game_id": "hk4e", "platform": "windows", "ok": True,
                "supported": True, "status": "finished", "version": None,
                "versions": ["1.1.0", "0.9.0"], "new": True,
                "stages": [
                    {"name": "packages", "ok": True, "version": "1.1.0", "path": str(new_path), "new": True},
                    {"name": "chunks", "ok": True, "version": "0.9.0", "path": str(older_path), "new": True},
                ],
            }
            return {"selected": 1, "succeeded": 1, "failed": 0, "new_versions": 1, "items": [item], "cancelled": False}

        client = self.client(discovery=discovery)
        result = self.start_discovery(client, "pc")
        self.assertEqual(result["status"], "finished")
        events = client.get("/api/v1/games/hk4e/activity").json()["items"]
        self.assertEqual([(event["platform"], event["version"], event["type"]) for event in events], [("windows", "1.1.0", "version_update")])

    def test_scheduled_discovery_and_probe_uses_same_activity_pipeline(self):
        old = make_record("android", "1.0.0", [url_candidate("https://example.invalid/old.apk")])
        write_v2_record(old, self.data)

        def discovery(game_ids, root, timeout, workers, **kwargs):
            newest = make_record("android", "1.1.0", [url_candidate("https://example.invalid/new.apk")])
            path = write_v2_record(newest, root)
            item = {
                "game_id": "hk4e", "platform": "android", "ok": True,
                "supported": True, "status": "finished", "version": "1.1.0",
                "new": True, "available": True, "path": str(path), "error": None,
            }
            return {"selected": 1, "succeeded": 1, "failed": 0, "new_versions": 1, "items": [item], "cancelled": False}

        def available(url, **kwargs):
            return {
                "adapter": "fixture", "platform": "android", "url": url,
                "http_code": 206, "available": True,
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "content_type": None, "observed_size": None, "size": None,
                "etag": None, "last_modified": None, "reason": "HTTP 206",
            }

        client = self.client(discovery=discovery, probe_fn=available)
        manager = client.app.state.admin_operations
        started = manager.start(
            ["discover", "probe"], ["hk4e"], "android", 10, 1,
            scheduled_mode="normal",
        )
        result = self.wait_for_operation(client, started["job_id"])
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["result"]["probe"]["checked"], 1)
        events = client.get("/api/v1/games/hk4e/activity").json()["items"]
        self.assertEqual([(event["version"], event["type"]) for event in events], [("1.1.0", "version_update")])

    def test_manual_single_url_probe_emits_only_the_all_unavailable_transition(self):
        now = datetime.now(timezone.utc)
        checked_at = (now - timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
        urls = [
            "https://example.invalid/first.apk",
            "https://example.invalid/second.apk",
        ]
        initial = make_record("android", "1.0.0", [url_candidate(url, state="available", checked_at=checked_at) for url in urls])
        write_v2_record(initial, self.data)
        probe_time = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

        def unavailable(url, **kwargs):
            return {
                "adapter": "fixture", "platform": "android", "url": url,
                "http_code": 404, "available": False, "checked_at": probe_time,
                "content_type": None, "observed_size": None, "size": None,
                "etag": None, "last_modified": None, "reason": "HTTP 404",
            }

        client = self.client(probe_fn=unavailable)
        for index, url in enumerate(urls):
            response = client.post(
                "/api/v1/admin/probe/url", headers=self.auth(),
                json={"url": url, "artifact_url_id": stable_url_id(initial["artifacts"][0]["artifact_id"], index, url)},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["persisted"])
            events = client.get("/api/v1/games/hk4e/activity").json()["items"]
            self.assertEqual(len(events), 0 if index == 0 else 1)

        repeated = client.post(
            "/api/v1/admin/probe/url", headers=self.auth(),
            json={"url": urls[1], "artifact_url_id": stable_url_id(initial["artifacts"][0]["artifact_id"], 1, urls[1])},
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        events = client.get("/api/v1/games/hk4e/activity").json()["items"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "version_unavailable")

    def test_activity_write_failure_does_not_fail_persisted_probe(self):
        checked_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
        old = make_record("android", "1.0.0", [url_candidate("https://example.invalid/old.apk", state="available", checked_at=checked_at)])
        write_v2_record(old, self.data)

        def unavailable(url, **kwargs):
            return {
                "adapter": "fixture", "platform": "android", "url": url,
                "http_code": 404, "available": False,
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "content_type": None, "observed_size": None, "size": None,
                "etag": None, "last_modified": None, "reason": "HTTP 404",
            }

        client = self.client(probe_fn=unavailable)
        with self.assertLogs("backend.admin_probe", level="WARNING"):
            with patch("backend.activity_store.ActivityStore.append", side_effect=OSError("injected sqlite error")):
                response = client.post(
                    "/api/v1/admin/probe/url", headers=self.auth(),
                    json={"url": "https://example.invalid/old.apk", "artifact_url_id": stable_url_id(old["artifacts"][0]["artifact_id"], 0, "https://example.invalid/old.apk")},
                )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["persisted"])

    def test_manual_version_probe_records_the_availability_transition(self):
        checked_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
        url = "https://example.invalid/version.apk"
        initial = make_record("android", "1.0.0", [url_candidate(url, state="available", checked_at=checked_at)])
        write_v2_record(initial, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "android")

        def unavailable(target, **kwargs):
            return {
                "adapter": "fixture", "platform": "android", "url": target,
                "http_code": 404, "available": False,
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "content_type": None, "observed_size": None, "size": None,
                "etag": None, "last_modified": None, "reason": "HTTP 404",
            }

        client = self.client(probe_fn=unavailable)
        response = client.post("/api/v1/admin/domains/hk4e-android/versions/1.0.0/probe", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        event = client.get("/api/v1/games/hk4e/activity").json()["items"][0]
        self.assertEqual((event["domain_id"], event["version"], event["type"]), ("hk4e-android", "1.0.0", "version_unavailable"))


if __name__ == "__main__":
    unittest.main()
