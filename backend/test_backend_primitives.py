"""Unit tests for shared backend filesystem, probe-policy, and module boundary invariants."""

from __future__ import annotations

import ast
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend import (
    admin_catalog_service,
    api_contract,
    catalog_admin,
    catalog_registry,
    inventory_loader,
    legacy_record_normalizer,
    manifest_projection,
    manifest_readers,
    mihoyo_package_files,
    public_projection,
    schema_v2,
    version_admin,
    version_store,
)
from backend.fs_safety import (
    FILE_ATTRIBUTE_REPARSE_POINT,
    UnsafePathError,
    atomic_write_bytes,
    atomic_write_text,
    disk_platform,
    domain_directory,
    ensure_directory,
    is_ordinary,
    is_safe_component,
    require_safe_component,
)
from backend.indexes import rebuild_index
from backend.probe_policy import (
    PROBE_EVIDENCE_TTL,
    parse_probe_checked_at,
    stable_id,
    stable_url_id,
)
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import (
    persist_v2_record_locked,
    read_existing_record,
    record_index_transaction,
    write_v2_record,
)


class FsSafetyTests(unittest.TestCase):
    def test_is_ordinary_single_lstat_and_reparse_point_detection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "sample.json"
            regular.write_text("{}", encoding="utf-8")
            subdir = root / "sub"
            subdir.mkdir()

            self.assertTrue(is_ordinary(regular))
            self.assertFalse(is_ordinary(regular, directory=True))
            self.assertTrue(is_ordinary(subdir, directory=True))
            self.assertFalse(is_ordinary(subdir))
            self.assertFalse(is_ordinary(root / "missing.json"))

            calls: list[Path] = []
            real_lstat = os.lstat

            def counted_lstat(target):
                calls.append(Path(target))
                return real_lstat(target)

            with patch("backend.fs_safety.os.lstat", side_effect=counted_lstat):
                self.assertTrue(is_ordinary(regular))
            self.assertEqual(len(calls), 1)

            reparse_file = SimpleNamespace(
                st_mode=stat.S_IFREG | 0o644,
                st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT,
            )
            reparse_dir = SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755,
                st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT,
            )
            with patch("backend.fs_safety.os.lstat", return_value=reparse_file):
                self.assertFalse(is_ordinary(regular))
            with patch("backend.fs_safety.os.lstat", return_value=reparse_dir):
                self.assertFalse(is_ordinary(subdir, directory=True))
                with self.assertRaises(UnsafePathError):
                    ensure_directory(subdir)

    def test_atomic_writers_replace_and_clean_up_temp_files_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "record.json"
            atomic_write_text(target, '{"ok": true}\n')
            self.assertEqual(target.read_bytes(), b'{"ok": true}\n')

            with patch("backend.fs_safety.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    atomic_write_bytes(target, b"broken")
            self.assertEqual(target.read_bytes(), b'{"ok": true}\n')
            self.assertEqual([item.name for item in root.iterdir()], ["record.json"])

    def test_safe_component_and_domain_directory_contracts(self) -> None:
        for valid in ("1.0.0", "hk4e-pc", "v2_rc-1", "a"):
            self.assertTrue(is_safe_component(valid))
            self.assertEqual(require_safe_component(valid, "field"), valid)
        for invalid in ("", ".", "..", ".hidden", "-flag", "1.0@beta", "a/b", "a\\b", "a b", None):
            self.assertFalse(is_safe_component(invalid))
            with self.assertRaises(KeyError):
                require_safe_component(invalid, "field", KeyError)

        root = Path("data")
        self.assertEqual(disk_platform("android"), "android")
        self.assertEqual(disk_platform("windows"), "pc")
        self.assertEqual(disk_platform("pc", allow_pc=True), "pc")
        with self.assertRaises(ValueError):
            disk_platform("pc")

        self.assertEqual(
            domain_directory(root, "mihoyo", "hk4e", "android"),
            root / "mihoyo" / "hk4e" / "android",
        )
        self.assertEqual(
            domain_directory(root, "mihoyo", "hk4e", "windows", "hk4e-pc"),
            root / "mihoyo" / "hk4e" / "pc",
        )
        self.assertEqual(
            domain_directory(root, "hypergryph", "endfield", "windows", "endfield-resources"),
            root / "hypergryph" / "endfield" / "pc" / "domains" / "endfield-resources",
        )
        with self.assertRaises(ValueError):
            domain_directory(root, "mihoyo", "hk4e", "android", "hk4e-extra")


class ProbePolicyAndDecouplingTests(unittest.TestCase):
    def test_probe_policy_parsing_ttl_and_stable_ids(self) -> None:
        self.assertEqual(PROBE_EVIDENCE_TTL, timedelta(hours=20))
        parsed = parse_probe_checked_at({"checked_at": "2026-08-29T01:02:03Z"})
        self.assertEqual(
            parsed,
            ("2026-08-29T01:02:03Z", datetime(2026, 8, 29, 1, 2, 3, tzinfo=timezone.utc)),
        )
        fractional = parse_probe_checked_at({"checked_at": "2026-08-29T01:02:03.500Z"})
        self.assertIsNotNone(fractional)
        for bad in ({}, {"checked_at": None}, {"checked_at": "2026-08-29"}, {"checked_at": "2026-08-29T01:02:03+00:00"}):
            self.assertIsNone(parse_probe_checked_at(bad))

        expected = stable_id("art-1", 0, "https://example.test/a.zip")
        self.assertEqual(stable_url_id("art-1", 0, "https://example.test/a.zip"), expected)
        self.assertTrue(0 <= expected < (1 << 48))

    def test_backend_non_test_modules_have_zero_private_cross_imports_and_no_probe_cycle(self) -> None:
        backend_dir = Path(__file__).resolve().parent
        violations: list[tuple[str, str, str]] = []
        for path in sorted(backend_dir.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend"):
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            violations.append((path.name, node.module, alias.name))
        self.assertEqual(violations, [])

        with tempfile.TemporaryDirectory() as state_dir:
            env = {**os.environ, "GMI_STATE_ROOT": state_dir}
            for entry in (
                "import backend.catalog_registry",
                "import backend.schema_v2",
                "import backend.legacy_record_normalizer",
                "import backend.inventory_loader",
                "import backend.public_projection",
                "import backend.manifest_projection",
                "import backend.admin_probe",
                "import backend.version_admin",
                "import backend.admin_catalog_service",
                "import backend.admin_routes",
                "import backend.api_contract",
                "import backend.admin_operations",
                "import backend.telegram_notify",
                "import backend.public_projection, backend.manifest_projection, backend.api_contract, backend.app",
            ):
                completed = subprocess.run(
                    [sys.executable, "-c", entry],
                    cwd=backend_dir.parent,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_split_modules_reexports_and_public_version_store_hooks(self) -> None:
        self.assertIs(schema_v2.normalize_legacy_record, legacy_record_normalizer.normalize_legacy_record)
        self.assertIs(schema_v2.LegacyNormalizationError, legacy_record_normalizer.LegacyNormalizationError)
        self.assertIs(schema_v2.Diagnostic, legacy_record_normalizer.Diagnostic)

        normalized = legacy_record_normalizer.normalize_legacy_record(
            {
                "vendor": "mihoyo",
                "game_id": "hk4e",
                "platform": "android",
                "channel": "official",
                "version": "1.0.0",
                "filename": "hk4e_1.0.0.apk",
                "url": "https://example.test/hk4e_1.0.0.apk",
            }
        )
        validate_v2_record(normalized)

        for name in (
            "KURO_PACK_MANIFEST",
            "kuro_pack_name",
            "kuro_pack_index_url",
            "kuro_common_pack",
            "build_kuro_resource_packs",
            "resolve_kuro_resource_packs",
            "file_artifacts",
            "file_metadata",
            "nte_manifest_modified_at",
            "compare_artifact",
            "compare_file",
            "artifact_compare_identity",
            "compare_artifact_rows",
            "public_chunk_document",
            "chunk_summary",
            "validate_chunk_document",
            "resolve_package_document",
            "tree_artifact",
            "record_artifact_tree_entries",
        ):
            self.assertIs(getattr(public_projection, name), getattr(manifest_projection, name), name)

        for name in (
            "catalog_projection",
            "create_game",
            "update_game",
            "delete_game",
            "create_domain",
            "update_domain",
            "delete_domain",
        ):
            self.assertIs(getattr(version_admin, name), getattr(admin_catalog_service, name), name)

        self.assertIs(version_store.read_existing_record, read_existing_record)
        self.assertIs(version_store._read_existing_record, read_existing_record)
        self.assertIs(version_store.persist_v2_record_locked, persist_v2_record_locked)
        self.assertIs(version_store._persist_v2_record_locked, persist_v2_record_locked)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            with record_index_transaction(normalized, root) as target:
                written = persist_v2_record_locked(normalized, root, target)
                self.assertEqual(written, target)
                loaded = read_existing_record(target)
            self.assertEqual(loaded["version"], "1.0.0")

    def test_catalog_registry_is_single_source_of_truth(self) -> None:
        self.assertIs(catalog_admin.VENDORS, catalog_registry.VENDORS)
        self.assertIs(manifest_readers.OFFICIAL_SOPHON_HOSTS, catalog_registry.OFFICIAL_SOPHON_HOSTS)
        self.assertIs(mihoyo_package_files.OFFICIAL_PACKAGE_HOSTS, catalog_registry.OFFICIAL_PACKAGE_HOSTS)
        self.assertIs(mihoyo_package_files.PACKAGE_HOSTS_BY_GAME, catalog_registry.PACKAGE_HOSTS_BY_GAME)
        self.assertIs(api_contract.GAME_CATALOG, catalog_registry.GAME_CATALOG)
        self.assertIs(api_contract.VENDORS, catalog_registry.VENDORS)
        self.assertIs(api_contract.ApiFault, inventory_loader.ApiFault)

    def test_catalog_config_loaded_once_per_inventory_and_catalog_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            state = Path(directory) / "state"
            root.mkdir()
            item = {
                "kind": "apk",
                "component": "game",
                "package_type": "full",
                "delivery_mode": "direct",
                "name": "game.apk",
                "size": 10,
                "urls": [{"url": "https://example.test/game.apk", "provider": "fixture", "source_kind": "official", "priority": 0}],
            }
            rec = {
                "schema_version": 2,
                "vendor": "mihoyo",
                "game_id": "hk4e",
                "domain_id": "hk4e-android",
                "platform": "android",
                "channel": "official",
                "version": "1.0.0",
                "version_code": 1,
                "file_time": "2026-01-01T00:00:00Z",
                "artifacts": [item],
                "references": [],
                "is_visible": True,
                "provenance": {"source_kind": "official_sync", "source_name": "fixture"},
            }
            identity = {k: rec[k] for k in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
            item["artifact_id"] = artifact_id(item, record_identity=identity)
            validate_v2_record(rec)
            write_v2_record(rec, root)
            rebuild_index(root, "mihoyo", "hk4e", "android")
            catalog_admin.save_config(
                root,
                {
                    "games": {"demo": {"name": "Demo", "platform": "windows", "vendor": "mihoyo"}},
                    "domains": {"demo-extra": {"game_id": "demo", "kind": "resources", "platform": "windows", "vendor": "mihoyo"}},
                },
            )
            catalog_admin.ensure_domain_directory(
                root,
                catalog_admin.configured_domains(root)["demo-extra"],
            )

            contract = api_contract.ApiContract(root, state_root=state)
            with patch.object(catalog_admin, "load_config", wraps=catalog_admin.load_config) as spy:
                first = contract.inventory()
                self.assertEqual(spy.call_count, 1)
                second = contract.inventory()
                self.assertEqual(spy.call_count, 1)
                self.assertEqual(second, first)

            with patch.object(catalog_admin, "load_config", wraps=catalog_admin.load_config) as spy:
                projection = version_admin.catalog_projection(root)
                self.assertEqual(spy.call_count, 1)
                self.assertIn("demo", {g["id"] for g in projection["games"]})

            with patch.object(version_admin, "catalog_projection", wraps=version_admin.catalog_projection) as proj_spy:
                updated = version_admin.update_game(
                    root,
                    "demo",
                    {"id": "demo", "name": "Demo 2", "sub_name": "", "platform": "windows", "icon_source": "builtin:demo", "is_enabled": True, "sort_order": 5},
                )
                self.assertEqual(updated["name"], "Demo 2")
                self.assertEqual(proj_spy.call_count, 2)


if __name__ == "__main__":
    unittest.main()
