"""Focused safety tests for the offline PC archive recovery tool."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from backend.schema_v2 import validate_v2_record
from scripts import recover_pc_history_from_archive_db as recovery_module
from scripts.recover_pc_history_from_archive_db import recover


MD5_A = "a" * 32
MD5_B = "b" * 32
MD5_C = "c" * 32
NTE_RECORD_PATH = "data/perfectworld/nte/pc/1.3.12.json"
NTE_MANIFEST_PATH = "data/perfectworld/nte/pc/manifests/1.3.12.json"


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return completed.stdout.strip()


def _nte_git_fixture(root: Path, *, manifest_edit=None) -> dict[str, str | int]:
    """Create a small pinned Git fixture with the production NTE shape."""
    record_path = root / NTE_RECORD_PATH
    manifest_path = root / NTE_MANIFEST_PATH
    record_path.parent.mkdir(parents=True)
    manifest_path.parent.mkdir(parents=True)
    file_specs = [
        ("Game.exe", 10, "a" * 32),
        ("Data/data.bin", 20, "b" * 32),
    ]
    files = [
        {"dest": dest, "size": size, "md5": md5,
         "urls": [f"https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/{md5[0]}/{md5}.{size}"]}
        for dest, size, md5 in file_specs
    ]
    patches = []
    for index, size in enumerate((2, 3, 4)):
        oldfile = f"{('c' + str(index)) * 16}.{size + 10}"
        newfile = f"{('d' + str(index)) * 16}.{size + 20}"
        patch = f"{('e' + str(index)) * 16}.{size}"
        patches.append({
            "oldfile": oldfile, "newfile": newfile, "patch": patch,
            "v": "1.3.12", "size": size,
            "url": f"https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/{patch[0]}/{patch}",
        })
    manifest = {
        "schema": "perfectworld-patcher-files-v1", "version": "1.3.12",
        "files": files, "patch_objects": patches,
    }
    if manifest_edit is not None:
        manifest_edit(manifest)
    full_size = sum(item["size"] for item in files)
    package_url = "https://yhcdn1.wmupd.com/clientRes/publish_PC/Version/Windows/version/1.3.12/ResList.bin.zip"
    record = {
        "vendor": "perfectworld", "game_id": "nte", "domain_id": "nte-pc",
        "platform": "windows", "adapter": "perfectworld_patcher", "channel": "official",
        "version": "1.3.12", "version_code": None, "file_time": None,
        "provenance": {"source_kind": "official_launcher", "source_url": recovery_module.NTE_LEGACY_SOURCE_URL},
        "artifacts": [
            {"kind": "manifest", "name": "config.xml", "size": recovery_module.NTE_LEGACY_CONFIG_BYTES,
             "urls": [{"url": recovery_module.NTE_LEGACY_SOURCE_URL, "provider": recovery_module.NTE_LEGACY_HOST, "source_kind": "official"}]},
            {"kind": "package", "name": "ResList.bin.zip", "size": full_size,
             "attributes": {"component": "game", "package_type": "full", "delivery_mode": "file_manifest",
                            "local_manifest": NTE_MANIFEST_PATH, "manifest_urls": [package_url],
                            "decoded_file_count": 2, "full_size": full_size, "patch_object_count": 3,
                            "config_res_size": full_size, "reslist_size": 20, "config_hash": "abc123",
                            "flags": {"compressed": "1", "encrypt": "1"}, "base_versions": ""},
             "urls": [{"url": package_url, "provider": recovery_module.NTE_LEGACY_HOST, "source_kind": "official"}]},
        ],
    }
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Recovery Test")
    _git(root, "add", NTE_RECORD_PATH, NTE_MANIFEST_PATH)
    _git(root, "commit", "-qm", "fixture")
    commit = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", f"{commit}^{{tree}}")
    return {
        "commit": commit, "tree": tree,
        "record_blob": _git(root, "rev-parse", f"{commit}:{NTE_RECORD_PATH}"),
        "manifest_blob": _git(root, "rev-parse", f"{commit}:{NTE_MANIFEST_PATH}"),
        "record_bytes": int(_git(root, "cat-file", "-s", _git(root, "rev-parse", f"{commit}:{NTE_RECORD_PATH}"))),
        "manifest_bytes": int(_git(root, "cat-file", "-s", _git(root, "rev-parse", f"{commit}:{NTE_MANIFEST_PATH}"))),
        "file_size": full_size,
    }


def _nte_allowlist(constants: dict[str, str | int]) -> dict[str, str | int]:
    return {
        "NTE_LEGACY_COMMIT": constants["commit"], "NTE_LEGACY_TREE": constants["tree"],
        "NTE_LEGACY_RECORD_BLOB": constants["record_blob"], "NTE_LEGACY_MANIFEST_BLOB": constants["manifest_blob"],
        "NTE_LEGACY_RECORD_BYTES": constants["record_bytes"], "NTE_LEGACY_MANIFEST_BYTES": constants["manifest_bytes"],
        "NTE_LEGACY_FILE_COUNT": 2, "NTE_LEGACY_PATCH_COUNT": 3,
        "NTE_LEGACY_FILE_SIZE": constants["file_size"],
    }


def _db(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE games (id TEXT PRIMARY KEY, platform TEXT NOT NULL);
        CREATE TABLE archive_domains (id TEXT PRIMARY KEY, platform TEXT NOT NULL);
        CREATE TABLE game_versions (
            id INTEGER PRIMARY KEY, game_id TEXT, domain_id TEXT, version TEXT,
            current_revision_id INTEGER, is_visible INTEGER
        );
        CREATE TABLE version_revisions (
            id INTEGER PRIMARY KEY, game_version_id INTEGER, attributes_json TEXT,
            capture_event_id INTEGER
        );
        CREATE TABLE capture_events (id INTEGER PRIMARY KEY, source_url TEXT);
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY, revision_id INTEGER, kind TEXT, name TEXT,
            part INTEGER, size INTEGER, checksum_type TEXT, checksum_value TEXT,
            attributes_json TEXT
        );
        CREATE TABLE artifact_urls (
            id INTEGER PRIMARY KEY, artifact_id INTEGER, url TEXT,
            priority INTEGER, source_kind TEXT
        );
        """
    )
    db.executemany("INSERT INTO games VALUES (?, ?)", [("hkrpg", "windows"), ("p5x", "windows"), ("endfield", "windows")])
    db.executemany("INSERT INTO archive_domains VALUES (?, ?)", [("hkrpg-pc", "windows"), ("p5x-pc", "windows"), ("endfield-resources", "windows")])
    db.executemany(
        "INSERT INTO game_versions VALUES (?, ?, ?, ?, ?, ?)",
        [(1, "hkrpg", "hkrpg-pc", "1.5.0", 11, 1), (2, "p5x", "p5x-pc", "1.0.74", 22, 1), (3, "endfield", "endfield-resources", "1.0.13", 33, 1)],
    )
    db.executemany(
        "INSERT INTO version_revisions VALUES (?, ?, ?, ?)",
        [
            (11, 1, json.dumps({"provenance": {"source_kind": "hoyofiles-split-archive", "source_url": "https://hoyo-files.amarea.cn"}}), None),
            (22, 2, json.dumps({"provenance": {"source_kind": "legacy_patchersdk_catalog_list"}}), None),
            (33, 3, json.dumps({"initial_file_count": 1, "main_file_count": 0, "resource_version": "initial_x_main_x"}), None),
        ],
    )
    db.executemany(
        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (101, 11, "package", "StarRail_1.5.0.zip", 1, 100, "md5", MD5_A, json.dumps({"component": "game", "package_type": "full"})),
            (102, 11, "package", "Chinese.zip", 2, 10, "md5", MD5_B, json.dumps({"component": "voice", "package_type": "optional_component", "language": "zh-tw"})),
            (103, 11, "patch", "game_1.4.0_1.5.0_hdiff.zip", 3, 20, "md5", MD5_C, json.dumps({"component": "game", "package_type": "differential", "route_from": "1.4.0", "route_to": "1.5.0"})),
            (201, 22, "manifest", "ResList.bin.zip", 1, 20, None, None, json.dumps({})),
            (202, 22, "file", "Game.exe", 2, 50, "md5", MD5_A, json.dumps({"relative_path": "Game.exe", "object": f"{MD5_A}.50"})),
            (203, 22, "patch", "patch.zip", 3, 5, "md5", MD5_B, json.dumps({"old_object": "old.40", "new_object": "new.50", "patch_object": f"{MD5_B}.5"})),
            (301, 33, "resource", "VFS/ABCD/file.chk", 1, 7, "md5", MD5_C.upper(), json.dumps({"manifest": 0, "resource_kind": "initial", "type": 1, "current": {"state": "available"}})),
        ],
    )
    db.executemany(
        "INSERT INTO artifact_urls VALUES (?, ?, ?, ?, ?)",
        [
            (1, 101, "https://autopatchcn.bhsr.com/StarRail_1.5.0.zip", 0, "official"),
            (2, 102, "https://autopatchcn.bhsr.com/Chinese.zip", 0, "official"),
            (3, 103, "https://autopatchcn.bhsr.com/game_1.4.0_1.5.0_hdiff.zip", 0, "official"),
            (4, 201, "https://nsywl-client-dev1.wmupd.com/clientRes/CN/Version/1.0.74/ResList.bin.zip", 0, "official"),
            (5, 202, f"https://nsywl-client-dev1.wmupd.com/clientRes/CN/Res/{MD5_A[0]}/{MD5_A}.50", 0, "official"),
            (6, 203, f"https://nsywl-client-dev1.wmupd.com/clientRes/CN/Res/{MD5_B[0]}/{MD5_B}.5", 0, "official"),
            (7, 301, f"https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.0/resource/Windows/initial/x/files/VFS/ABCD/file.chk?auth_key=secret&keep=%2B", 0, "official"),
        ],
    )
    db.commit()
    db.close()


