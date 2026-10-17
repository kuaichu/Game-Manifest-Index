"""Shared record/index commits, including exception recovery and nesting."""

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from backend import indexes, version_store
from backend.schema_v2 import artifact_id, record_identity
from backend.storage_locks import DATA_LOCK
from backend.test_version_store import record


class IndexedRecordTransactionTests(unittest.TestCase):
    def test_persist_updates_index_before_returning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = record()
            version_store.persist_v2_record(value, root)
            path = indexes.index_path(root, "mihoyo", "hk4e", "android")
            self.assertTrue(path.exists())
            value["artifacts"][0]["urls"][0]["current"] = {"state": "unavailable", "http_code": 404}
            version_store.persist_v2_record(value, root)
            self.assertIs(indexes.read_index(path)["versions"][0]["available"], False)

    def test_persist_index_failure_removes_new_record_and_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rebuild = indexes.rebuild_index

            def fail_after_replace(*args):
                rebuild(*args)
                raise OSError("failed after index replacement")

            with patch.object(indexes, "rebuild_index", side_effect=fail_after_replace):
                with self.assertRaises(OSError):
                    version_store.persist_v2_record(record(), root)
            self.assertFalse(version_store.v2_record_path(record(), root).exists())
            self.assertFalse(indexes.index_path(root, "mihoyo", "hk4e", "android").exists())

    def test_persist_index_failure_restores_existing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = version_store.write_v2_record(record(), root)
            index = indexes.rebuild_index(root, "mihoyo", "hk4e", "android")
            before = path.read_bytes(), index.read_bytes()
            changed = record()
            changed["is_visible"] = False
            with patch.object(indexes, "rebuild_index", side_effect=OSError("index unavailable")):
                with self.assertRaises(OSError):
                    version_store.persist_v2_record(changed, root)
            self.assertEqual((path.read_bytes(), index.read_bytes()), before)

    def test_failure_after_replacing_existing_index_restores_both_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = version_store.persist_v2_record(record(), root)
            index = indexes.index_path(root, "mihoyo", "hk4e", "android")
            before = path.read_bytes(), index.read_bytes()
            rebuild = indexes.rebuild_index

            def fail_after_replace(*args):
                rebuild(*args)
                raise OSError("failed after index replacement")

            changed = record()
            changed["artifacts"][0]["size"] = 999
            with patch.object(indexes, "rebuild_index", side_effect=fail_after_replace):
                with self.assertRaises(OSError):
                    version_store.persist_v2_record(changed, root)
            self.assertEqual((path.read_bytes(), index.read_bytes()), before)

    def test_unchanged_persist_repairs_stale_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version_store.persist_v2_record(record(), root)
            index = indexes.index_path(root, "mihoyo", "hk4e", "android")
            index.unlink()
            version_store.persist_v2_record(record(), root)
            self.assertTrue(index.exists())

    def test_locked_reader_waits_for_record_and_index_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = version_store.persist_v2_record(record(), root)
            index = indexes.index_path(root, "mihoyo", "hk4e", "android")
            attempted = threading.Event()
            completed = threading.Event()

            def read_both():
                attempted.set()
                with DATA_LOCK:
                    values = json.loads(path.read_bytes()), indexes.read_index(index)
                completed.set()
                return values

            with ThreadPoolExecutor(max_workers=1) as executor:
                with version_store.record_index_transaction(record(), root):
                    changed = record()
                    changed["artifacts"][0]["size"] = 999
                    version_store.write_v2_record(changed, root, overwrite=True)
                    result = executor.submit(read_both)
                    self.assertTrue(attempted.wait(timeout=2))
                    self.assertFalse(completed.is_set())
                stored, summary = result.result(timeout=2)
            self.assertEqual(stored["artifacts"][0]["size"], 999)
            self.assertEqual(summary["versions"][0]["size"], 999)

    def test_different_records_with_same_index_cannot_nest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            second = record()
            second["version"] = "7.0.1"
            second["artifacts"][0]["artifact_id"] = artifact_id(second["artifacts"][0], record_identity=record_identity(second))
            with version_store.record_index_transaction(record(), root):
                with self.assertRaisesRegex(version_store.VersionStoreError, "嵌套事务"):
                    with version_store.record_index_transaction(second, root):
                        pass

    def test_transaction_rolls_back_body_failure_and_commits_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = version_store.write_v2_record(record(), root)
            index = indexes.rebuild_index(root, "mihoyo", "hk4e", "android")
            before = path.read_bytes(), index.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                with version_store.record_index_transaction(record(), root):
                    path.unlink()
                    raise RuntimeError("cancelled")
            self.assertEqual((path.read_bytes(), index.read_bytes()), before)
            with version_store.record_index_transaction(record(), root):
                path.unlink()
            self.assertFalse(index.exists())

    def test_nested_persist_joins_outer_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(indexes, "rebuild_index", wraps=indexes.rebuild_index) as rebuild:
                with version_store.record_index_transaction(record(), root):
                    version_store.persist_v2_record(record(), root)
                    self.assertEqual(rebuild.call_count, 0)
                self.assertEqual(rebuild.call_count, 1)

    def test_legacy_noop_preserves_original_index_and_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = version_store.v2_record_path(record(), root)
            path.parent.mkdir(parents=True)
            legacy = {key: record()[key] for key in ("vendor", "game_id", "platform", "version")}
            path.write_text(json.dumps(legacy), encoding="utf-8")
            index = path.parent / "index.json"
            index.write_bytes(b'{"legacy":true}')
            before = path.read_bytes(), index.read_bytes()
            version_store.persist_v2_record(record(), root)
            self.assertEqual((path.read_bytes(), index.read_bytes()), before)

    def test_reference_only_record_without_index_entry_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = copy.deepcopy(record("windows"))
            value["artifacts"] = []
            value["references"] = [{"kind": "chunk_manifest", "path": "manifests/a.json"}]
            path = version_store.persist_v2_record(value, root)
            self.assertTrue(path.exists())
