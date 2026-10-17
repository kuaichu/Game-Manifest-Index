"""Probe results commit only to the selected, still-matching resource."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api_contract import ApiContract
from backend.admin_probe import probe_public_url, probe_records, selected_records, stable_url_id
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, record_identity
from probe_adapters.service import apply_result
from backend.test_admin_sync_operations import artifact, fake_probe, record
from backend.version_store import write_v2_record


class ProbeCommitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def store(self, value):
        path = write_v2_record(value, self.root, overwrite=True)
        rebuild_index(self.root, value["vendor"], value["game_id"], value["platform"])
        return path

    def test_changed_target_cannot_receive_an_old_probe_result(self):
        for change in ("identity", "size", "source_kind", "provider", "priority", "channel"):
            with self.subTest(change=change):
                value = record("windows", artifacts=[artifact("original.zip", ["https://autopatchcn.yuanshen.com/original.zip"], kind="package")])
                path = self.store(value)
                original = value["artifacts"][0]
                target = original["urls"][0]["url"]

                def edited_during_probe(url, **kwargs):
                    changed = copy.deepcopy(value)
                    item = changed["artifacts"][0]
                    if change == "identity":
                        item["name"] = "replacement.zip"
                    elif change == "size":
                        item["size"] = 999
                    elif change == "channel":
                        changed["channel"] = "beta"
                    else:
                        item["urls"][0][change] = {"source_kind": "mirror", "provider": "replacement", "priority": 9}[change]
                    item["artifact_id"] = artifact_id(item, record_identity=record_identity(changed))
                    self.store(changed)
                    return fake_probe(url, **kwargs)

                result = probe_public_url(
                    self.root, target, stable_url_id(original["artifact_id"], 0, target),
                    1, probe_fn=edited_during_probe,
                )
                self.assertFalse(result["persisted"])
                self.assertNotIn("current", json.loads(path.read_bytes())["artifacts"][0]["urls"][0])

    def test_reordered_same_target_is_resolved_by_identity(self):
        value = record("windows", artifacts=[
            artifact("first.zip", ["https://autopatchcn.yuanshen.com/first.zip"], kind="package"),
            artifact("second.zip", ["https://autopatchcn.yuanshen.com/second.zip"], kind="package"),
        ])
        path = self.store(value)
        first = value["artifacts"][0]
        target = first["urls"][0]["url"]

        def reordered_during_probe(url, **kwargs):
            changed = copy.deepcopy(value)
            changed["artifacts"].reverse()
            self.store(changed)
            return fake_probe(url, **kwargs)

        result = probe_public_url(self.root, target, stable_url_id(first["artifact_id"], 0, target), 1, probe_fn=reordered_during_probe)
        self.assertTrue(result["persisted"])
        saved = json.loads(path.read_bytes())
        self.assertNotIn("current", saved["artifacts"][0]["urls"][0])
        self.assertEqual(saved["artifacts"][1]["urls"][0]["current"]["state"], "available")

    def test_each_batch_result_is_publicly_readable_before_next_network_call(self):
        for version in ("1.0.0", "2.0.0"):
            self.store(record("android", version=version))
        calls = []

        def unavailable(url, **kwargs):
            calls.append(url)
            ApiContract(self.root, state_root=self.root / "state").inventory()
            return {**fake_probe(url, **kwargs), "http_code": 404, "available": False}

        result = probe_records(self.root, selected_records(self.root, ["hk4e"], "android"), 1, 1, probe_fn=unavailable)
        self.assertEqual((result["checked"], result["failed"], result["unavailable"]), (2, 0, 2))
        self.assertEqual(len(calls), 2)

    def test_index_failure_reports_unpersisted_and_restores_original_record(self):
        value = record("android")
        path = self.store(value)
        index = path.parent / "index.json"
        before = path.read_bytes(), index.read_bytes()
        target = value["artifacts"][0]["urls"][0]["url"]
        with patch("backend.indexes._write_atomic", side_effect=OSError("injected disk failure")):
            result = probe_public_url(self.root, target, stable_url_id(value["artifacts"][0]["artifact_id"], 0, target), 1, probe_fn=fake_probe)
        self.assertFalse(result["persisted"])
        self.assertEqual((path.read_bytes(), index.read_bytes()), before)
        self.assertIn("hk4e-android", ApiContract(self.root, state_root=self.root / "state").inventory())

    def test_in_place_apply_cannot_change_other_owned_fields(self):
        value = record("android")
        path = self.store(value)
        before = path.read_bytes()
        target = value["artifacts"][0]["urls"][0]["url"]

        def changes_extra_fields(current, result):
            updated = apply_result(current, result)
            current.update(updated)
            current["provenance"]["source_name"] = "unrelated rewrite"
            return current

        result = probe_public_url(
            self.root, target, stable_url_id(value["artifacts"][0]["artifact_id"], 0, target),
            1, probe_fn=fake_probe, apply_fn=changes_extra_fields,
        )
        self.assertFalse(result["persisted"])
        self.assertEqual(path.read_bytes(), before)
