"""Regression cases for admin edits spanning identities and storage writes."""

import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import catalog_admin, indexes, version_admin
from backend.api_contract import ApiContract, ApiFault
from backend.app import create_app
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, record_identity, validate_v2_record
from backend.test_admin_version_admin import TOKEN, make_record, manual_payload
from backend.version_store import write_v2_record


class AdminStorageConsistencyTests(unittest.TestCase):
    def test_http_reordered_pc_artifacts_preserve_identity_owned_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = make_record(platform="windows", reference=False)
            first = record["artifacts"][0]
            first["checksum"] = {"md5": "a" * 32, "crc64": "123"}
            first["urls"][0]["current"] = {"state": "available", "http_code": 200}
            second = copy.deepcopy(first)
            second["name"] = "other.zip"
            second["checksum"] = {"sha256": "b" * 64}
            second["urls"][0]["url"] = "https://example.test/other.zip"
            second["urls"][0]["provider"] = "other-provider"
            second["urls"][0]["current"] = {"state": "unavailable", "http_code": 404}
            record["artifacts"].append(second)
            for item in record["artifacts"]:
                item["artifact_id"] = artifact_id(item, record_identity=record_identity(record))
            path = write_v2_record(record, root)
            rebuild_index(root, "mihoyo", "hk4e", "windows")
            endpoint = "/api/v1/admin/domains/hk4e-pc/versions/1.0.0/editable"
            headers = {"Authorization": f"Bearer {TOKEN}"}
            with TestClient(create_app(root, state_root=root / "state", admin_token=TOKEN)) as client:
                response = client.get(endpoint, headers=headers)
                self.assertEqual(response.status_code, 200)
                artifacts = response.json()["artifacts"]
                for item in artifacts:
                    for candidate in item["urls"]:
                        candidate.pop("id")
                response = client.patch(endpoint, headers=headers, json={"artifacts": list(reversed(artifacts))})
                self.assertEqual(response.status_code, 200, response.text)
            saved = json.loads(path.read_text(encoding="utf-8"))
            validate_v2_record(saved)
            self.assertEqual(saved["artifacts"], list(reversed(record["artifacts"])))

    def test_artifact_identity_is_returned_and_rejects_foreign_or_reused_ids(self):
        record = make_record(platform="windows", reference=False)
        projected = version_admin.editable_projection(record)["artifacts"]
        self.assertEqual(projected[0]["artifact_id"], record["artifacts"][0]["artifact_id"])
        for payload in (
            [{**projected[0], "artifact_id": "a1_foreign"}],
            [projected[0], {**projected[0], "name": "second.zip"}],
        ):
            with self.subTest(payload=payload), self.assertRaises(ApiFault) as failure:
                version_admin._normalize_edited_artifacts(payload, record, record_identity(record))
            self.assertEqual(failure.exception.status, 422)

    def test_reordering_pc_artifacts_keeps_each_checksum_and_observation(self):
        for explicit_identity in (False, True):
            with self.subTest(explicit_identity=explicit_identity), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = make_record(platform="windows", reference=False)
                first = record["artifacts"][0]
                first["checksum"] = {"md5": "a" * 32, "crc64": "123"}
                first["urls"][0]["current"] = {"state": "available", "http_code": 200}
                second = copy.deepcopy(first)
                second["name"] = "other.zip"
                second["checksum"] = {"sha256": "b" * 64}
                second["urls"][0]["url"] = "https://example.test/other.zip"
                record["artifacts"].append(second)
                for item in record["artifacts"]:
                    item["artifact_id"] = artifact_id(item, record_identity=record_identity(record))
                write_v2_record(record, root)
                rebuild_index(root, "mihoyo", "hk4e", "windows")
                payload = version_admin.editable_projection(record)["artifacts"]
                if not explicit_identity:
                    for item in payload:
                        item.pop("artifact_id", None)
                updated, _ = version_admin.update_version(
                    root, "hk4e-pc", "1.0.0", {"artifacts": list(reversed(payload))},
                )
                self.assertEqual(updated["artifacts"], list(reversed(record["artifacts"])))

    def test_concurrent_catalog_creates_keep_both_successful_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_read = threading.Event()
            second_read = threading.Event()
            load_config = version_admin._catalog_config

            def overlapping_read(path):
                config = load_config(path)
                if not first_read.is_set():
                    first_read.set()
                    second_read.wait(timeout=0.3)
                else:
                    second_read.set()
                return config

            with patch.object(version_admin, "_catalog_config", overlapping_read):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(version_admin.create_game, root, {"id": "debt-a", "platform": "windows"})
                    self.assertTrue(first_read.wait(timeout=2))
                    second = executor.submit(version_admin.create_game, root, {"id": "debt-b", "platform": "windows"})
                    self.assertEqual({first.result()["id"], second.result()["id"]}, {"debt-a", "debt-b"})
            self.assertEqual(set(catalog_admin.load_config(root)["games"]), {"debt-a", "debt-b"})

    def test_index_write_failure_restores_record_and_public_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = make_record()
            path = write_v2_record(record, root)
            rebuild_index(root, "mihoyo", "hk4e", "android")
            before = path.read_bytes()
            with patch.object(indexes, "rebuild_index", side_effect=OSError("index commit failed")):
                with self.assertRaises(OSError):
                    version_admin.set_visibility(root, "hk4e-android", "1.0.0", False)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("hk4e-android", ApiContract(root, state_root=root / "state").inventory())
            version_admin.set_visibility(root, "hk4e-android", "1.0.0", False)
            self.assertNotIn("hk4e-android", ApiContract(root, state_root=root / "state").inventory())

    def test_failed_create_edit_and_delete_restore_both_original_files(self):
        for action in ("create", "edit", "delete"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = write_v2_record(make_record(), root)
                index = rebuild_index(root, "mihoyo", "hk4e", "android")
                original_record, original_index = path.read_bytes(), index.read_bytes()
                rebuild = indexes.rebuild_index

                def fail_after_index_write(*args):
                    rebuild(*args)
                    raise OSError("failed after replacing the index")

                with patch.object(indexes, "rebuild_index", side_effect=fail_after_index_write):
                    with self.assertRaises(OSError):
                        if action == "create":
                            version_admin.create_version(root, "hk4e-android", manual_payload())
                        elif action == "edit":
                            version_admin.update_version(root, "hk4e-android", "1.0.0", {"file_path": "changed.apk"})
                        else:
                            version_admin.delete_version(root, "hk4e-android", "1.0.0")
                self.assertEqual(path.read_bytes(), original_record)
                self.assertEqual(index.read_bytes(), original_index)
                self.assertFalse((path.parent / "2.0.0.json").exists())
                self.assertIn("hk4e-android", ApiContract(root, state_root=root / "state").inventory())

    def test_noop_edits_repair_missing_index_without_rewriting_record(self):
        for action in ("edit", "visibility"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = write_v2_record(make_record(), root)
                index = rebuild_index(root, "mihoyo", "hk4e", "android")
                before = path.read_bytes()
                index.unlink()
                with patch.object(version_admin, "write_v2_record", wraps=write_v2_record) as write:
                    if action == "edit":
                        _, changed = version_admin.update_version(root, "hk4e-android", "1.0.0", {})
                        self.assertFalse(changed)
                    else:
                        self.assertTrue(version_admin.set_visibility(root, "hk4e-android", "1.0.0", True))
                    write.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                self.assertTrue(index.exists())
                self.assertIn("hk4e-android", ApiContract(root, state_root=root / "state").inventory())
