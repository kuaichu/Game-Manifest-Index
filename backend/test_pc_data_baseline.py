"""Audit coverage for the checked-in canonical PC data baseline."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, validate_v2_record
from scripts.migrate_pc_data_baseline import (
    ALLOWED_PROVENANCE,
    SOURCE_COMMIT,
    SOURCE_TREE,
    migrate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
AUDIT_PATH = PROJECT_ROOT / "scripts" / "migrate_pc_data_baseline_audit.json"
SOURCE_REPO = Path(os.environ.get("GMI_PC_BASELINE_SOURCE_REPO", PROJECT_ROOT.parent / "GMI"))
GAMES = (
    ("mihoyo", "hk4e"), ("mihoyo", "hkrpg"), ("mihoyo", "nap"),
    ("mihoyo", "bh3"), ("kuro", "wuwa"),
    ("perfectworld", "tof"), ("perfectworld", "p5x"), ("perfectworld", "nte"),
)
EXPECTED_RECORDS = {
    ("mihoyo", "hk4e"): 56, ("mihoyo", "hkrpg"): 18,
    ("mihoyo", "nap"): 19, ("mihoyo", "bh3"): 32,
    ("kuro", "wuwa"): 45, ("perfectworld", "tof"): 1,
    ("perfectworld", "p5x"): 1, ("perfectworld", "nte"): 1,
}
EXPECTED_ARTIFACTS = {
    ("mihoyo", "hk4e"): 697, ("mihoyo", "hkrpg"): 244,
    ("mihoyo", "nap"): 437, ("mihoyo", "bh3"): 27,
    ("kuro", "wuwa"): 91, ("perfectworld", "tof"): 1,
    ("perfectworld", "p5x"): 1, ("perfectworld", "nte"): 1,
}
EXPECTED_REFERENCES = {
    ("mihoyo", "hk4e"): 25, ("mihoyo", "hkrpg"): 12,
    ("mihoyo", "nap"): 17, ("mihoyo", "bh3"): 9,
    ("kuro", "wuwa"): 0, ("perfectworld", "tof"): 0,
    ("perfectworld", "p5x"): 0, ("perfectworld", "nte"): 0,
}
FORBIDDEN = {
    "url", "filename", "status", "adapter", "source_released_at", "attributes",
    "checksum_type", "checksum_value", "chunk_summary", "kuro_manifest", "evidence",
    "route_part", "official_api", "official_launcher",
}
FORBIDDEN_CURRENT = {
    "reason", "confidence", "retained", "expected_size", "observed_size", "evidence_status", "md5",
}
CURRENT_RECORDS = {
    ("mihoyo", "hk4e", "5.5.0"), ("mihoyo", "hk4e", "7.0.0"),
    ("mihoyo", "hkrpg", "4.4.0"), ("mihoyo", "hkrpg", "4.5.0"),
    ("mihoyo", "nap", "3.1.0"), ("mihoyo", "bh3", "8.4.0"),
    ("mihoyo", "bh3", "9.0.0"), ("kuro", "wuwa", "3.6.0"),
    ("perfectworld", "tof", "6.3.3"), ("perfectworld", "p5x", "1.0.74"),
    ("perfectworld", "nte", "1.3.13"),
}
OFFICIAL_SOURCES = {
    ("mihoyo", "hk4e", "5.5.0"): (
        "MiHoYo HoYoPlay getGamePackages",
        "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids%5B%5D=1Z8W5NHUQb",
    ),
    ("mihoyo", "hk4e", "7.0.0"): (
        "HoYoPlay/Sophon", "https://api-takumi.mihoyo.com/downloader/sophon_chunk/api/getBuild",
    ),
    ("mihoyo", "hkrpg", "4.4.0"): (
        "MiHoYo HoYoPlay getGamePackages",
        "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids%5B%5D=64kMb5iAWu",
    ),
    ("mihoyo", "hkrpg", "4.5.0"): (
        "HoYoPlay/Sophon", "https://api-takumi.mihoyo.com/downloader/sophon_chunk/api/getBuild",
    ),
    ("mihoyo", "nap", "3.1.0"): (
        "MiHoYo HoYoPlay getGamePackages",
        "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids%5B%5D=x6znKlJ0xK",
    ),
    ("mihoyo", "bh3", "8.4.0"): (
        "MiHoYo HoYoPlay getGamePackages",
        "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids%5B%5D=osvnlOc0S8",
    ),
    ("mihoyo", "bh3", "9.0.0"): (
        "HoYoPlay/Sophon", "https://api-takumi.mihoyo.com/downloader/sophon_chunk/api/getBuild",
    ),
    ("kuro", "wuwa", "3.6.0"): (
        "Kuro GameStarter",
        "https://prod-cn-alicdn-gamestarter.kurogame.com/launcher/game/G152/10003_Y8xXrXk65DqFHEDgApn3cpK5lfczpFx5/index.json",
    ),
    ("perfectworld", "tof", "6.3.3"): (
        "Perfect World PatcherSDK", "https://htcdn1.wmupd.com/clientRes/Windows55/Version/Windows/config.xml",
    ),
    ("perfectworld", "p5x", "1.0.74"): (
        "Perfect World PatcherSDK", "https://nsywl-client-dev1.wmupd.com/clientRes/CN_OB_OFFICIAL/Version/Windows/config.xml",
    ),
    ("perfectworld", "nte", "1.3.13"): (
        "Perfect World PatcherSDK", "https://yhcdn1.wmupd.com/clientRes/publish_PC/Version/Windows/config.xml",
    ),
}


def _source_available() -> bool:
    if not SOURCE_REPO.is_dir():
        return False
    return subprocess.run(
        ["git", "-C", str(SOURCE_REPO), "cat-file", "-e", f"{SOURCE_COMMIT}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _records() -> list[tuple[Path, dict]]:
    result = []
    for vendor, game_id in GAMES:
        directory = DATA_ROOT / vendor / game_id / "pc"
        for path in sorted(directory.glob("*.json")):
            if path.name != "index.json":
                result.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return result


def _is_current_overlay(relative: Path) -> bool:
    if len(relative.parts) < 4 or relative.parts[2] != "pc":
        return False
    vendor, game_id = relative.parts[:2]
    tail = relative.parts[3:]
    for current_vendor, current_game, version in CURRENT_RECORDS:
        if (vendor, game_id) != (current_vendor, current_game):
            continue
        if tail == (f"{version}.json",):
            return True
        if len(tail) >= 3 and tail[:2] == ("manifests", version):
            return True
        if tail == ("chunk-manifests", f"{version}.json"):
            return True
    return False


class PcDataBaselineTests(unittest.TestCase):
    def test_checked_in_migration_audit_is_complete(self):
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(audit["source_commit"], SOURCE_COMMIT)
        self.assertEqual(audit["source_tree"], SOURCE_TREE)
        self.assertEqual(audit["source_files"], {"records": 185, "manifests": 110, "indexes": 8})
        self.assertEqual(
            (audit["written_records"], audit["written_artifacts"], audit["written_manifests"]),
            (168, 1449, 106),
        )
        self.assertEqual(audit["exclusions"], {
            "empty_after_conversion": 1,
            "hkrpg_zh_tw_without_semantics": 12,
            "kuro_route_manifest_unpaired": 648,
            "official_api_chunk_reference": 1,
            "provenance_official_launcher": 4,
        })
        detailed = {}
        for item in audit["exclusion_details"]:
            self.assertTrue(item["source_path"].startswith("data/") and item["source_path"].endswith(".json"))
            detailed[item["reason"]] = detailed.get(item["reason"], 0) + item["count"]
        self.assertEqual(detailed, audit["exclusions"])

    def test_fixed_snapshot_migration_inventory_and_exclusions(self):
        if not _source_available():
            self.skipTest(f"fixed source object is unavailable: {SOURCE_REPO}")
        with tempfile.TemporaryDirectory() as directory:
            summary = migrate(SOURCE_REPO, Path(directory) / "data")
        self.assertEqual(summary, json.loads(AUDIT_PATH.read_text(encoding="utf-8")))
        self.assertEqual(summary["source_commit"], SOURCE_COMMIT)
        self.assertEqual(summary["source_tree"], SOURCE_TREE)
        self.assertEqual(summary["source_files"], {"records": 185, "manifests": 110, "indexes": 8})
        self.assertEqual(summary["written_records"], 168)
        self.assertEqual(summary["written_artifacts"], 1449)
        self.assertEqual(summary["written_manifests"], 106)
        self.assertEqual(summary["exclusions"], {
            "empty_after_conversion": 1,
            "hkrpg_zh_tw_without_semantics": 12,
            "kuro_route_manifest_unpaired": 648,
            "official_api_chunk_reference": 1,
            "provenance_official_launcher": 4,
        })

    def test_records_are_canonical_unique_and_source_safe(self):
        counts = {game: 0 for game in GAMES}
        artifacts = {game: 0 for game in GAMES}
        references = {game: 0 for game in GAMES}
        ids: dict[str, Path] = {}
        seen_current = set()
        for path, record in _records():
            game = (record["vendor"], record["game_id"])
            segment_parts = {}
            counts[game] += 1
            validate_v2_record(record)
            self.assertEqual(record["platform"], "windows")
            self.assertIn(record["provenance"]["source_kind"], {"official_sync", *ALLOWED_PROVENANCE})
            if record["provenance"]["source_kind"] == "official_sync":
                source_key = (*game, record["version"])
                seen_current.add(source_key)
                self.assertIn(source_key, OFFICIAL_SOURCES)
                self.assertEqual(
                    (record["provenance"].get("source_name"), record["provenance"].get("source_url")),
                    OFFICIAL_SOURCES[source_key],
                )
                for reference in record["references"]:
                    self.assertIn(reference.get("source", {}).get("source_kind"), {"official_sync", *ALLOWED_PROVENANCE})
            else:
                self.assertNotIn(record["provenance"]["source_kind"], {"official", "official_api", "official_launcher"})
            identity = {key: record[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
            for artifact in record["artifacts"]:
                artifacts[game] += 1
                self.assertEqual(artifact["artifact_id"], artifact_id(artifact, identity), path)
                self.assertNotIn(artifact["artifact_id"], ids, path)
                ids[artifact["artifact_id"]] = path
                self.assertTrue(FORBIDDEN.isdisjoint(artifact))
                if artifact["package_type"] == "segment":
                    key = (artifact["component"], artifact.get("language"))
                    segment_parts.setdefault(key, []).append(artifact["part"])
                for url in artifact["urls"]:
                    self.assertTrue(FORBIDDEN_CURRENT.isdisjoint(url.get("current", {})))
            for key, parts in segment_parts.items():
                self.assertEqual(sorted(parts), list(range(1, len(parts) + 1)), (path, key))
            references[game] += len(record["references"])
            self.assertTrue(FORBIDDEN.isdisjoint(record))
            self.assertNotIn("zh-tw", json.dumps(record, ensure_ascii=False).lower())
        self.assertEqual(counts, EXPECTED_RECORDS)
        self.assertEqual(artifacts, EXPECTED_ARTIFACTS)
        self.assertEqual(references, EXPECTED_REFERENCES)
        self.assertEqual(seen_current, CURRENT_RECORDS)
        self.assertEqual(len(ids), 1499)

    def test_manifest_and_reference_paths_are_safe_and_parseable(self):
        referenced = set()
        for path, record in _records():
            for artifact in record["artifacts"]:
                manifest = artifact.get("manifest")
                if manifest is None:
                    continue
                self.assertEqual(set(manifest), {"path", "base_urls"} if "base_urls" in manifest else {"path"})
                target = path.parent / manifest["path"]
                self.assertTrue(target.is_file(), target)
                referenced.add(target.resolve())
                document = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(document.get("schema_version"), 1)
                self.assertNotIn("kuro_manifest", json.dumps(document, ensure_ascii=False))
                self.assertNotIn('"password"', json.dumps(document, ensure_ascii=False).lower())
            for reference in record["references"]:
                self.assertEqual(reference["kind"], "chunk_manifest")
                target = path.parent / reference["path"]
                self.assertTrue(target.is_file(), target)
                referenced.add(target.resolve())
                document = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(document.get("schema_version"), 1)
                self.assertNotIn('"password"', json.dumps(document, ensure_ascii=False).lower())
        stored = {
            path.resolve()
            for vendor, game_id in GAMES
            for directory in (
                DATA_ROOT / vendor / game_id / "pc" / "manifests",
                DATA_ROOT / vendor / game_id / "pc" / "chunk-manifests",
            )
            if directory.is_dir()
            for path in directory.rglob("*.json")
        }
        self.assertEqual(stored, referenced)

    def test_pc_indexes_rebuild_without_difference(self):
        for vendor, game_id in GAMES:
            directory = DATA_ROOT / vendor / game_id / "pc"
            checked = json.loads((directory / "index.json").read_text(encoding="utf-8"))
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "data"
                target = root / vendor / game_id
                target.parent.mkdir(parents=True)
                shutil.copytree(directory, target / "pc")
                rebuilt = json.loads(rebuild_index(root, vendor, game_id, "windows").read_text(encoding="utf-8"))
            self.assertEqual(rebuilt, checked, (vendor, game_id))

    def test_android_objects_match_parent_branch(self):
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", "integration/pc", "--", "data"], text=True,
        ).splitlines()
        self.assertFalse([path for path in changed if "/android/" in path], changed)

    def test_migration_reruns_from_git_objects(self):
        if not _source_available():
            self.skipTest(f"fixed source object is unavailable: {SOURCE_REPO}")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            left = Path(first) / "data"
            right = Path(second) / "data"
            migrate(SOURCE_REPO, left)
            migrate(SOURCE_REPO, right)
            left_files = sorted(path.relative_to(left) for path in left.rglob("*.json"))
            right_files = sorted(path.relative_to(right) for path in right.rglob("*.json"))
            self.assertEqual(left_files, right_files)
            for relative in left_files:
                self.assertEqual((left / relative).read_bytes(), (right / relative).read_bytes(), relative)
                if not _is_current_overlay(relative):
                    self.assertEqual((left / relative).read_bytes(), (DATA_ROOT / relative).read_bytes(), relative)


if __name__ == "__main__":
    unittest.main()
