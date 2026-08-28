import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import artifact_id, record_identity, validate_v2_record
from backend import version_store
from backend.version_store import VersionStoreError, persist_v2_record, write_v2_record


def record(platform: str = "android") -> dict:
    value = {
        "schema_version": 2,
        "vendor": "mihoyo",
        "game_id": "hk4e",
        "domain_id": f"hk4e-{'android' if platform == 'android' else 'pc'}",
        "platform": platform,
        "channel": "official",
        "version": "7.0.0",
        "version_code": None,
        "file_time": None,
        "artifacts": [{
            "kind": "apk" if platform == "android" else "package",
            "component": "game",
            "package_type": "full",
            "delivery_mode": "direct",
            "name": "game.apk" if platform == "android" else "game.zip",
            "size": 10,
            "urls": [{
                "url": "https://example.test/game.apk" if platform == "android" else "https://example.test/game.zip",
                "provider": "mihoyo",
                "source_kind": "official",
                "priority": 0,
            }],
        }],
        "references": [],
    }
    identity = {key: value[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    value["artifacts"][0]["artifact_id"] = artifact_id(value["artifacts"][0], record_identity=identity)
    validate_v2_record(value)
    return value


def refresh_artifact_id(value: dict) -> dict:
    identity = {key: value[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    value["artifacts"][0]["artifact_id"] = artifact_id(value["artifacts"][0], record_identity=identity)
    return value


class VersionStoreTests(unittest.TestCase):
    def test_record_identity_normalizes_nfc_and_persist_refreshes_equivalent_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = record()
            old["domain_id"] = "hk4e-\u00e1ndroid"
            refresh_artifact_id(old)
            persist_v2_record(old, root)

            refreshed = record()
            refreshed["domain_id"] = "hk4e-a\u0301ndroid"
            refreshed["file_time"] = "2026-08-27T00:00:00Z"
            refresh_artifact_id(refreshed)
            self.assertEqual(record_identity(old), record_identity(refreshed))
            self.assertEqual(old["artifacts"][0]["artifact_id"], refreshed["artifacts"][0]["artifact_id"])

            path = persist_v2_record(refreshed, root)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["domain_id"], refreshed["domain_id"])
            self.assertEqual(stored["file_time"], refreshed["file_time"])

    def test_record_identity_rejects_missing_or_empty_fields(self) -> None:
        for invalid in ({}, record() | {"domain_id": ""}):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    record_identity(invalid)

    def test_persist_reads_and_writes_within_one_data_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = record()
            old["is_visible"] = False
            write_v2_record(old, root)
            events: list[str] = []
            locked = False

            @contextmanager
            def tracked_lock(_root: Path):
                nonlocal locked
                events.append("enter")
                locked = True
                try:
                    yield
                finally:
                    locked = False
                    events.append("exit")

            original_read = version_store._read_existing_record
            original_write = version_store._write_v2_record_locked

            def checked_read(path: Path):
                self.assertTrue(locked)
                events.append("read")
                return original_read(path)

            def checked_write(*args, **kwargs):
                self.assertTrue(locked)
                events.append("write")
                return original_write(*args, **kwargs)

            with patch.object(version_store, "data_file_lock", tracked_lock), patch.object(
                version_store, "_read_existing_record", checked_read,
            ), patch.object(version_store, "_write_v2_record_locked", checked_write):
                persist_v2_record(record(), root)
            self.assertEqual(events, ["enter", "read", "write", "exit"])

    def test_persist_writes_a_new_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = persist_v2_record(record(), root)
            self.assertEqual(path, root / "mihoyo/hk4e/android/7.0.0.json")
            validate_v2_record(json.loads(path.read_text(encoding="utf-8")))

    def test_persist_refreshes_valid_v2_and_preserves_explicit_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = record()
            old["is_visible"] = False
            persist_v2_record(old, root)
            refreshed = record()
            refreshed["file_time"] = "2026-08-27T00:00:00Z"
            path = persist_v2_record(refreshed, root)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(stored["is_visible"])
            self.assertEqual(stored["file_time"], refreshed["file_time"])
            validate_v2_record(stored)

    def test_persist_preserves_matching_legacy_record_verbatim(self) -> None:
        legacy = {
            "vendor": "mihoyo",
            "game_id": "hk4e",
            "platform": "android",
            "version": "7.0.0",
            "url": "https://example.test/legacy.apk",
            "custom": {"retained": True},
        }
        raw = json.dumps(legacy, ensure_ascii=False, indent=2) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "mihoyo/hk4e/android/7.0.0.json"
            path.parent.mkdir(parents=True)
            path.write_text(raw, encoding="utf-8")
            self.assertEqual(persist_v2_record(record(), root), path)
            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_persist_rejects_corrupt_non_object_and_non_regular_existing_targets(self) -> None:
        cases = ("{not-json", "[]")
        for raw in cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "mihoyo/hk4e/android/7.0.0.json"
                path.parent.mkdir(parents=True)
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(VersionStoreError):
                    persist_v2_record(record(), root)
                self.assertEqual(path.read_text(encoding="utf-8"), raw)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "mihoyo/hk4e/android/7.0.0.json"
            path.mkdir(parents=True)
            with self.assertRaises(VersionStoreError):
                persist_v2_record(record(), root)

    def test_persist_rejects_unknown_schema_and_identity_conflicts(self) -> None:
        cases = (
            {"schema_version": 1},
            {"schema_version": "2"},
            {"schema_version": 2, "game_id": "other"},
        )
        for existing in cases:
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "mihoyo/hk4e/android/7.0.0.json"
                path.parent.mkdir(parents=True)
                raw = json.dumps(existing) + "\n"
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(VersionStoreError):
                    persist_v2_record(record(), root)
                self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_persist_rejects_missing_or_conflicting_legacy_identity(self) -> None:
        for field, value in (("version", None), ("game_id", "other")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                legacy = {
                    "vendor": "mihoyo",
                    "game_id": "hk4e",
                    "platform": "android",
                    "version": "7.0.0",
                }
                legacy.pop(field) if value is None else legacy.update({field: value})
                path = root / "mihoyo/hk4e/android/7.0.0.json"
                path.parent.mkdir(parents=True)
                raw = json.dumps(legacy) + "\n"
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(VersionStoreError):
                    persist_v2_record(record(), root)
                self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_write_enters_the_cross_process_data_file_lock(self) -> None:
        entered: list[Path] = []

        @contextmanager
        def tracked_lock(root: Path):
            entered.append(root)
            yield

        with tempfile.TemporaryDirectory() as directory, patch(
            "backend.version_store.data_file_lock", tracked_lock,
        ):
            root = Path(directory) / "first-write-root"
            path = write_v2_record(record(), root)
            self.assertEqual(path, root / "mihoyo/hk4e/android/7.0.0.json")
            self.assertEqual(entered, [root])
            validate_v2_record(json.loads(path.read_text(encoding="utf-8")))

    def test_android_and_windows_disk_paths_preserve_windows_platform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            android = write_v2_record(record(), root)
            windows = record("windows")
            windows["version"] = "7.0.1"
            identity = {key: windows[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
            windows["artifacts"][0]["artifact_id"] = artifact_id(windows["artifacts"][0], record_identity=identity)
            pc = write_v2_record(windows, root)
            self.assertEqual(android, root / "mihoyo/hk4e/android/7.0.0.json")
            self.assertEqual(pc, root / "mihoyo/hk4e/pc/7.0.1.json")
            self.assertEqual(json.loads(pc.read_text(encoding="utf-8"))["platform"], "windows")
            self.assertFalse((root / "mihoyo/hk4e/android/index.json").exists())

    def test_default_no_overwrite_and_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_v2_record(record(), root)
            changed = copy.deepcopy(record())
            changed["file_time"] = "2026-08-27T00:00:00Z"
            with self.assertRaises(FileExistsError):
                write_v2_record(changed, root)
            write_v2_record(changed, root, overwrite=True)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["file_time"], "2026-08-27T00:00:00Z")

    def test_invalid_record_and_path_components_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = record()
            invalid["artifacts"][0]["size"] = -1
            with self.assertRaises(ValueError):
                write_v2_record(invalid, root)
            for field, value in (("vendor", "../outside"), ("game_id", "a\\b"), ("version", "C:\\bad")):
                invalid = record()
                invalid[field] = value
                refresh_artifact_id(invalid)
                with self.assertRaises((VersionStoreError, ValueError)):
                    write_v2_record(invalid, root)

    def test_written_content_can_be_checked_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_v2_record(record(), Path(directory))
            validate_v2_record(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
