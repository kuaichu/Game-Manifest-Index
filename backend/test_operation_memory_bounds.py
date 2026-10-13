import json
import tempfile
import unittest
from concurrent.futures import Future, wait as real_wait
from pathlib import Path
from unittest.mock import patch

from backend.admin_operations import MAX_JOB_LOGS, OperationManager
from backend.admin_probe import probe_records
from backend.admin_state import AdminStateStore, BoundedItems, MAX_STATE_BYTES


class OperationMemoryBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = AdminStateStore(self.root / "state")
        self.manager = OperationManager(self.store, self.root / "data")
        self.manager._job = {
            "job_id": "bounded", "status": "running", "phase": "probe",
            "actions": ["probe"], "game_ids": ["hk4e"], "scope": "android",
            "completed": 0, "total": 5000, "phase_completed": 0, "phase_total": 5000,
            "succeeded": 0, "failed": 0, "current": None,
            "started_at": "2026-10-13T00:00:00Z", "finished_at": None,
            "result": None, "error": None, "logs": [],
        }

    def test_log_cursor_survives_eviction_and_restart(self):
        for number in range(1000):
            self.manager._log(str(number))
        self.manager._save()
        restored = OperationManager(self.store, self.root / "data")
        view = restored.latest()
        self.assertEqual(view["status"], "failed")
        self.assertEqual(view["log_total"], 1001)
        self.assertEqual(view["log_offset"], 1001 - MAX_JOB_LOGS)
        self.assertEqual(len(view["logs"]), MAX_JOB_LOGS)
        expired = restored.status("bounded", 0)
        self.assertEqual(expired["logs"], view["logs"])
        self.assertEqual(expired["log_offset"], view["log_offset"])
        self.assertEqual(restored.status("bounded", 1001)["logs"], [])
        for cursor in (-1, 1002):
            with self.assertRaises(ValueError):
                restored.status("bounded", cursor)

    def test_legacy_snapshot_logs_are_bounded_when_restored(self):
        self.manager._job["logs"] = [str(number) for number in range(1000)]
        self.store.write("latest_operation", self.manager._job)
        restored = OperationManager(self.store, self.root / "data")
        self.assertEqual(restored.latest()["log_total"], 1001)
        self.assertEqual(len(self.store.read("latest_operation")["logs"]), MAX_JOB_LOGS)

    def test_progress_writes_are_coalesced_and_final_snapshot_fits(self):
        item = {"game_id": "hk4e", "version": "1.0", "platform": "android", "ok": True}
        with patch("backend.admin_operations.monotonic", return_value=1), patch.object(self.store, "write", wraps=self.store.write) as write:
            for number in range(5000):
                self.manager._progress("bounded", "probe", 0, 0, item, number + 1, 5000)
            self.assertEqual(write.call_count, 1)
            self.assertEqual(self.manager.latest()["completed"], 5000)
            result = {"probe": {"checked": 5000, "failed": 0, "available": 5000,
                                "items": [{**item, "reason": "x" * 500} for _ in range(5000)]}}
            with patch("backend.admin_operations.notify_operation"):
                self.manager._finish("bounded", "finished", result)
            self.assertEqual(write.call_count, 2)
        saved = self.store.read("latest_operation")
        self.assertEqual((saved["status"], saved["completed"], saved["succeeded"]), ("finished", 5000, 5000))
        probe = saved["result"]["probe"]
        self.assertTrue(probe["items_truncated"])
        self.assertEqual(probe["items_total"], 5000)
        self.assertEqual(len(probe["items"]) + probe["items_omitted"], 5000)
        self.assertLess(len(json.dumps(saved, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), MAX_STATE_BYTES)
        self.assertEqual(OperationManager(self.store, self.root / "data").latest()["status"], "finished")

    def test_discovery_counters_and_notification_survive_detail_truncation(self):
        items = [{"ok": True, "new": True, "version": str(number), "note": "x" * 1000} for number in range(2000)]
        result = {"discover": {"succeeded": 2000, "failed": 0, "new_versions": 2000, "items": items}}
        notification = {"items": [{"ok": True, "new": True, "version": "last-new-version"}], "failed": 0}
        with patch("backend.admin_operations.notify_operation") as notify:
            self.manager._finish("bounded", "finished", result, notification_discover=notification)
        saved = self.store.read("latest_operation")
        self.assertEqual(saved["completed"], 2000)
        self.assertEqual(saved["result"]["discover"]["new_versions"], 2000)
        self.assertTrue(saved["result"]["discover"]["items_truncated"])
        self.assertEqual(notify.call_args.args[0]["discover"], notification)

    def test_normal_details_are_kept_in_full(self):
        item = {"ok": True, "reason": "normal"}
        details = BoundedItems(1000)
        details.append(item)
        self.assertEqual(details.result(), {"items": [item]})

    def test_discovery_errors_do_not_leak_adapter_urls_or_secrets(self):
        self.manager._progress("bounded", "discover", 0, 0, {
            "ok": False, "game_id": "hk4e", "platform": "android",
            "error": "failed https://private.test/download?token=secret-value",
        }, 1, 1)
        logs = "\n".join(self.manager.latest()["logs"])
        self.assertIn("discovery_failed", logs)
        self.assertNotIn("private.test", logs)
        self.assertNotIn("secret-value", logs)


class ProbeWindowTests(unittest.TestCase):
    def test_pending_futures_and_details_are_bounded_without_losing_counts(self):
        submissions = []
        window_sizes = []

        class ImmediatePool:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def submit(self, operation, *args):
                submissions.append(args)
                future = Future()
                future.set_result(operation(*args))
                return future

        def window_wait(futures, **kwargs):
            window_sizes.append(len(futures))
            return real_wait(futures, **kwargs)

        def probe(*args):
            for _ in range(3):
                yield {"ok": True, "available": True, "reason": "x" * 100}

        records = [(Path(str(number)), {}) for number in range(20)]
        progress = []
        with patch("backend.admin_probe.ThreadPoolExecutor", ImmediatePool), patch("backend.admin_probe.wait", window_wait), patch("backend.admin_probe._filtered_candidates", return_value=[None] * 3), patch("backend.admin_probe._probe_record", probe), patch("backend.admin_probe._domain", return_value=("v", "g", "android", "g")), patch("backend.admin_probe.rebuild_index") as rebuild, patch("backend.admin_probe.BoundedItems", side_effect=lambda: BoundedItems(512)):
            result = probe_records(Path("unused"), records, 5, 2, progress=lambda item, done, total: progress.append((done, total)))
        self.assertEqual(len(submissions), 20)
        self.assertEqual(max(window_sizes), 2)
        self.assertEqual((result["checked"], result["available"], result["failed"]), (60, 60, 0))
        self.assertEqual(progress[-1], (60, 60))
        self.assertTrue(result["items_truncated"])
        self.assertEqual(result["items_total"], 60)
        rebuild.assert_called_once()

    def test_cancel_does_not_submit_remaining_records(self):
        cancelled = False
        calls = []

        def probe(*args):
            calls.append(args[1])
            yield {"ok": True, "available": True}

        def progress(*args):
            nonlocal cancelled
            cancelled = True

        with patch("backend.admin_probe._filtered_candidates", return_value=[None]), patch("backend.admin_probe._probe_record", probe), patch("backend.admin_probe._domain", return_value=("v", "g", "android", "g")), patch("backend.admin_probe.rebuild_index"):
            result = probe_records(Path("unused"), [(Path(str(n)), {}) for n in range(100)], 5, 1, cancelled=lambda: cancelled, progress=progress)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["checked"], 1)
        self.assertTrue(result["cancelled"])

    def test_record_error_after_one_result_only_fails_remaining_candidates(self):
        def probe(*args):
            yield {"ok": True, "available": True}
            raise OSError("private failure details")

        record = {"game_id": "hk4e", "version": "1.0", "platform": "android"}
        candidates = [(n, 0, {"kind": "apk"}, {"url": "https://example.test/app.apk"}) for n in range(3)]
        with patch("backend.admin_probe._filtered_candidates", return_value=candidates), patch("backend.admin_probe._probe_record", probe), patch("backend.admin_probe._domain", return_value=("v", "g", "android", "g")), patch("backend.admin_probe.rebuild_index"):
            result = probe_records(Path("unused"), [(Path("1"), record)], 5, 1)
        self.assertEqual((result["checked"], result["available"], result["failed"]), (3, 1, 2))
        self.assertEqual([item.get("artifact_index") for item in result["items"]], [None, 1, 2])
        self.assertNotIn("private failure details", str(result))

    def test_progress_callback_error_propagates_without_recounting(self):
        def probe(*args):
            yield {"ok": True, "available": True}

        with patch("backend.admin_probe._filtered_candidates", return_value=[None]), patch("backend.admin_probe._probe_record", probe), patch("backend.admin_probe._domain", return_value=("v", "g", "android", "g")):
            with self.assertRaisesRegex(RuntimeError, "callback failed"):
                probe_records(Path("unused"), [(Path("1"), {})], 5, 1,
                              progress=lambda *args: (_ for _ in ()).throw(RuntimeError("callback failed")))


if __name__ == "__main__":
    unittest.main()
