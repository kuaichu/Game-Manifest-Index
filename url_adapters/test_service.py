import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import artifact_id, validate_v2_record
from url_adapters.android import (
    hypergryph_launcher_latest, kuro_pns_manifest, kuro_wuwa_mc_manifest,
    mihoyo_bh2_download_page, mihoyo_bh3_download_porter, mihoyo_download_porter,
    perfectworld_webops,
)
from url_adapters.common import AdapterError
from url_adapters.service import DISCOVERERS, _discover_one, discovery_task_count, discover_games


class DiscoveryServiceTests(unittest.TestCase):
    def test_registry_has_exactly_twelve_games_and_v2_discoverers(self):
        expected = {
            "hk4e": mihoyo_download_porter.discover_v2, "hkrpg": mihoyo_download_porter.discover_v2,
            "nap": mihoyo_download_porter.discover_v2, "bh3": mihoyo_bh3_download_porter.discover_v2,
            "bh2": mihoyo_bh2_download_page.discover_v2, "arknights": hypergryph_launcher_latest.discover_v2,
            "endfield": hypergryph_launcher_latest.discover_v2, "wuwa": kuro_wuwa_mc_manifest.discover_v2,
            "pns": kuro_pns_manifest.discover_v2, "tof": perfectworld_webops.discover_v2,
            "p5x": perfectworld_webops.discover_v2, "nte": perfectworld_webops.discover_v2,
        }
        self.assertEqual(set(DISCOVERERS), set(expected))
        for game_id, discoverer in expected.items():
            with self.subTest(game_id=game_id):
                self.assertIs(DISCOVERERS[game_id], discoverer)
                self.assertNotIn("old", discoverer.__module__)
                self.assertNotIn("legacy", discoverer.__module__)
        self.assertEqual(discovery_task_count(list(DISCOVERERS)), 12)

    @staticmethod
    def canonical_record(game_id="hk4e", version="2.0.0"):
        record = {"schema_version": 2, "vendor": "test", "game_id": game_id,
                  "domain_id": f"{game_id}-android", "platform": "android", "channel": "official",
                  "version": version, "version_code": None, "file_time": None,
                  "artifacts": [{"artifact_id": "placeholder", "kind": "apk", "component": "game",
                                  "package_type": "full", "delivery_mode": "direct", "name": "game.apk",
                                  "urls": [{"url": "https://example.test/game.apk", "provider": "test",
                                            "source_kind": "official", "priority": 0}]}], "references": []}
        identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
        record["artifacts"][0]["artifact_id"] = artifact_id(record["artifacts"][0], record_identity=identity)
        validate_v2_record(record)
        return record

    def test_discover_passes_canonical_arguments_and_reports_new_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "demo" / "hk4e" / "android"
            target.mkdir(parents=True)
            (target / "1.0.0.json").write_text("{}", encoding="utf-8")

            def discover(game_id, output_root, timeout, version, version_code):
                self.assertEqual((game_id, output_root, timeout, version, version_code),
                                 ("hk4e", root, 3, None, None))
                path = target / "2.0.0.json"
                path.write_text(json.dumps(self.canonical_record()), encoding="utf-8")
                return path

            with patch.dict(DISCOVERERS, {"hk4e": discover}, clear=True):
                result = discover_games(["hk4e"], root, timeout=3, workers=1)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["new_versions"], 1)

    def test_concurrent_tasks_collect_failure_without_stopping_other_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            started = threading.Event()

            def discover(game_id, output_root, timeout, version, version_code):
                if game_id == "bad":
                    started.set()
                    raise AdapterError("boom")
                started.wait(1)
                path = output_root / f"{game_id}.json"
                path.write_text(json.dumps(self.canonical_record(game_id, "1.0.0")), encoding="utf-8")
                return path

            with patch.dict(DISCOVERERS, {"bad": discover, "good": discover}, clear=True):
                result = discover_games(["bad", "good"], root, timeout=1, workers=2)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual({item["game_id"] for item in result["items"]}, {"bad", "good"})

    def test_unexpected_runtime_error_bubbles_out(self):
        with tempfile.TemporaryDirectory() as directory:
            def broken(*args):
                raise RuntimeError("program bug")
            with patch.dict(DISCOVERERS, {"hk4e": broken}, clear=True):
                with self.assertRaises(RuntimeError):
                    discover_games(["hk4e"], Path(directory), timeout=1, workers=1)

    def test_unknown_game_raises_adapter_error_for_single_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AdapterError):
                _discover_one("unknown", Path(directory), 1)

    def test_invalid_bounds_are_rejected_without_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kwargs in ({"timeout": 0, "workers": 1}, {"timeout": 1, "workers": 0},
                           {"timeout": True, "workers": 1}, {"timeout": 1, "workers": True}):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises((TypeError, ValueError)):
                        discover_games([], root, **kwargs)

    def test_cancellation_stops_submission_and_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(DISCOVERERS, {}, clear=True):
                result = discover_games([], Path(directory), timeout=1, workers=1,
                                        cancelled=lambda: True)
        self.assertTrue(result["cancelled"])


if __name__ == "__main__":
    unittest.main()
