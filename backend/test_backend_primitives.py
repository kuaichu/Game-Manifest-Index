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
from backend.probe_policy import (
    PROBE_EVIDENCE_TTL,
    parse_probe_checked_at,
    stable_id,
    stable_url_id,
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

        for entry in ("import backend.admin_probe", "import backend.api_contract", "import backend.admin_operations"):
            completed = subprocess.run(
                [sys.executable, "-c", entry],
                cwd=backend_dir.parent,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
