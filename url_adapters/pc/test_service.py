import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import artifact_id, validate_v2_record
from url_adapters.common import AdapterError
from url_adapters.service import PC_DISCOVERERS, _discover_pc_one, discover_games, discovery_task_count


class PCDiscoveryServiceTests(unittest.TestCase):
    IDENTITIES = {
        "hk4e": ("mihoyo", "hk4e-pc"),
        "hkrpg": ("mihoyo", "hkrpg-pc"),
        "nap": ("mihoyo", "nap-pc"),
        "bh3": ("mihoyo", "bh3-pc"),
        "wuwa": ("kuro", "wuwa-pc"),
        "tof": ("perfectworld", "tof-pc"),
        "p5x": ("perfectworld", "p5x-pc"),
        "nte": ("perfectworld", "nte-pc"),
    }

    @classmethod
    def canonical_record(cls, game_id, version, *, with_artifact=True, references=None):
        vendor, domain_id = cls.IDENTITIES[game_id]
        record = {
            "schema_version": 2,
            "vendor": vendor,
            "game_id": game_id,
            "domain_id": domain_id,
            "platform": "windows",
            "channel": "official",
            "version": version,
            "version_code": None,
            "file_time": None,
            "artifacts": [],
            "references": list(references or []),
        }
        if with_artifact:
            artifact = {
                "artifact_id": "placeholder",
                "kind": "package",
                "component": "game",
                "package_type": "full",
                "delivery_mode": "archive",
                "name": f"{game_id}-{version}.zip",
                "urls": [{
                    "url": f"https://example.test/{game_id}-{version}.zip",
                    "provider": "test",
                    "source_kind": "official",
                    "priority": 0,
                }],
            }
            identity = {
                key: record[key]
                for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")
            }
            artifact["artifact_id"] = artifact_id(artifact, identity)
            record["artifacts"].append(artifact)
        validate_v2_record(record)
        return record

    @staticmethod
    def chunk_reference(version, name="current"):
        return {
            "kind": "chunk_manifest",
            "path": f"chunk-manifests/{version}-{name}.json",
            "build_id": f"build-{name}",
            "source": {
                "source_kind": "official_sync",
                "source_name": "test",
                "source_url": f"https://example.test/{version}/{name}",
            },
        }

    @classmethod
    def write_record(cls, root, game_id, version, *, with_artifact=True, references=None):
        vendor, _ = cls.IDENTITIES[game_id]
        path = root / vendor / game_id / "pc" / f"{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = cls.canonical_record(
            game_id,
            version,
            with_artifact=with_artifact,
            references=references,
        )
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def test_registry_is_exactly_eight_current_modules(self):
        expected = {"hk4e", "hkrpg", "nap", "bh3", "wuwa", "tof", "p5x", "nte"}
        self.assertEqual(set(PC_DISCOVERERS), expected)
        for game_id, stages in PC_DISCOVERERS.items():
            names = [name for name, _ in stages]
            self.assertEqual(
                names,
                ["packages", "chunks"]
                if game_id in {"hk4e", "hkrpg", "nap", "bh3"}
                else ["manifests"]
                if game_id == "wuwa"
                else ["packages"],
            )
            for _, discoverer in stages:
                self.assertNotIn("old", discoverer.__module__)
                self.assertNotIn("legacy", discoverer.__module__)
        self.assertEqual(discovery_task_count(list(PC_DISCOVERERS), "pc"), 8)

    def test_mihoyo_same_version_stages_preserve_artifacts_and_references(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_reference = self.chunk_reference("1.0.0", "old")
            new_reference = self.chunk_reference("1.0.0", "new")

            def packages(game_id, output_root, timeout):
                calls.append(("packages", timeout))
                return self.write_record(
                    output_root,
                    game_id,
                    "1.0.0",
                    references=[old_reference],
                )

            def chunks(game_id, output_root, timeout):
                calls.append(("chunks", timeout))
                return self.write_record(
                    output_root,
                    game_id,
                    "1.0.0",
                    references=[old_reference, new_reference],
                )

            registry = {"hk4e": (("packages", packages), ("chunks", chunks))}
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                result = discover_games(["hk4e"], root, timeout=3, workers=1, scope="pc")
            item = result["items"][0]
            record = json.loads(Path(item["path"]).read_text(encoding="utf-8"))

        self.assertEqual(calls, [("packages", 3), ("chunks", 3)])
        self.assertEqual(item["versions"], ["1.0.0"])
        self.assertEqual([stage["new"] for stage in item["stages"]], [True, False])
        self.assertTrue(item["new"])
        self.assertEqual(result["new_versions"], 1)
        self.assertEqual(len(record["artifacts"]), 1)
        self.assertEqual(record["references"], [old_reference, new_reference])

    def test_same_path_stage_rejects_dropped_artifact_or_reference(self):
        for lost, expected_error in (
            ("artifact", "丢失既有 artifact"),
            ("reference", "丢失既有 reference"),
        ):
            with self.subTest(lost=lost), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                old_reference = self.chunk_reference("1.0.0", "old")
                new_reference = self.chunk_reference("1.0.0", "new")

                def packages(game_id, output_root, timeout):
                    return self.write_record(
                        output_root,
                        game_id,
                        "1.0.0",
                        references=[old_reference],
                    )

                def chunks(game_id, output_root, timeout):
                    return self.write_record(
                        output_root,
                        game_id,
                        "1.0.0",
                        with_artifact=lost != "artifact",
                        references=[new_reference] if lost == "reference" else [old_reference, new_reference],
                    )

                registry = {"hk4e": (("packages", packages), ("chunks", chunks))}
                with patch.dict(PC_DISCOVERERS, registry, clear=True):
                    result = discover_games(["hk4e"], root, timeout=1, workers=1, scope="pc")

                item = result["items"][0]
                self.assertFalse(item["ok"])
                self.assertTrue(item["stages"][0]["ok"])
                self.assertFalse(item["stages"][1]["ok"])
                self.assertIn(expected_error, item["stages"][1]["error"])

    def test_mihoyo_different_versions_are_reported_as_separate_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def packages(game_id, output_root, timeout):
                return self.write_record(output_root, game_id, "1.0.0")

            def chunks(game_id, output_root, timeout):
                return self.write_record(
                    output_root,
                    game_id,
                    "2.0.0",
                    with_artifact=False,
                    references=[self.chunk_reference("2.0.0")],
                )

            registry = {"hk4e": (("packages", packages), ("chunks", chunks))}
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                result = discover_games(["hk4e"], root, timeout=1, workers=1, scope="pc")
            item = result["items"][0]
            saved = sorted(path.name for path in (root / "mihoyo" / "hk4e" / "pc").glob("*.json"))

        self.assertEqual(item["versions"], ["1.0.0", "2.0.0"])
        self.assertEqual(len(item["paths"]), 2)
        self.assertIsNone(item["version"])
        self.assertIsNone(item["path"])
        self.assertEqual(result["new_versions"], 2)
        self.assertEqual(saved, ["1.0.0.json", "2.0.0.json"])

    def test_kuro_and_perfectworld_use_one_stage_each(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(game_id, output_root, timeout):
                return self.write_record(output_root, game_id, "1.0.0")

            registry = {
                "wuwa": (("manifests", write),),
                "nte": (("packages", write),),
            }
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                result = discover_games(["wuwa", "nte"], root, timeout=1, workers=2, scope="pc")

        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(
            [[stage["name"] for stage in item["stages"]] for item in result["items"]],
            [["manifests"], ["packages"]],
        )

    def test_concurrent_failure_is_isolated_and_results_keep_input_order(self):
        started = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def good(game_id, output_root, timeout):
                self.assertTrue(started.wait(1))
                return self.write_record(output_root, game_id, "1.0.0")

            def bad(game_id, output_root, timeout):
                started.set()
                raise AdapterError("boom")

            registry = {
                "wuwa": (("manifests", good),),
                "nte": (("packages", bad),),
            }
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                result = discover_games(["wuwa", "nte"], root, timeout=1, workers=2, scope="pc")

        self.assertEqual([item["game_id"] for item in result["items"]], ["wuwa", "nte"])
        self.assertEqual((result["succeeded"], result["failed"]), (1, 1))
        self.assertTrue(result["items"][0]["ok"])
        self.assertTrue(result["items"][1]["supported"])
        self.assertEqual(result["items"][1]["stages"][0]["error"], "boom")

    def test_failed_mihoyo_stage_does_not_skip_later_stage(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def packages(*args):
                calls.append("packages")
                raise AdapterError("packages unavailable")

            def chunks(game_id, output_root, timeout):
                calls.append("chunks")
                return self.write_record(
                    output_root,
                    game_id,
                    "2.0.0",
                    with_artifact=False,
                    references=[self.chunk_reference("2.0.0")],
                )

            registry = {"hk4e": (("packages", packages), ("chunks", chunks))}
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                result = discover_games(["hk4e"], root, timeout=1, workers=1, scope="pc")

        item = result["items"][0]
        self.assertEqual(calls, ["packages", "chunks"])
        self.assertFalse(item["ok"])
        self.assertEqual([stage["ok"] for stage in item["stages"]], [False, True])
        self.assertEqual(item["versions"], ["2.0.0"])
        self.assertEqual(result["new_versions"], 1)

    def test_cancellation_stops_queued_games(self):
        cancelled = threading.Event()
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def first(game_id, output_root, timeout):
                calls.append(game_id)
                path = self.write_record(output_root, game_id, "1.0.0")
                cancelled.set()
                return path

            def queued(game_id, output_root, timeout):
                calls.append(game_id)
                return self.write_record(output_root, game_id, "1.0.0")

            registry = {
                "wuwa": (("manifests", first),),
                "nte": (("packages", queued),),
            }
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                result = discover_games(
                    ["wuwa", "nte"],
                    root,
                    timeout=1,
                    workers=1,
                    cancelled=cancelled.is_set,
                    scope="pc",
                )

        self.assertEqual(calls, ["wuwa"])
        self.assertEqual([item["game_id"] for item in result["items"]], ["wuwa"])
        self.assertEqual(result["selected"], 2)
        self.assertTrue(result["cancelled"])

    def test_timeout_and_worker_bounds_apply_to_pc_scope(self):
        observed = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write(game_id, output_root, timeout):
                observed.append(timeout)
                return self.write_record(output_root, game_id, "1.0.0")

            with patch.dict(PC_DISCOVERERS, {"wuwa": (("manifests", write),)}, clear=True):
                result = discover_games(["wuwa"], root, timeout=7, workers=3, scope="pc")
            self.assertTrue(result["items"][0]["ok"])
            for timeout, workers in ((0, 1), (1, 0), (True, 1), (1, True)):
                with self.subTest(timeout=timeout, workers=workers):
                    with self.assertRaises(ValueError):
                        discover_games([], root, timeout=timeout, workers=workers, scope="pc")

        self.assertEqual(observed, [7])

    def test_relative_root_is_not_prefixed_twice(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                root = Path("data")

                def write(game_id, output_root, timeout):
                    return self.write_record(output_root, game_id, "1.0.0")

                with patch.dict(PC_DISCOVERERS, {"wuwa": (("manifests", write),)}, clear=True):
                    result = discover_games(["wuwa"], root, timeout=1, workers=1, scope="pc")
                returned = Path(result["items"][0]["path"])
                expected = (root / "kuro" / "wuwa" / "pc" / "1.0.0.json").resolve()
                self.assertEqual(returned, expected)
                self.assertTrue(returned.is_file())
            finally:
                os.chdir(original_cwd)

    def test_unknown_game_isolated_and_unexpected_runtime_bubbles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = discover_games(["unknown"], root, timeout=1, workers=1, scope="pc")
            self.assertFalse(result["items"][0]["supported"])
            self.assertEqual(result["items"][0]["status"], "failed")
            registry = {
                "hk4e": (("packages", lambda *args: (_ for _ in ()).throw(RuntimeError("bug"))),),
            }
            with patch.dict(PC_DISCOVERERS, registry, clear=True):
                with self.assertRaises(RuntimeError):
                    discover_games(["hk4e"], root, timeout=1, workers=1, scope="pc")

    def test_pc_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                discover_games(["wuwa", "wuwa"], Path(directory), timeout=1, workers=2, scope="pc")

    def test_unknown_single_discovery_raises_adapter_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AdapterError):
                _discover_pc_one("unknown", Path(directory), 1)


if __name__ == "__main__":
    unittest.main()
