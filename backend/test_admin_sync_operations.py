from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.admin_operations import OperationManager
from backend.admin_probe import AdminProbeDataError, candidates, probe_records, selected_records, stable_url_id
from backend.admin_state import AdminStateError, AdminStateStore
from backend.app import create_app
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import write_v2_record
from probe_adapters.service import apply_result


TOKEN = "correct-admin-token-123456"


def artifact(name: str, urls: list[str], *, kind: str = "apk", part: int = 1) -> dict:
    value = {
        "kind": kind, "component": "game", "package_type": "full",
        "delivery_mode": "direct", "name": name,
        "size": 10, "decompressed_size": 11,
        "checksum": {"md5": hashlib.md5(name.encode()).hexdigest()},
        "urls": [{"url": url, "provider": "fixture", "source_kind": "official", "priority": index} for index, url in enumerate(urls)],
    }
    return value


def record(platform: str, *, game: str = "hk4e", version: str = "1.0.0", artifacts: list[dict] | None = None, visible: bool = True) -> dict:
    vendor = "mihoyo"
    domain = f"{game}-{'android' if platform == 'android' else 'pc'}"
    arts = artifacts or [artifact("game.apk", ["https://autopatchcn.yuanshen.com/game.apk"])]
    value = {
        "schema_version": 2, "vendor": vendor, "game_id": game,
        "domain_id": domain, "platform": platform, "channel": "official",
        "version": version, "version_code": 1 if platform == "android" else None,
        "file_time": "2026-08-29T00:00:00Z", "artifacts": arts,
        "references": [], "is_visible": visible,
        "provenance": {"source_kind": "official_sync", "source_name": "fixture"},
    }
    identity = {key: value[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    for item in arts:
        item["artifact_id"] = artifact_id(item, record_identity=identity)
    validate_v2_record(value)
    return value


def fake_probe(url: str, **kwargs):
    return {
        "adapter": "fixture", "platform": kwargs.get("platform") or "android",
        "url": url, "http_code": 206, "available": True,
        "checked_at": "2026-08-29T02:00:00Z", "content_type": "application/octet-stream",
        "observed_size": 10, "size": 10, "etag": "fixture", "last_modified": None,
        "reason": "HTTP 206", "source_kind": "live_probe",
    }


class AdminFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.data = base / "data"
        self.state = base / "state"
        self.data.mkdir()
        self.android = record("android")
        write_v2_record(self.android, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "android")

    def tearDown(self):
        self.temp.cleanup()

    def client(self, token=TOKEN, **kwargs):
        kwargs.setdefault("probe_fn", fake_probe)
        return TestClient(create_app(self.data, state_root=self.state, admin_token=token, **kwargs))

    @staticmethod
    def auth(token=TOKEN):
        return {"Authorization": f"Bearer {token}"}


class AuthAndRouteTests(AdminFixture):
    def test_admin_disabled_without_secure_token(self):
        with patch.dict(os.environ, {"GMI_ADMIN_TOKEN": TOKEN}):
            response = self.client(token=None).get("/api/v1/admin/sync/schedule")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "admin_auth_not_configured")
            malformed = self.client(token=None).post("/api/v1/admin/operations/start", json={"workers": "bad"})
            self.assertEqual(malformed.status_code, 503)

    def test_short_token_disables_admin(self):
        self.assertEqual(self.client(token="short").get("/api/v1/admin/sync/schedule").status_code, 503)

    def test_missing_and_wrong_bearer_are_401(self):
        client = self.client()
        self.assertEqual(client.get("/api/v1/admin/sync/schedule").status_code, 401)
        self.assertEqual(client.get("/api/v1/admin/sync/schedule", headers=self.auth("wrong-token-123456789")).status_code, 401)
        malformed = client.post(
            "/api/v1/admin/operations/start",
            headers=self.auth("wrong-token-123456789"),
            json={"workers": "bad"},
        )
        self.assertEqual(malformed.status_code, 401)

    def test_correct_bearer_and_public_route(self):
        client = self.client()
        self.assertEqual(client.get("/api/v1/admin/sync/schedule", headers=self.auth()).status_code, 200)
        self.assertEqual(client.get("/api/v1/health").status_code, 200)

    def test_secret_never_returned(self):
        response = self.client().get("/api/v1/admin/operations/latest", headers=self.auth())
        self.assertNotIn(TOKEN, response.text)

    def test_route_inventory_has_only_phase_routes(self):
        routes = {(route.path, method) for route in self.client().app.routes for method in getattr(route, "methods", set())}
        expected = {
            ("/api/v1/admin/operations/start", "POST"), ("/api/v1/admin/operations/latest", "GET"),
            ("/api/v1/admin/operations/{job_id}", "GET"), ("/api/v1/admin/operations/{job_id}/cancel", "POST"),
            ("/api/v1/admin/sync-status", "GET"), ("/api/v1/admin/sync/status", "GET"),
            ("/api/v1/admin/sync/schedule", "GET"), ("/api/v1/admin/sync/schedule", "PUT"),
            ("/api/v1/admin/probe/status", "GET"), ("/api/v1/admin/probe/schedule", "GET"),
            ("/api/v1/admin/probe/schedule", "PUT"), ("/api/v1/admin/probe/url", "POST"),
            ("/api/v1/admin/probe/urls", "POST"), ("/api/v1/admin/domains/{domain_id}/versions/{version}/probe", "POST"),
        }
        self.assertTrue(expected <= routes)
        self.assertNotIn(("/api/v1/admin/operations/run", "POST"), routes)
        self.assertFalse(any("retention" in path for path, _ in routes))


class ScheduleTests(AdminFixture):
    def test_defaults(self):
        client = self.client()
        self.assertEqual(client.get("/api/v1/admin/sync/schedule", headers=self.auth()).json(), {"enabled": False, "times": []})
        self.assertEqual(client.get("/api/v1/admin/probe/schedule", headers=self.auth()).json(), {"enabled": False, "interval_hours": 24, "mode": "normal"})

    def test_sync_normalizes_and_survives_restart(self):
        client = self.client()
        response = client.put("/api/v1/admin/sync/schedule", headers=self.auth(), json={"enabled": True, "times": ["18:00", "08:00", "08:00"]})
        self.assertEqual(response.json()["times"], ["08:00", "18:00"])
        restarted = self.client()
        self.assertEqual(restarted.get("/api/v1/admin/sync/schedule", headers=self.auth()).json()["times"], ["08:00", "18:00"])

    def test_validation(self):
        client = self.client()
        for payload in ({"enabled": True, "times": []}, {"enabled": False, "times": ["24:00"]}):
            self.assertEqual(client.put("/api/v1/admin/sync/schedule", headers=self.auth(), json=payload).status_code, 422)
        self.assertEqual(client.put("/api/v1/admin/sync/schedule", headers=self.auth(), json={"enabled": False, "times": ["01:00", "02:00", "03:00"]}).status_code, 422)
        for hours in (0, 169):
            self.assertEqual(client.put("/api/v1/admin/probe/schedule", headers=self.auth(), json={"enabled": True, "interval_hours": hours, "mode": "full"}).status_code, 422)

    def test_writes_preserve_other_schedule(self):
        client = self.client()
        client.put("/api/v1/admin/probe/schedule", headers=self.auth(), json={"enabled": True, "interval_hours": 12, "mode": "full"})
        client.put("/api/v1/admin/sync/schedule", headers=self.auth(), json={"enabled": False, "times": ["09:00"]})
        self.assertEqual(client.get("/api/v1/admin/probe/schedule", headers=self.auth()).json()["interval_hours"], 12)

    def test_valid_json_with_invalid_schedule_shape_is_rejected(self):
        store = AdminStateStore(self.state)
        store.write("schedules", {"sync": {"enabled": False, "times": [], "unexpected": True}})
        with self.assertRaises(AdminStateError):
            store.schedules()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_state_root_is_rejected(self):
        target = self.state.parent / "real-state"
        target.mkdir()
        try:
            os.symlink(target, self.state, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(AdminStateError):
            AdminStateStore(self.state).schedules()


class ProbeTests(AdminFixture):
    def test_no_id_is_read_only(self):
        before = deepcopy(self.android)
        response = self.client().post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": self.android["artifacts"][0]["urls"][0]["url"], "timeout": 5})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["persisted"])
        path = self.data / "mihoyo/hk4e/android/1.0.0.json"
        self.assertEqual(json.loads(path.read_text()), before)

    def test_probe_rejects_unsafe_urls_before_transport_and_redacts_query(self):
        calls = []
        def tracking(url, **kwargs):
            calls.append(url)
            return fake_probe(url, **kwargs)
        client = self.client(probe_fn=tracking)
        for url in ("file:///etc/passwd", "https://user:secret@autopatchcn.yuanshen.com/a.apk"):
            response = client.post(
                "/api/v1/admin/probe/url", headers=self.auth(), json={"url": url},
            )
            self.assertEqual(response.status_code, 422)
        self.assertEqual(calls, [])
        response = client.post(
            "/api/v1/admin/probe/url",
            headers=self.auth(),
            json={"url": "https://autopatchcn.yuanshen.com/a.apk?token=secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["url"], "https://autopatchcn.yuanshen.com/a.apk")
        self.assertNotIn("secret", response.text)

    def test_id_persists_exact_candidate_and_preserves_nonprobe_fields(self):
        candidate = self.android["artifacts"][0]["urls"][0]
        public_id = stable_url_id(self.android["artifacts"][0]["artifact_id"], 0, candidate["url"])
        response = self.client().post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": candidate["url"], "artifact_url_id": public_id})
        self.assertTrue(response.json()["persisted"])
        current = json.loads((self.data / "mihoyo/hk4e/android/1.0.0.json").read_text())
        self.assertEqual(current["artifacts"][0]["artifact_id"], self.android["artifacts"][0]["artifact_id"])
        self.assertEqual(current["artifacts"][0]["checksum"], self.android["artifacts"][0]["checksum"])
        self.assertTrue(current["is_visible"])
        self.assertEqual(current["artifacts"][0]["urls"][0]["current"]["state"], "available")
        expected = deepcopy(self.android)
        actual = deepcopy(current)
        actual["artifacts"][0]["urls"][0].pop("current")
        self.assertEqual(actual, expected)
        index = json.loads((self.data / "mihoyo/hk4e/android/index.json").read_text())
        self.assertTrue(index["versions"][0]["available"])

    def test_id_url_mismatch_and_missing(self):
        candidate = self.android["artifacts"][0]["urls"][0]
        public_id = stable_url_id(self.android["artifacts"][0]["artifact_id"], 0, candidate["url"])
        client = self.client()
        self.assertEqual(client.post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": "https://example.test/wrong.apk", "artifact_url_id": public_id}).status_code, 409)
        self.assertEqual(client.post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": candidate["url"], "artifact_url_id": public_id + 1}).status_code, 404)

    def test_ambiguous_public_id_is_409(self):
        url = self.android["artifacts"][0]["urls"][0]["url"]
        with patch("backend.admin_probe.stable_url_id", return_value=77):
            response = self.client().post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": url, "artifact_url_id": 77})
        # One matching candidate is still unique. Add a second canonical URL
        # target, then the collision must be rejected rather than guessed.
        other = record("windows", artifacts=[artifact("game.zip", [url], kind="package")])
        write_v2_record(other, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "windows")
        with patch("backend.admin_probe.stable_url_id", return_value=77):
            response = self.client().post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": url, "artifact_url_id": 77})
        self.assertEqual(response.status_code, 409)

    def test_many_alignment_duplicate_and_readonly(self):
        client = self.client()
        urls = ["https://autopatchcn.yuanshen.com/a.apk", "https://autopatchcn.yuanshen.com/b.apk"]
        response = client.post("/api/v1/admin/probe/urls", headers=self.auth(), json={"urls": urls, "artifact_url_ids": [1]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(client.post("/api/v1/admin/probe/urls", headers=self.auth(), json={"urls": [urls[0], urls[0]]}).status_code, 422)
        response = client.post("/api/v1/admin/probe/urls", headers=self.auth(), json={"urls": urls})
        self.assertTrue(all(not item["persisted"] for item in response.json()["items"]))

    def test_same_record_candidates_are_sequential_without_lost_updates(self):
        second = record("windows", artifacts=[
            artifact("a.zip", ["https://autopatchcn.yuanshen.com/a.zip", "https://autopatchcn.yuanshen.com/b.zip"], kind="package"),
            artifact("c.zip", ["https://autopatchcn.yuanshen.com/c.zip"], kind="package", part=2),
        ])
        write_v2_record(second, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "windows")
        calls = []
        def tracking(url, **kwargs):
            calls.append(url)
            return fake_probe(url, **kwargs)
        summary = probe_records(self.data, selected_records(self.data, ["hk4e"], "pc"), 5, 8, probe_fn=tracking, apply_fn=apply_result)
        self.assertEqual(summary["checked"], 3)
        saved = json.loads((self.data / "mihoyo/hk4e/pc/1.0.0.json").read_text())
        self.assertEqual([url["current"]["state"] for art in saved["artifacts"] for url in art["urls"]], ["available"] * 3)
        self.assertEqual(calls, ["https://autopatchcn.yuanshen.com/a.zip", "https://autopatchcn.yuanshen.com/b.zip", "https://autopatchcn.yuanshen.com/c.zip"])

    def test_expected_size_uses_archive_size_but_not_file_manifest_total(self):
        archive = record("windows", version="3.0.0", artifacts=[artifact("archive.zip", ["https://autopatchcn.yuanshen.com/archive.zip"], kind="package")])
        manifest = record("windows", version="4.0.0", artifacts=[artifact("index.json", ["https://autopatchcn.yuanshen.com/index.json"], kind="package")])
        archive["artifacts"][0]["delivery_mode"] = "archive"
        manifest["artifacts"][0]["delivery_mode"] = "file_manifest"
        manifest["artifacts"][0]["manifest"] = {
            "path": "manifests/4.0.0/files.json",
            "base_urls": [{
                "url": "https://autopatchcn.yuanshen.com/files/",
                "provider": "mihoyo",
                "source_kind": "official",
                "priority": 0,
            }],
        }
        validate_v2_record(archive)
        validate_v2_record(manifest)
        write_v2_record(archive, self.data)
        write_v2_record(manifest, self.data)
        observed = {}
        def tracking(url, **kwargs):
            observed[url] = kwargs.get("expected_size")
            return fake_probe(url, **kwargs)
        probe_records(self.data, selected_records(self.data, ["hk4e"], "pc"), 5, 2, probe_fn=tracking, apply_fn=apply_result)
        self.assertEqual(observed["https://autopatchcn.yuanshen.com/archive.zip"], archive["artifacts"][0]["size"])
        self.assertIsNone(observed["https://autopatchcn.yuanshen.com/index.json"])

    def test_android_multi_url_and_hidden_flag_are_preserved(self):
        value = record("android", version="2.0.0", artifacts=[artifact("two.apk", ["https://autopatchcn.yuanshen.com/one.apk", "https://autopatchcn.yuanshen.com/two.apk"])], visible=False)
        write_v2_record(value, self.data)
        summary = probe_records(self.data, selected_records(self.data, ["hk4e"], "android", version="2.0.0"), 5, 4, probe_fn=fake_probe, apply_fn=apply_result)
        self.assertEqual(summary["checked"], 2)
        saved = json.loads((self.data / "mihoyo/hk4e/android/2.0.0.json").read_text())
        self.assertFalse(saved["is_visible"])
        self.assertEqual([item["current"]["state"] for item in saved["artifacts"][0]["urls"]], ["available", "available"])

    def test_failure_isolated_to_candidate_and_version_summary(self):
        candidate = self.android["artifacts"][0]["urls"][0]["url"]
        def failing(url, **kwargs):
            raise ValueError("secret?token=do-not-return")
        client = TestClient(create_app(self.data, state_root=self.state, admin_token=TOKEN, probe_fn=failing))
        response = client.post("/api/v1/admin/domains/hk4e-android/versions/1.0.0/probe", headers=self.auth())
        summary = response.json()["summary"]
        self.assertEqual(summary["checked"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertNotIn("do-not-return", response.text)

    def test_candidate_failure_does_not_stop_later_candidate(self):
        value = record("windows", artifacts=[artifact("pair.zip", ["https://autopatchcn.yuanshen.com/fail.zip", "https://autopatchcn.yuanshen.com/ok.zip"], kind="package")])
        write_v2_record(value, self.data)
        def partial(url, **kwargs):
            if "fail" in url:
                raise ValueError("failed")
            return fake_probe(url, **kwargs)
        summary = probe_records(self.data, selected_records(self.data, ["hk4e"], "pc"), 5, 2, probe_fn=partial, apply_fn=apply_result)
        self.assertEqual((summary["failed"], summary["available"]), (1, 1))
        saved = json.loads((self.data / "mihoyo/hk4e/pc/1.0.0.json").read_text())
        self.assertNotIn("current", saved["artifacts"][0]["urls"][0])
        self.assertEqual(saved["artifacts"][0]["urls"][1]["current"]["state"], "available")

    def test_admin_probe_refuses_corrupt_or_path_mismatched_records(self):
        path = self.data / "mihoyo/hk4e/android/1.0.0.json"
        original = path.read_text(encoding="utf-8")
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(AdminProbeDataError):
            selected_records(self.data, ["hk4e"], "android")
        path.write_text(original, encoding="utf-8")
        value = json.loads(original)
        value["game_id"] = "nap"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(AdminProbeDataError):
            selected_records(self.data, ["hk4e"], "android")

    def test_record_level_failure_accounts_for_every_selected_candidate(self):
        value = record("windows", artifacts=[artifact("pair.zip", ["https://autopatchcn.yuanshen.com/a.zip", "https://autopatchcn.yuanshen.com/b.zip"], kind="package")])
        write_v2_record(value, self.data)
        def broken_apply(record_value, result):
            raise RuntimeError("apply failed")
        summary = probe_records(
            self.data, selected_records(self.data, ["hk4e"], "pc"), 5, 1,
            probe_fn=fake_probe, apply_fn=broken_apply,
        )
        self.assertEqual((summary["selected"], summary["checked"], summary["failed"]), (2, 2, 2))


class OperationTests(AdminFixture):
    def wait(self, client, job_id):
        for _ in range(200):
            value = client.get(f"/api/v1/admin/operations/{job_id}", headers=self.auth()).json()
            if value["status"] not in {"running", "cancelling"}:
                return value
            time.sleep(.01)
        self.fail("operation did not finish")

    def test_payload_defaults_order_and_status_projection(self):
        events = []
        def discovery(game_ids, root, timeout, workers, **kwargs):
            events.append("discover")
            return {"selected": 0, "succeeded": 0, "failed": 0, "new_versions": 0, "items": [], "cancelled": False}
        def probing(url, **kwargs):
            events.append("probe")
            return fake_probe(url, **kwargs)
        client = self.client(discovery=discovery, probe_fn=probing)
        started = client.post("/api/v1/admin/operations/start", headers=self.auth(), json={"all_games": True}).json()
        finished = self.wait(client, started["job_id"])
        self.assertEqual(finished["actions"], ["discover", "probe"])
        self.assertEqual(events[0], "discover")
        self.assertIn("probe", events)
        self.assertEqual(finished["result"]["scope"], "all")
        self.assertNotIn("https://", json.dumps(finished["result"]))
        self.assertNotIn(TOKEN, json.dumps(finished))
        self.assertEqual(client.get("/api/v1/admin/sync/status", headers=self.auth()).json()["status"], "finished")
        self.assertEqual(client.get("/api/v1/admin/probe/status", headers=self.auth()).json()["status"], "finished")

    def test_partial_failure_is_finished_but_status_projection_is_not_ok(self):
        def discovery(game_ids, root, timeout, workers, **kwargs):
            items = [{
                "game_id": game_ids[0], "platform": "android", "ok": False,
                "supported": True, "status": "failed", "version": None,
                "new": False, "available": None, "error": "failed",
            }]
            kwargs["progress"](items[0], 1, 1)
            return {"selected": 1, "succeeded": 0, "failed": 1, "new_versions": 0, "items": items, "cancelled": False}
        client = self.client(discovery=discovery)
        started = client.post(
            "/api/v1/admin/operations/start", headers=self.auth(),
            json={"actions": ["discover"], "scope": "android", "all_games": False, "game_ids": ["hk4e"]},
        ).json()
        finished = self.wait(client, started["job_id"])
        self.assertEqual((finished["status"], finished["failed"]), ("finished", 1))
        live = client.get("/api/v1/admin/sync/status", headers=self.auth()).json()
        legacy = client.get("/api/v1/admin/sync-status", headers=self.auth()).json()["latest_refresh"]
        self.assertEqual((live["result"]["ok"], live["exit_code"]), (False, 1))
        self.assertEqual((len(legacy["failures"]), legacy["exit_code"]), (1, 1))

    def test_initial_status_routes_do_not_fabricate_snapshots(self):
        client = self.client()
        self.assertEqual(client.get("/api/v1/admin/sync-status", headers=self.auth()).json(), {"approved_snapshots": [], "latest_snapshot": None, "latest_refresh": None})
        self.assertEqual(client.get("/api/v1/admin/sync/status", headers=self.auth()).json()["status"], "idle")
        self.assertEqual(client.get("/api/v1/admin/probe/status", headers=self.auth()).json()["status"], "idle")

    def test_same_game_runs_android_and_pc_scope_tasks(self):
        pc = record("windows", artifacts=[artifact("game.zip", ["https://autopatchcn.yuanshen.com/game.zip"], kind="package")])
        write_v2_record(pc, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "windows")
        client = self.client()
        started = client.post("/api/v1/admin/operations/start", headers=self.auth(), json={"actions": ["probe"], "scope": "all", "all_games": False, "game_ids": ["hk4e"]}).json()
        result = self.wait(client, started["job_id"])["result"]["probe"]
        self.assertEqual({item["platform"] for item in result["items"]}, {"android", "windows"})

    def test_same_game_discovery_runs_android_and_pc_scopes(self):
        scopes = []
        def discovery(game_ids, root, timeout, workers, **kwargs):
            scopes.append((kwargs["scope"], tuple(game_ids)))
            platform = "android" if kwargs["scope"] == "android" else "windows"
            item = {"game_id": game_ids[0], "platform": platform, "ok": True, "supported": True, "status": "finished", "version": "1.0.0", "new": False, "available": None, "error": None}
            kwargs["progress"](item, 1, 1)
            return {"selected": 1, "succeeded": 1, "failed": 0, "new_versions": 0, "items": [item], "cancelled": False}
        client = self.client(discovery=discovery)
        started = client.post(
            "/api/v1/admin/operations/start", headers=self.auth(),
            json={"actions": ["discover"], "scope": "all", "all_games": False, "game_ids": ["hk4e"]},
        ).json()
        finished = self.wait(client, started["job_id"])
        self.assertEqual(finished["status"], "finished")
        self.assertEqual(scopes, [("android", ("hk4e",)), ("pc", ("hk4e",))])

    def test_payload_validation_404_cursor_and_single_active(self):
        gate = []
        def slow_discovery(game_ids, root, timeout, workers, **kwargs):
            while not gate:
                time.sleep(.01)
            return {"selected": 0, "succeeded": 0, "failed": 0, "new_versions": 0, "items": [], "cancelled": False}
        client = self.client(discovery=slow_discovery)
        for payload in (
            {"actions": [], "all_games": True}, {"actions": ["probe"], "all_games": False, "game_ids": []},
            {"actions": ["probe"], "scope": "android", "all_games": False, "game_ids": ["unknown"]},
            {"actions": ["probe"], "workers": 0}, {"actions": ["probe"], "workers": 17},
            {"actions": ["probe"], "timeout": 0}, {"actions": ["probe"], "timeout": 61},
        ):
            self.assertEqual(client.post("/api/v1/admin/operations/start", headers=self.auth(), json=payload).status_code, 422)
        started = client.post("/api/v1/admin/operations/start", headers=self.auth(), json={"actions": ["discover"], "scope": "android", "all_games": False, "game_ids": ["hk4e"]}).json()
        self.assertEqual(client.post("/api/v1/admin/operations/start", headers=self.auth(), json={"actions": ["probe"]}).status_code, 409)
        self.assertEqual(client.get("/api/v1/admin/operations/missing", headers=self.auth()).status_code, 404)
        self.assertEqual(client.get(f"/api/v1/admin/operations/{started['job_id']}?after=999", headers=self.auth()).status_code, 422)
        gate.append(True)
        self.wait(client, started["job_id"])

    def test_cancel_and_restart_recovery(self):
        store = AdminStateStore(self.state)
        store.write("latest_operation", {"job_id": "old", "status": "running", "phase": "probe", "actions": ["probe"], "game_ids": ["hk4e"], "scope": "android", "completed": 0, "total": 1, "phase_completed": 0, "phase_total": 1, "succeeded": 0, "failed": 0, "current": None, "started_at": "2026-08-29T00:00:00Z", "finished_at": None, "result": None, "error": None, "logs": []})
        restored = OperationManager(store, self.data, probe_fn=fake_probe).latest()
        self.assertEqual(restored["status"], "failed")
        self.assertEqual(restored["error"], "operation_interrupted_by_restart")

        gate = []
        def slow_discovery(game_ids, root, timeout, workers, **kwargs):
            while not gate:
                time.sleep(.01)
            return {"selected": 0, "succeeded": 0, "failed": 0, "new_versions": 0, "items": [], "cancelled": kwargs["cancelled"]()}
        # Separate state root so the recovered terminal snapshot does not affect this check.
        client = TestClient(create_app(self.data, state_root=self.state.parent / "cancel-state", admin_token=TOKEN, discovery=slow_discovery, probe_fn=fake_probe))
        started = client.post("/api/v1/admin/operations/start", headers=self.auth(), json={"actions": ["discover"], "scope": "android", "all_games": False, "game_ids": ["hk4e"]}).json()
        cancelled = client.post(f"/api/v1/admin/operations/{started['job_id']}/cancel", headers=self.auth()).json()
        self.assertEqual(cancelled["status"], "cancelling")
        gate.append(True)
        self.assertEqual(self.wait(client, started["job_id"])["status"], "cancelled")

    def test_invalid_restored_snapshot_is_ignored(self):
        store = AdminStateStore(self.state)
        store.write("latest_operation", {"job_id": "bad", "status": "running", "logs": "not-a-list"})
        with self.assertRaises(KeyError):
            OperationManager(store, self.data, probe_fn=fake_probe).latest()

    def test_internal_failure_counter_is_not_public_or_persisted(self):
        manager = OperationManager(AdminStateStore(self.state), self.data, probe_fn=fake_probe)
        manager._job = {
            "job_id": "fixture", "status": "running", "phase": "probe",
            "actions": ["probe"], "game_ids": ["hk4e"], "scope": "android",
            "completed": 1, "total": 1, "phase_completed": 1, "phase_total": 1,
            "succeeded": 0, "failed": 1, "current": None,
            "started_at": "2026-08-29T00:00:00Z", "finished_at": None,
            "result": None, "error": None, "logs": ["fixture"], "_phase_failed": 1,
        }
        manager._save()
        self.assertNotIn("_phase_failed", manager.latest())
        persisted = json.loads((self.state / "admin/latest_operation.json").read_text(encoding="utf-8"))
        self.assertNotIn("_phase_failed", persisted)

    def test_incremental_logs(self):
        client = self.client()
        started = client.post("/api/v1/admin/operations/start", headers=self.auth(), json={"actions": ["probe"], "scope": "android", "all_games": False, "game_ids": ["hk4e"]}).json()
        finished = self.wait(client, started["job_id"])
        after = max(0, finished["log_total"] - 1)
        incremental = client.get(f"/api/v1/admin/operations/{started['job_id']}?after={after}", headers=self.auth()).json()
        self.assertEqual(incremental["log_offset"], after)
        self.assertEqual(len(incremental["logs"]), finished["log_total"] - after)

    def test_discovery_rebuilds_each_domain_once(self):
        second = record("android", version="2.0.0")
        write_v2_record(second, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "android")
        manager = OperationManager(AdminStateStore(self.state), self.data, probe_fn=fake_probe)
        items = [{"game_id": "hk4e", "platform": "android", "ok": True}]
        with patch("backend.admin_operations.rebuild_index") as rebuild:
            manager._rebuild_discovered(items)
        rebuild.assert_called_once_with(self.data, "mihoyo", "hk4e", "android")


if __name__ == "__main__":
    unittest.main()