class PcDataRecoveryTests(unittest.TestCase):
    @staticmethod
    def _file_snapshot(root: Path) -> dict[str, bytes]:
        if not root.exists():
            return {}
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and path.name != ".gmi-data.lock"
        }

    def test_endfield_resources_use_current_revision_and_secondary_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            db = sqlite3.connect(database)
            old_md5 = "d" * 32
            current_md5 = "E" * 32
            db.execute(
                "INSERT INTO version_revisions VALUES (?, ?, ?, ?)",
                (34, 3, json.dumps({"resource_version": "old", "initial_file_count": 1, "main_file_count": 0}), None),
            )
            db.execute(
                "INSERT INTO version_revisions VALUES (?, ?, ?, ?)",
                (35, 3, json.dumps({"resource_version": "current", "initial_file_count": 0, "main_file_count": 1}), None),
            )
            db.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (302, 34, "resource", "old/file.chk", 1, 2, "md5", old_md5, json.dumps({"resource_kind": "initial"})),
            )
            db.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (303, 35, "resource", "VFS/current/file.chk", 1, 9, "md5", current_md5, json.dumps({"resource_kind": "main", "current": {"state": "available"}})),
            )
            db.execute(
                "INSERT INTO artifact_urls VALUES (?, ?, ?, ?, ?)",
                (8, 302, f"https://beyond.hycdn.cn/old/{old_md5}.2", 0, "official"),
            )
            db.execute(
                "INSERT INTO artifact_urls VALUES (?, ?, ?, ?, ?)",
                (9, 303, "https://beyond.hycdn.cn/current/file.chk?auth_key=secret&keep=a%2Bb", 0, "official"),
            )
            db.execute("UPDATE game_versions SET current_revision_id = ? WHERE id = 3", (35,))
            db.commit()
            db.close()

            result = recover(database, output, domains={"endfield-resources"}, apply=True)
            self.assertEqual(result["planned_records"], 1)
            candidate = result["candidates"][0]
            self.assertEqual(candidate["current_revision"], 35)
            self.assertEqual(candidate["resource_audit"]["metadata"]["resource_version"], "current")
            target = output / "hypergryph/endfield/pc/domains/endfield-resources/1.0.13.json"
            self.assertTrue(target.is_file())
            resource_index_path = target.parent / "index.json"
            self.assertTrue(resource_index_path.is_file())
            resource_index = json.loads(resource_index_path.read_text(encoding="utf-8"))
            self.assertEqual(resource_index["domain_id"], "endfield-resources")
            self.assertEqual([item["version"] for item in resource_index["versions"]], ["1.0.13"])
            self.assertEqual(resource_index["versions"][0]["size"], 9)
            record = json.loads(target.read_text(encoding="utf-8"))
            validate_v2_record(record)
            self.assertEqual([item["name"] for item in record["artifacts"]], ["VFS/current/file.chk"])
            artifact = record["artifacts"][0]
            self.assertEqual(artifact["checksum"], {"md5": current_md5.lower()})
            self.assertEqual(set(artifact), {"artifact_id", "kind", "component", "name", "size", "checksum", "urls", "source"})
            self.assertNotIn("auth_key", artifact["urls"][0]["url"])
            self.assertIn("keep=a%2Bb", artifact["urls"][0]["url"])
            again = recover(database, output, domains={"endfield-resources"}, apply=True)
            self.assertEqual((again["planned_records"], again["written_records"]), (0, 0))
            self.assertEqual(json.loads(resource_index_path.read_text(encoding="utf-8")), resource_index)

    def test_endfield_resource_safety_and_same_version_domain_coexistence(self):
        mutations = (
            ("UPDATE artifacts SET name = ? WHERE id = 301", ("../escape.chk",)),
            ("UPDATE artifacts SET checksum_value = ? WHERE id = 301", ("not-md5",)),
            ("UPDATE artifact_urls SET url = ? WHERE artifact_id = 301", ("http://beyond.hycdn.cn/file.chk",)),
            ("UPDATE artifact_urls SET priority = ? WHERE artifact_id = 301", (-1,)),
            ("UPDATE artifact_urls SET url = ? WHERE artifact_id = 301", ("https://user:pass@beyond.hycdn.cn/file.chk",)),
        )
        for statement, values in mutations:
            with self.subTest(statement=statement):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    database = root / "archive.sqlite"
                    output = root / "data"
                    _db(database)
                    db = sqlite3.connect(database)
                    db.execute(statement, values)
                    db.commit()
                    db.close()
                    result = recover(database, output, domains={"endfield-resources"})
                    self.assertEqual(result["candidates"][0]["decision"], "block")
                    self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            default = output / "hypergryph/endfield/pc/1.0.13.json"
            default.parent.mkdir(parents=True)
            default.write_text('{"keep": true}\n', encoding="utf-8")
            result = recover(database, output, domains={"endfield-resources"}, apply=True)
            self.assertEqual(result["written_records"], 1)
            self.assertEqual(default.read_text(encoding="utf-8"), '{"keep": true}\n')
            self.assertTrue((output / "hypergryph/endfield/pc/domains/endfield-resources/1.0.13.json").is_file())

    def test_dry_run_is_read_only_and_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            dry = recover(database, output)
            self.assertEqual(dry["planned_records"], 3)
            self.assertEqual(dry["planned_manifests"], 1)
            self.assertFalse(output.exists())
            applied = recover(database, output, apply=True)
            self.assertEqual((applied["written_records"], applied["written_manifests"]), (3, 1))
            again = recover(database, output, apply=True)
            self.assertEqual(again["planned_records"], 0)
            self.assertEqual(again["skipped"]["existing_record_preserved"], 3)

            hkrpg = json.loads((output / "mihoyo/hkrpg/pc/1.5.0.json").read_text(encoding="utf-8"))
            validate_v2_record(hkrpg)
            self.assertEqual(hkrpg["provenance"]["source_kind"], "third_party_history")
            self.assertEqual(hkrpg["artifacts"][1]["language"], "zh-tw")
            self.assertNotIn("current", json.dumps(hkrpg))
            manifest = json.loads((output / "perfectworld/p5x/pc/manifests/1.0.74/files.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files"]), 1)
            self.assertEqual(len(manifest["patch_objects"]), 1)
            resource_path = output / "hypergryph/endfield/pc/domains/endfield-resources/1.0.13.json"
            resource = json.loads(resource_path.read_text(encoding="utf-8"))
            validate_v2_record(resource)
            self.assertEqual(resource["domain_id"], "endfield-resources")
            self.assertEqual(resource["artifacts"][0]["kind"], "resource")
            self.assertEqual(resource["artifacts"][0]["component"], "resource")
            self.assertEqual(resource["artifacts"][0]["checksum"]["md5"], MD5_C)
            self.assertEqual(resource["artifacts"][0]["urls"][0]["provider"], "beyond.hycdn.cn")
            self.assertNotIn("auth_key", resource["artifacts"][0]["urls"][0]["url"])
            self.assertIn("keep=%2B", resource["artifacts"][0]["urls"][0]["url"])
            self.assertNotIn("current", json.dumps(resource))

    def test_dry_run_report_is_detailed_stable_and_uses_read_only_uri(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            report = root / "reports/recovery.json"
            _db(database)
            real_connect = recovery_module.sqlite3.connect
            observed: list[str] = []

            def connect(database_uri, **kwargs):
                observed.append(database_uri)
                return real_connect(database_uri, **kwargs)

            with mock.patch.object(recovery_module.sqlite3, "connect", side_effect=connect):
                first = recover(database, output, report=report)
            first_bytes = report.read_bytes()
            second = recover(database, output, report=report)
            self.assertEqual(first_bytes, report.read_bytes())
            self.assertEqual(first["decision_counts"], {"plan": 3, "skip": 0, "block": 0})
            self.assertEqual(second["decision_counts"], first["decision_counts"])
            self.assertFalse(output.exists())
            self.assertTrue(observed[0].endswith("?mode=ro&immutable=1"))

            candidate = next(item for item in first["candidates"] if item["domain"] == "hkrpg-pc")
            for field in (
                "domain", "version", "source_db", "source_file", "current_revision",
                "artifact_count", "artifact_kinds", "url_count", "url_source_kinds",
                "canonical_provenance", "safe_conversion_status", "existing_v5_record",
                "content_conflict", "decision", "reason", "expected_record_path",
                "expected_manifest_paths", "serialized_bytes",
            ):
                self.assertIn(field, candidate)
            self.assertEqual(candidate["decision"], "plan")
            self.assertEqual(candidate["serialized_bytes"]["record"], candidate["expected_record_bytes"])
            resource = next(item for item in first["candidates"] if item["domain"] == "endfield-resources")
            self.assertEqual(resource["canonical_provenance"]["source_name"], "Game-Manifest-Index legacy Endfield resources archive")
            self.assertEqual(
                recovery_module._compact_provenance(
                    "endfield", "endfield-pc", "1.0.13",
                    {"source_kind": "legacy_endfield_launcher_aggregate"}, None,
                )["source_name"],
                "Game-Manifest-Index legacy Endfield archive",
            )
            self.assertEqual(resource["resource_audit"]["revision"], 33)
            self.assertEqual(resource["resource_audit"]["total"], 1)
            self.assertEqual(resource["resource_audit"]["initial"], 1)
            self.assertEqual(resource["resource_audit"]["main"], 0)
            self.assertEqual(resource["resource_audit"]["urls"], {"total": 1, "official": 1, "mirror": 0, "md5": 1})
            self.assertEqual(resource["resource_metadata"]["resource_version"], "initial_x_main_x")

    def test_existing_identical_and_conflict_are_reported_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            recover(database, output, apply=True)

            identical = recover(database, output)
            hkrpg = next(item for item in identical["candidates"] if item["domain"] == "hkrpg-pc")
            self.assertEqual(hkrpg["existing_v5_content"], "identical")
            self.assertEqual(hkrpg["decision"], "skip")
            self.assertFalse(hkrpg["content_conflict"])

            target = output / "mihoyo/hkrpg/pc/1.5.0.json"
            original = target.read_bytes()
            value = json.loads(original)
            value["is_visible"] = False
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            conflicted = recover(database, output)
            hkrpg = next(item for item in conflicted["candidates"] if item["domain"] == "hkrpg-pc")
            self.assertEqual(hkrpg["existing_v5_content"], "conflict")
            self.assertTrue(hkrpg["content_conflict"])
            self.assertEqual(hkrpg["decision"], "skip")
            before = target.read_bytes()
            recover(database, output, apply=True)
            self.assertEqual(before, target.read_bytes())
            self.assertNotEqual(original, target.read_bytes())

    def test_identical_record_with_missing_manifest_is_repaired_idempotently(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            recover(database, output, apply=True)
            manifest = output / "perfectworld/p5x/pc/manifests/1.0.74/files.json"
            manifest.unlink()

            dry = recover(database, output)
            candidate = next(item for item in dry["candidates"] if item["domain"] == "p5x-pc")
            self.assertEqual(candidate["decision"], "plan")
            self.assertEqual(candidate["reason"], "missing_manifest_for_identical_record")
            self.assertEqual((dry["planned_records"], dry["planned_manifests"]), (0, 1))

            applied = recover(database, output, apply=True)
            self.assertEqual((applied["written_records"], applied["written_manifests"]), (0, 1))
            self.assertTrue(manifest.is_file())
            repeated = recover(database, output, apply=True)
            self.assertEqual((repeated["planned_records"], repeated["planned_manifests"]), (0, 0))

    def test_missing_manifest_guard_rejects_record_changed_inside_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            recover(database, output, apply=True)
            manifest = output / "perfectworld/p5x/pc/manifests/1.0.74/files.json"
            record = output / "perfectworld/p5x/pc/1.0.74.json"
            manifest.unlink()
            before = self._file_snapshot(output)
            original_lock = recovery_module.data_file_lock

            @contextmanager
            def writer_lock(data_root):
                with original_lock(data_root):
                    value = json.loads(record.read_text(encoding="utf-8"))
                    value["is_visible"] = False
                    record.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    yield

            with mock.patch.object(recovery_module, "data_file_lock", writer_lock):
                with self.assertRaisesRegex(recovery_module.RecoveryError, "guarded existing record changed"):
                    recover(database, output, apply=True)
            after = self._file_snapshot(output)
            self.assertFalse(manifest.exists())
            self.assertNotEqual(after.pop(record.relative_to(output).as_posix()), before.pop(record.relative_to(output).as_posix()))
            self.assertEqual(after, before)

    def test_missing_record_guard_rejects_manifest_changed_inside_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            recover(database, output, apply=True)
            manifest = output / "perfectworld/p5x/pc/manifests/1.0.74/files.json"
            record = output / "perfectworld/p5x/pc/1.0.74.json"
            record.unlink()
            before = self._file_snapshot(output)
            original_lock = recovery_module.data_file_lock

            @contextmanager
            def writer_lock(data_root):
                with original_lock(data_root):
                    value = json.loads(manifest.read_text(encoding="utf-8"))
                    value["files"][0]["size"] += 1
                    manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    yield

            with mock.patch.object(recovery_module, "data_file_lock", writer_lock):
                with self.assertRaisesRegex(recovery_module.RecoveryError, "guarded existing manifest changed"):
                    recover(database, output, apply=True)
            after = self._file_snapshot(output)
            self.assertFalse(record.exists())
            self.assertNotEqual(after.pop(manifest.relative_to(output).as_posix()), before.pop(manifest.relative_to(output).as_posix()))
            self.assertEqual(after, before)

    def test_conflicting_record_does_not_repair_missing_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            recover(database, output, apply=True)
            record = output / "perfectworld/p5x/pc/1.0.74.json"
            value = json.loads(record.read_text(encoding="utf-8"))
            value["is_visible"] = False
            record.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest = output / "perfectworld/p5x/pc/manifests/1.0.74/files.json"
            manifest.unlink()

            result = recover(database, output, apply=True)
            candidate = next(item for item in result["candidates"] if item["domain"] == "p5x-pc")
            self.assertEqual(candidate["decision"], "skip")
            self.assertEqual(candidate["reason"], "existing_v5_record_conflict")
            self.assertFalse(manifest.exists())

    def test_publication_failure_rolls_back_new_files_and_indexes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            before = self._file_snapshot(output)
            real_link = recovery_module.os.link
            publications = 0

            def link(source, target):
                nonlocal publications
                if ".pc-recovery-" in str(source):
                    publications += 1
                    if publications == 2:
                        raise OSError("injected publication failure")
                return real_link(source, target)

            with mock.patch.object(recovery_module.os, "link", side_effect=link):
                with self.assertRaisesRegex(OSError, "injected publication failure"):
                    recover(database, output, apply=True)
            self.assertEqual(self._file_snapshot(output), before)

    def test_target_appearing_after_preflight_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            before = self._file_snapshot(output)
            real_link = recovery_module.os.link
            links = 0
            concurrent_target = None

            def link(source, target):
                nonlocal links, concurrent_target
                links += 1
                if links == 2:
                    concurrent_target = target
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"concurrent writer")
                    raise FileExistsError(target)
                return real_link(source, target)

            with mock.patch.object(recovery_module.os, "link", side_effect=link):
                with self.assertRaises(FileExistsError):
                    recover(database, output, apply=True)
            self.assertIsNotNone(concurrent_target)
            self.assertEqual(concurrent_target.read_bytes(), b"concurrent writer")
            self.assertEqual(self._file_snapshot(output), {
                concurrent_target.relative_to(output).as_posix(): b"concurrent writer",
            })

    def test_rollback_leaves_publication_replaced_after_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            replaced = output / "hypergryph/endfield/pc/domains/endfield-resources/1.0.13.json"
            real_rebuild = recovery_module.rebuild_index
            rebuilds = 0

            def rebuild(*args, **kwargs):
                nonlocal rebuilds
                rebuilds += 1
                if rebuilds == 2:
                    replacement = replaced.with_name(".concurrent-replacement")
                    replacement.write_bytes(b"concurrent replacement")
                    recovery_module.os.replace(replacement, replaced)
                    raise OSError("injected rebuild failure")
                return real_rebuild(*args, **kwargs)

            with mock.patch.object(recovery_module, "rebuild_index", side_effect=rebuild):
                with self.assertRaisesRegex(OSError, "injected rebuild failure"):
                    recover(database, output, apply=True)
            self.assertEqual(replaced.read_bytes(), b"concurrent replacement")
            self.assertEqual(self._file_snapshot(output), {
                replaced.relative_to(output).as_posix(): b"concurrent replacement",
            })

    def test_stage_is_cleaned_when_lock_acquisition_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)

            with mock.patch.object(recovery_module, "data_file_lock", side_effect=OSError("injected lock failure")):
                with self.assertRaisesRegex(OSError, "injected lock failure"):
                    recover(database, output, apply=True)
            self.assertEqual(list(root.glob(".pc-recovery-*")), [])

    def test_rebuild_failure_rolls_back_new_files_and_indexes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            original_index = output / "hypergryph/endfield/pc/index.json"
            original_index.parent.mkdir(parents=True)
            original_index.write_bytes(b'{"sentinel": true}\n')
            before = self._file_snapshot(output)
            real_rebuild = recovery_module.rebuild_index
            rebuilds = 0

            def rebuild(*args, **kwargs):
                nonlocal rebuilds
                rebuilds += 1
                if rebuilds == 2:
                    raise OSError("injected rebuild failure")
                return real_rebuild(*args, **kwargs)

            with mock.patch.object(recovery_module, "rebuild_index", side_effect=rebuild):
                with self.assertRaisesRegex(OSError, "injected rebuild failure"):
                    recover(database, output, apply=True)
            self.assertEqual(self._file_snapshot(output), before)

    def test_report_is_portable_across_output_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            _db(database)
            report_a = root / "a.json"
            report_b = root / "b.json"
            recover(database, root / "checkout-a/data", report=report_a)
            recover(database, root / "checkout-b/data", report=report_b)
            self.assertEqual(report_a.read_bytes(), report_b.read_bytes())
            rendered = report_a.read_text(encoding="utf-8")
            self.assertNotRegex(rendered, r"[A-Za-z]:\\")
            self.assertNotIn("checkout-a", rendered)
            self.assertNotIn("checkout-b", rendered)

    def test_approved_database_layout_retains_portable_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "Game-Manifest-Index/var/db/archive.sqlite"
            database.parent.mkdir(parents=True)
            _db(database)
            report_a = root / "a.json"
            report_b = root / "b.json"
            first = recover(database, root / "one/data", report=report_a)
            recover(database, root / "two/data", report=report_b)

            expected = {
                "kind": "approved_legacy_repository_database",
                "repository": "Game-Manifest-Index",
                "path": "var/db/archive.sqlite",
                "identity": "Game-Manifest-Index/var/db/archive.sqlite",
                "file": "archive.sqlite",
            }
            self.assertEqual(first["database_source"], expected)
            self.assertEqual(first["database"], expected["identity"])
            self.assertTrue(all(candidate["source"] == expected for candidate in first["candidates"]))
            self.assertTrue(all(candidate["source_db"] == expected["identity"] for candidate in first["candidates"]))
            self.assertEqual(report_a.read_bytes(), report_b.read_bytes())
            self.assertNotRegex(report_a.read_text(encoding="utf-8"), r"[A-Za-z]:\\")

    def test_android_sentinel_failure_rolls_back_only_pc_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            android = output / "mihoyo/hkrpg/android/sentinel.txt"
            android.parent.mkdir(parents=True)
            android.write_bytes(b"keep")
            original_index = output / "hypergryph/endfield/pc/index.json"
            original_index.parent.mkdir(parents=True)
            original_index.write_bytes(b'{"sentinel": true}\n')
            before = self._file_snapshot(output)
            real_snapshot = recovery_module._android_snapshot
            snapshots = 0

            def snapshot(path):
                nonlocal snapshots
                snapshots += 1
                actual = real_snapshot(path)
                if snapshots == 2:
                    return {**actual, "injected/concurrent.txt": b"changed"}
                return actual

            with mock.patch.object(recovery_module, "_android_snapshot", side_effect=snapshot):
                with self.assertRaisesRegex(recovery_module.RecoveryError, "Android data changed"):
                    recover(database, output, apply=True)

            self.assertEqual(android.read_bytes(), b"keep")
            self.assertEqual(self._file_snapshot(output), before)

    def test_source_root_is_filtered_when_domain_filter_excludes_nte(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            result = recover(database, output, domains={"hkrpg-pc"}, source_root=root / "legacy-git")
            self.assertEqual([item["domain"] for item in result["candidates"]], ["hkrpg-pc"])
            self.assertEqual(result["source_root"]["status"], "filtered")
            self.assertEqual(result["source_root"]["reason"], "domain_filter_excludes_nte-pc")
            self.assertFalse(output.exists())

    def test_pinned_nte_source_reads_commit_blob_not_dirty_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy-git"
            source.mkdir()
            constants = _nte_git_fixture(source)
            record_path = source / NTE_RECORD_PATH
            dirty = json.loads(record_path.read_text(encoding="utf-8"))
            dirty["version"] = "dirty-worktree"
            record_path.write_text(json.dumps(dirty), encoding="utf-8")
            with mock.patch.multiple(recovery_module, **_nte_allowlist(constants)):
                record, document, metadata = recovery_module._read_nte_legacy_source(source, str(constants["commit"]))
            self.assertEqual(record["version"], "1.3.12")
            self.assertEqual(len(document["files"]), 2)
            self.assertEqual(len(document["patch_objects"]), 3)
            self.assertEqual(metadata["source_tree"], constants["tree"])
            self.assertEqual(metadata["blobs"][NTE_RECORD_PATH]["bytes"], constants["record_bytes"])

    def test_pinned_nte_rejects_short_sha_and_ref(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "legacy-git"
            source.mkdir()
            constants = _nte_git_fixture(source)
            with mock.patch.multiple(recovery_module, **_nte_allowlist(constants)):
                for value in (str(constants["commit"])[:8], "HEAD"):
                    with self.assertRaises(recovery_module.RecoveryError):
                        recovery_module._read_nte_legacy_source(source, value)

    def test_pinned_nte_rejects_symlinked_source_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy-git"
            source.mkdir()
            constants = _nte_git_fixture(source)
            link = root / "legacy-link"
            try:
                link.symlink_to(source, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            with mock.patch.multiple(recovery_module, **_nte_allowlist(constants)):
                with self.assertRaises(recovery_module.RecoveryError):
                    recovery_module._read_nte_legacy_source(link, str(constants["commit"]))

    def test_pinned_nte_allowlist_checks_tree_blob_type_and_size(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "legacy-git"
            source.mkdir()
            constants = _nte_git_fixture(source)
            checks = (
                ("NTE_LEGACY_TREE", "0" * 40),
                ("NTE_LEGACY_RECORD_BLOB", "1" * 40),
                ("NTE_LEGACY_RECORD_BYTES", int(constants["record_bytes"]) + 1),
            )
            for name, value in checks:
                allowlist = _nte_allowlist(constants)
                allowlist[name] = value
                with mock.patch.multiple(recovery_module, **allowlist):
                    with self.assertRaises(recovery_module.RecoveryError):
                        recovery_module._read_nte_legacy_source(source, str(constants["commit"]))

    def test_pinned_nte_rejects_url_checksum_and_duplicate_destination(self):
        mutations = (
            lambda manifest: manifest["files"][0]["urls"].__setitem__(0, "https://evil.invalid/file"),
            lambda manifest: manifest["files"][0].__setitem__("md5", "not-md5"),
            lambda manifest: manifest["files"][1].__setitem__("dest", manifest["files"][0]["dest"]),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                with tempfile.TemporaryDirectory() as temp:
                    source = Path(temp) / "legacy-git"
                    source.mkdir()
                    constants = _nte_git_fixture(source, manifest_edit=mutate)
                    with mock.patch.multiple(recovery_module, **_nte_allowlist(constants)):
                        with self.assertRaises(recovery_module.RecoveryError):
                            recovery_module._read_nte_legacy_source(source, str(constants["commit"]))

    def test_pinned_nte_apply_is_idempotent_and_preserves_android(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy-git"
            source.mkdir()
            constants = _nte_git_fixture(source)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            android = output / "perfectworld/nte/android/sentinel.txt"
            android.parent.mkdir(parents=True)
            android.write_bytes(b"keep")
            with mock.patch.multiple(recovery_module, **_nte_allowlist(constants)):
                first = recover(database, output, domains={"nte-pc"}, source_root=source, apply=True)
                source_manifest = output / "perfectworld/nte/pc/manifests/1.3.12/files.json"
                source_manifest.unlink()
                repair_plan = recover(database, output, domains={"nte-pc"}, source_root=source)
                repaired = recover(database, output, domains={"nte-pc"}, source_root=source, apply=True)
                second = recover(database, output, domains={"nte-pc"}, source_root=source, apply=True)
            source_candidate = first["source_candidate"]
            self.assertEqual(source_candidate["canonical_provenance"], {
                "source_kind": "legacy_migration",
                "source_name": "official launcher legacy Git",
                "source_url": recovery_module.NTE_LEGACY_SOURCE_URL,
                "source_repo": "Game-Manifest-Index",
                "source_commit": constants["commit"],
            })
            self.assertEqual(first["source_root"]["status"], "ready")
            self.assertEqual(first["source_root"]["decision"], "plan")
            self.assertEqual(first["source_root"]["reason"], "pinned_source_candidate_planned")
            self.assertEqual(source_candidate["reason"], "missing_source_record_or_manifest")
            self.assertEqual((first["written_records"], first["written_manifests"]), (1, 1))
            self.assertEqual((repair_plan["planned_records"], repair_plan["planned_manifests"]), (0, 1))
            self.assertEqual((repaired["written_records"], repaired["written_manifests"]), (0, 1))
            self.assertEqual((second["planned_records"], second["written_records"]), (0, 0))
            self.assertEqual(android.read_bytes(), b"keep")
            record = json.loads((output / "perfectworld/nte/pc/1.3.12.json").read_text(encoding="utf-8"))
            validate_v2_record(record)

    def test_unsafe_candidate_is_blocked_while_other_versions_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            db = sqlite3.connect(database)
            db.execute("UPDATE artifact_urls SET url = ? WHERE artifact_id = 101", ("not-a-url",))
            db.commit()
            db.close()
            result = recover(database, output)
            hkrpg = next(item for item in result["candidates"] if item["domain"] == "hkrpg-pc")
            p5x = next(item for item in result["candidates"] if item["domain"] == "p5x-pc")
            self.assertEqual(hkrpg["decision"], "block")
            self.assertEqual(hkrpg["safe_conversion_status"], "unsafe")
            self.assertIn("URL", hkrpg["reason"])
            self.assertEqual(p5x["decision"], "plan")
            self.assertEqual(result["decision_counts"], {"plan": 2, "skip": 0, "block": 1})

    def test_duplicate_target_identity_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            _db(database)
            db = sqlite3.connect(database)
            db.execute("INSERT INTO game_versions VALUES (?, ?, ?, ?, ?, ?)", (4, "hkrpg", "hkrpg-pc", "1.5.0", 11, 1))
            db.commit()
            db.close()
            result = recover(database, output)
            duplicate_candidates = [item for item in result["candidates"] if item["domain"] == "hkrpg-pc"]
            self.assertEqual(len(duplicate_candidates), 2)
            self.assertTrue(all(item["decision"] == "block" for item in duplicate_candidates))
            self.assertEqual(result["blocked"]["duplicate_recovery_target"], 2)
            self.assertFalse(output.exists())

    def test_cli_aliases_and_apply_preserve_android(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "archive.sqlite"
            output = root / "data"
            report = root / "cli-report.json"
            _db(database)
            android = output / "mihoyo/hkrpg/android/sentinel.txt"
            android.parent.mkdir(parents=True)
            android.write_bytes(b"keep")
            script = Path(__file__).resolve().parents[1] / "scripts/recover_pc_history_from_archive_db.py"
            completed = subprocess.run(
                [
                    sys.executable, str(script), "--source-db", str(database),
                    "--source-root", str(root / "legacy"), "--output-root", str(output),
                    "--domains", "hkrpg-pc", "--report", str(report), "--apply",
                ],
                cwd=script.parents[1], capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(report.is_file())
            self.assertEqual(android.read_bytes(), b"keep")
            result = recover(database, output, domains={"hkrpg-pc"}, apply=True)
            self.assertEqual(result["planned_records"], 0)
            self.assertEqual(result["written_records"], 0)


if __name__ == "__main__":
    unittest.main()
