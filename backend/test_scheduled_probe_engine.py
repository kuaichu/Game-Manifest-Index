from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

from backend.admin_operations import OperationManager
from backend.admin_state import AdminStateStore
from backend.admin_probe import probe_records, selected_records
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import write_v2_record
from probe_adapters.service import current_from_result


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _record(platform: str, urls: list[dict], game_id: str = "hk4e", version: str = "1.0.0", vendor: str = "mihoyo") -> dict:
    artifact = {
        "kind": "package" if platform == "windows" else "apk",
        "component": "game", "package_type": "full", "delivery_mode": "direct",
        "name": "game.zip" if platform == "windows" else "game.apk",
        "size": 10, "decompressed_size": 11,
        "checksum": {"md5": hashlib.md5(platform.encode()).hexdigest()}, "urls": urls,
    }
    value = {
        "schema_version": 2, "vendor": vendor, "game_id": game_id,
        "domain_id": f"{game_id}-{'pc' if platform == 'windows' else 'android'}",
        "platform": platform, "channel": "official", "version": version,
        "version_code": None if platform == "windows" else 1,
        "file_time": "2026-08-29T00:00:00Z", "artifacts": [artifact],
        "references": [], "is_visible": True,
        "provenance": {"source_kind": "official_sync", "source_name": "fixture"},
    }
    identity = {key: value[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    artifact["artifact_id"] = artifact_id(artifact, record_identity=identity)
    validate_v2_record(value)
    return value


def _url(name: str, source_kind: str = "official", checked_at: str | None = None, state: str = "available") -> dict:
    value = {"url": f"https://autopatchcn.yuanshen.com/{name}", "provider": "fixture", "source_kind": source_kind, "priority": 0}
    if checked_at is not None:
        value["current"] = {"state": state, "checked_at": checked_at}
    return value


def _probe(url: str, **kwargs):
    return {
        "adapter": "fixture", "platform": kwargs.get("platform"), "url": url,
        "target_url": url, "http_code": 206, "available": True,
        "checked_at": "2026-09-14T12:00:00Z", "observed_size": 10,
        "size": 10, "etag": "fixture", "last_modified": None, "reason": "HTTP 206",
    }


class ScheduledProbeEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.data, self.state = root / "data", root / "state"
        self.data.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _save(self, value):
        write_v2_record(value, self.data)
        rebuild_index(self.data, value["vendor"], value["game_id"], value["platform"])

    def _wait(self, manager):
        for _ in range(300):
            view = manager.latest()
            if view["status"] not in {"running", "cancelling"}:
                return view
            time.sleep(0.01)
        self.fail("operation did not finish")

    def test_normal_uses_one_snapshot_and_counts_only_due_candidates(self):
        stamp = lambda delta: (NOW + delta).isoformat().replace("+00:00", "Z")
        urls = [
            _url("fresh.apk", checked_at=stamp(-timedelta(hours=19))),
            _url("boundary.apk", checked_at=stamp(-timedelta(hours=20))),
            _url("stale.apk", checked_at=stamp(-timedelta(hours=20, minutes=1))),
            _url("future.apk", checked_at=stamp(timedelta(minutes=1))),
            _url("invalid.apk", checked_at="not-a-timestamp"),
            _url("legacy.apk", "legacy", checked_at=stamp(-timedelta(hours=21))),
            _url("legacy-fresh.apk", "legacy", checked_at=stamp(-timedelta(hours=19))),
            _url("mirror.apk", "mirror", checked_at=stamp(-timedelta(hours=21))),
            _url("unknown.apk", "unknown"),
            _url("gone.apk", checked_at=stamp(-timedelta(hours=21)), state="unavailable"),
            _url("inconclusive.apk", checked_at=stamp(-timedelta(hours=21)), state="unknown"),
            _url("never-probed.apk"),
        ]
        original = _record("android", urls)
        self._save(original)
        calls = []

        def probe(url, **kwargs):
            calls.append(url.rsplit("/", 1)[-1])
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data, probe_fn=probe, current_fn=current_from_result, clock=lambda: NOW)
        started = manager.start(["probe"], ["hk4e"], "android", 5, 1, scheduled_mode="normal")
        finished = self._wait(manager)
        self.assertEqual(started["phase_total"], 5)
        self.assertEqual(finished["result"]["probe"]["selected"], 5)
        self.assertEqual(finished["result"]["probe"]["checked"], 5)
        self.assertEqual(set(calls), {"boundary.apk", "stale.apk", "future.apk", "invalid.apk", "legacy.apk"})
        self.assertTrue(any("自动探活任务 scheduled_mode=normal" in line for line in finished["logs"]))
        saved = json.loads((self.data / "mihoyo/hk4e/android/1.0.0.json").read_text())
        for index in (1, 2, 3, 4, 5):
            saved["artifacts"][0]["urls"][index]["current"] = original["artifacts"][0]["urls"][index]["current"]
        self.assertEqual(saved, original)

    def test_full_selects_official_and_legacy_and_scope_all_covers_both_platforms(self):
        stamp = NOW.isoformat().replace("+00:00", "Z")
        urls = [
            _url("fresh", "official", stamp), _url("legacy", "legacy", stamp),
            _url("gone", "official", stamp, "unavailable"),
            _url("uncertain", "legacy", stamp, "unknown"),
            _url("never-probed"), _url("unknown", "unknown", stamp),
            _url("mirror", "mirror", stamp),
        ]
        self._save(_record("android", deepcopy(urls)))
        self._save(_record("windows", deepcopy(urls)))
        calls = []

        def probe(url, **kwargs):
            calls.append((kwargs["platform"], url.rsplit("/", 1)[-1]))
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data, probe_fn=probe, current_fn=current_from_result, clock=lambda: NOW)
        manager.start(["probe"], ["hk4e"], "all", 5, 2, scheduled_mode="full")
        finished = self._wait(manager)
        self.assertEqual(finished["result"]["probe"]["selected"], 4)
        self.assertEqual(finished["result"]["probe"]["checked"], 4)
        self.assertEqual({platform for platform, _name in calls}, {"android", "windows"})
        self.assertEqual({name for _platform, name in calls}, {"fresh", "legacy"})

    def test_scheduled_discovery_then_probes_new_and_historical_urls(self):
        self._save(_record("android", [
            _url("old.apk", "legacy", (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")),
            _url("unprobed-history.apk"),
        ]))
        discovered = _record("android", [_url("new.apk")], version="2.0.0")
        calls = []

        def discovery(game_ids, root, timeout, workers, *, scope, progress, cancelled):
            self.assertEqual((game_ids, scope), (["hk4e"], "android"))
            write_v2_record(discovered, root)
            item = {"game_id": "hk4e", "platform": "android", "ok": True,
                    "status": "created", "version": "2.0.0", "new": True}
            progress(item, 1, 1)
            return {"items": [item]}

        def probe(url, **kwargs):
            calls.append(url.rsplit("/", 1)[-1])
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data,
                                   discovery=discovery, probe_fn=probe,
                                   current_fn=current_from_result, clock=lambda: NOW)
        manager.start(["discover", "probe"], ["hk4e"], "android", 5, 1,
                      scheduled_mode="normal")
        finished = self._wait(manager)
        self.assertEqual(finished["status"], "finished")
        self.assertEqual(finished["result"]["discover"]["new_versions"], 1)
        self.assertEqual(finished["result"]["probe"]["checked"], 2)
        self.assertEqual(set(calls), {"old.apk", "new.apk"})
        for version, source_kind in (("1.0.0", "legacy"), ("2.0.0", "official")):
            saved = json.loads((self.data / f"mihoyo/hk4e/android/{version}.json").read_text())
            url = saved["artifacts"][0]["urls"][0]
            self.assertEqual(url["source_kind"], source_kind)
            self.assertEqual(url["current"]["state"], "available")

    def test_scheduled_probe_still_checks_history_when_discovery_fails(self):
        self._save(_record("android", [
            _url("old.apk", "legacy", (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")),
            _url("unprobed-history.apk"),
        ]))
        calls = []

        def failing_discovery(*args, **kwargs):
            raise OSError("official endpoint unavailable")

        def probe(url, **kwargs):
            calls.append(url.rsplit("/", 1)[-1])
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data,
                                   discovery=failing_discovery, probe_fn=probe,
                                   current_fn=current_from_result, clock=lambda: NOW)
        manager.start(["discover", "probe"], ["hk4e"], "android", 5, 1,
                      scheduled_mode="normal")
        finished = self._wait(manager)
        self.assertEqual(finished["status"], "finished")
        self.assertEqual(finished["result"]["discover"]["failed"], 1)
        self.assertEqual(finished["result"]["probe"]["checked"], 1)
        self.assertEqual(calls, ["old.apk"])

    def test_pc_discovery_initially_probes_only_new_and_previously_available_urls(self):
        stamp = (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")
        self._save(_record("windows", [
            _url("old.7z", checked_at=stamp),
            _url("unprobed-history.7z"),
        ]))
        discovered = _record("windows", [_url("new.7z")], version="2.0.0")
        calls = []

        def discovery(game_ids, root, timeout, workers, *, scope, progress, cancelled):
            self.assertEqual(scope, "pc")
            write_v2_record(discovered, root)
            item = {"game_id": "hk4e", "platform": "windows", "ok": True,
                    "status": "created", "version": "2.0.0", "new": True}
            progress(item, 1, 1)
            return {"items": [item]}

        def probe(url, **kwargs):
            calls.append(url.rsplit("/", 1)[-1])
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data,
                                   discovery=discovery, probe_fn=probe,
                                   current_fn=current_from_result, clock=lambda: NOW)
        manager.start(["discover", "probe"], ["hk4e"], "pc", 5, 1,
                      scheduled_mode="normal")
        finished = self._wait(manager)
        self.assertEqual(finished["result"]["probe"]["checked"], 2)
        self.assertEqual(set(calls), {"old.7z", "new.7z"})

    def test_azurpromilia_probes_android_apk_and_pc_sentinels_only(self):
        stamp = (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")
        android_record = _record(
            "android", [_url("azurpromilia/android/c000/test.apk", checked_at=stamp)],
            game_id="azurpromilia", vendor="manjuu",
        )
        pc_record = _record(
            "windows", [_url("azurpromilia/pg_chunk/c000/part1", checked_at=stamp)],
            game_id="azurpromilia", vendor="manjuu",
        )
        pc_identity = {
            key: pc_record[key]
            for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")
        }
        pc_artifacts = [
            {
                "kind": "package", "component": "game", "package_type": "segment",
                "delivery_mode": "direct", "name": f"pg_chunk.{part:04d}", "part": part,
                "size": 10, "checksum": {"md5": "a" * 32},
                "urls": [_url(f"azurpromilia/pg_chunk/c000/part{part}", checked_at=stamp)],
            }
            for part in (1, 2, 3)
        ] + [{
            "kind": "package", "component": "game", "package_type": "full",
            "delivery_mode": "file_manifest", "name": "AzurPromilia-1.0.0-pg_item_v2",
            "size": 30, "decompressed_size": 30,
            "manifest": {"path": "manifests/1.0.0/pg_item_v2.json", "base_urls": [_url("azurpromilia/pg_item_v2/target/")]},
            "urls": [_url("azurpromilia/pg_item_v2/c000/mf-1.txt", checked_at=stamp)],
        }]
        for item in pc_artifacts:
            item["artifact_id"] = artifact_id(item, record_identity=pc_identity)
        pc_record["artifacts"] = pc_artifacts
        validate_v2_record(pc_record)
        self._save(android_record)
        self._save(pc_record)

        probed_names: list[str] = []

        def probe(url, **kwargs):
            probed_names.append(url.rsplit("/", 1)[-1])
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data,
                                   probe_fn=probe, current_fn=current_from_result, clock=lambda: NOW)
        manager.start(["probe"], ["azurpromilia"], "all", 5, 1, scheduled_mode="full")
        finished = self._wait(manager)
        self.assertEqual(finished["result"]["probe"]["selected"], 3)
        self.assertEqual(finished["result"]["probe"]["checked"], 3)
        self.assertEqual(set(probed_names), {"test.apk", "part1", "mf-1.txt"})

    def test_confirmed_unavailable_stops_future_scheduled_probes(self):
        stamp = (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")
        self._save(_record("android", [_url("old.apk", "legacy", stamp)]))
        calls = []

        def probe(url, **kwargs):
            calls.append(url)
            return {**_probe(url, **kwargs), "http_code": 404, "available": False, "reason": "HTTP 404"}

        manager = OperationManager(AdminStateStore(self.state), self.data,
                                   probe_fn=probe, current_fn=current_from_result, clock=lambda: NOW)
        manager.start(["probe"], ["hk4e"], "android", 5, 1, scheduled_mode="full")
        first = self._wait(manager)
        self.assertEqual(first["result"]["probe"]["unavailable"], 1)
        saved = json.loads((self.data / "mihoyo/hk4e/android/1.0.0.json").read_text())
        self.assertEqual(saved["artifacts"][0]["urls"][0]["current"]["state"], "unavailable")
        manager.start(["probe"], ["hk4e"], "android", 5, 1, scheduled_mode="full")
        second = self._wait(manager)
        self.assertEqual(second["result"]["probe"]["selected"], 0)
        self.assertEqual(len(calls), 1)

    def test_probe_failure_keeps_available_url_in_future_rotation(self):
        from probe_adapters.common import ProbeError

        stamp = (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")
        self._save(_record("android", [_url("old.apk", checked_at=stamp)]))
        calls = []

        def failing_probe(url, **kwargs):
            calls.append(url)
            raise ProbeError("fixture timeout")

        manager = OperationManager(AdminStateStore(self.state), self.data,
                                   probe_fn=failing_probe, clock=lambda: NOW)
        for _ in range(2):
            manager.start(["probe"], ["hk4e"], "android", 5, 1, scheduled_mode="normal")
            finished = self._wait(manager)
            self.assertEqual(finished["result"]["probe"]["selected"], 1)
            self.assertEqual(finished["result"]["probe"]["failed"], 1)
        self.assertEqual(len(calls), 2)

    def test_scheduled_mode_validation_and_shutdown_share_active_guard(self):
        self._save(_record("android", [_url("game.apk", checked_at=(NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z"))]))
        gate = Event()
        probe_started = Event()

        def slow_probe(url, **kwargs):
            probe_started.set()
            gate.wait(2)
            return _probe(url, **kwargs)

        manager = OperationManager(AdminStateStore(self.state), self.data, probe_fn=slow_probe, current_fn=current_from_result, clock=lambda: NOW)
        with self.assertRaises(ValueError):
            manager.start(["discover"], ["hk4e"], "android", 5, 1, scheduled_mode="normal")
        manager.start(["probe"], ["hk4e"], "android", 5, 1, scheduled_mode="full")
        self.assertTrue(probe_started.wait(1))
        with self.assertRaises(RuntimeError):
            manager.start(["probe"], ["hk4e"], "android", 5, 1)
        self.assertTrue(manager.shutdown(0.01) is False)
        gate.set()
        self.assertTrue(manager.shutdown(2))

    def test_single_url_manual_probe_and_background_jobs_share_slot(self):
        self._save(_record("android", [_url("game.apk")]))
        manager = OperationManager(AdminStateStore(self.state), self.data, probe_fn=_probe, clock=lambda: NOW)
        manager.begin_manual_probe()
        with self.assertRaises(RuntimeError):
            manager.start(["probe"], ["hk4e"], "all", 1, 1, scheduled_mode="normal")
        with self.assertRaises(RuntimeError):
            manager.begin_manual_probe()
        manager.end_manual_probe()
        manager.start(["probe"], ["hk4e"], "all", 1, 1, scheduled_mode="normal")
        self.assertEqual(self._wait(manager)["status"], "finished")

    def test_filtered_record_failure_counts_selected_official_and_legacy_candidates(self):
        from backend.admin_operations import _scheduled_candidate_filter
        stamp = (NOW - timedelta(hours=21)).isoformat().replace("+00:00", "Z")
        self._save(_record("android", [_url("official.apk", checked_at=stamp), _url("legacy.apk", "legacy", checked_at=stamp)]))
        events = []
        with patch("backend.admin_probe._probe_record", side_effect=OSError("fixture failure")):
            result = probe_records(
                self.data, selected_records(self.data, ["hk4e"], "android"), 1, 1,
                candidate_filter=_scheduled_candidate_filter("full", NOW, frozenset()),
                progress=lambda item, done, total: events.append((done, total)),
            )
        self.assertEqual((result["selected"], result["checked"], result["failed"]), (2, 2, 2))
        self.assertEqual(events, [(1, 2), (2, 2)])
        self.assertEqual([item["url_index"] for item in result["items"]], [0, 1])


if __name__ == "__main__":
    unittest.main()
