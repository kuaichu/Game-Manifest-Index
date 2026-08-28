"""Regression coverage for the checked-in Android APK data baseline."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.indexes import rebuild_index
from backend.schema_v2 import validate_v2_record


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
EXPECTED_COUNTS = {
    ("hypergryph", "arknights"): 23,
    ("hypergryph", "endfield"): 3,
    ("kuro", "pns"): 3,
    ("kuro", "wuwa"): 32,
    ("mihoyo", "bh2"): 33,
    ("mihoyo", "bh3"): 57,
    ("mihoyo", "hk4e"): 55,
    ("mihoyo", "hkrpg"): 30,
    ("mihoyo", "nap"): 19,
    ("perfectworld", "nte"): 3,
    ("perfectworld", "p5x"): 10,
    ("perfectworld", "tof"): 1,
}
FORBIDDEN_RECORD_FIELDS = {
    "url", "filename", "size", "checksum", "status", "adapter", "source_released_at",
}
FORBIDDEN_ARTIFACT_FIELDS = {
    "attributes", "checksum_type", "checksum_value", "chunk_summary", "kuro_manifest", "evidence",
}
FORBIDDEN_CURRENT_FIELDS = {
    "reason", "confidence", "retained", "expected_size", "observed_size", "evidence_status", "md5",
}
FORBIDDEN_MARKERS = ("amarea", "hoyofiles", "github", "community", "社区")


class ApkDataBaselineTests(unittest.TestCase):
    def test_expected_android_records_and_canonical_shape(self):
        found = {}
        for vendor, game_id in EXPECTED_COUNTS:
            directory = DATA_ROOT / vendor / game_id / "android"
            self.assertTrue(directory.is_dir(), directory)
            files = sorted(directory.glob("*.json"))
            self.assertEqual(len(files), EXPECTED_COUNTS[(vendor, game_id)] + 1, directory)
            self.assertEqual([p.name for p in files].count("index.json"), 1)
            for path in files:
                if path.name == "index.json":
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                validate_v2_record(record)
                self.assertEqual(record["platform"], "android")
                self.assertIsInstance(record["references"], list)
                self.assertTrue(record["artifacts"])
                self.assertTrue(all(a.get("kind") == "apk" for a in record["artifacts"]))
                self.assertTrue(set(record).isdisjoint(FORBIDDEN_RECORD_FIELDS), path)
                for artifact in record["artifacts"]:
                    self.assertTrue(set(artifact).isdisjoint(FORBIDDEN_ARTIFACT_FIELDS), path)
                    for url in artifact.get("urls", []):
                        if isinstance(url.get("current"), dict):
                            self.assertTrue(set(url["current"]).isdisjoint(FORBIDDEN_CURRENT_FIELDS), path)
                serialized = json.dumps(record, ensure_ascii=False).lower()
                self.assertFalse(any(marker in serialized for marker in FORBIDDEN_MARKERS), path)
                found[(vendor, game_id)] = found.get((vendor, game_id), 0) + 1
        self.assertEqual(found, EXPECTED_COUNTS)
        self.assertEqual(sum(found.values()), 269)

    def test_indexes_are_reproducible_and_match_visible_versions(self):
        for vendor, game_id in EXPECTED_COUNTS:
            directory = DATA_ROOT / vendor / game_id / "android"
            checked_index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
            versions = {
                json.loads(path.read_text(encoding="utf-8"))["version"]
                for path in directory.glob("*.json")
                if path.name != "index.json"
            }
            self.assertEqual({entry["version"] for entry in checked_index["versions"]}, versions)
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "data"
                target = root / vendor / game_id
                target.parent.mkdir(parents=True)
                shutil.copytree(directory, target / "android")
                rebuilt_path = rebuild_index(root, vendor, game_id, "android")
                rebuilt = json.loads(rebuilt_path.read_text(encoding="utf-8"))
            self.assertEqual(rebuilt, checked_index, (vendor, game_id))


if __name__ == "__main__":
    unittest.main()
