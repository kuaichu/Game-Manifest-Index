from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from backend import admin_operations, telegram_notify
from backend.admin_operations import JOB_FIELDS, OperationManager
from backend.admin_state import AdminStateStore
from backend.test_admin_sync_operations import record
from backend.version_store import write_v2_record
from probe_adapters.common import ProbeError


class OperationNotificationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        transport = patch.object(telegram_notify.urllib.request, "urlopen", side_effect=AssertionError("unexpected Telegram HTTP"))
        self.transport = transport.start()
        self.addCleanup(transport.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name) / "data"
        self.data.mkdir()
        self.store = AdminStateStore(Path(temp.name) / "state")

    def manager(self, discovery=None, **kwargs):
        if discovery is not None:
            kwargs["discovery"] = discovery
        manager = OperationManager(self.store, self.data, **kwargs)
        self.addCleanup(manager.shutdown, 2)
        return manager

    def run_job(self, manager, actions=None, scope="android", scheduled_mode=None):
        notified = Event()
        with patch.object(admin_operations, "notify_operation", side_effect=lambda *a, **kw: notified.set()) as notify:
            manager.start(actions or ["discover"], ["hk4e"], scope, 5, 1, scheduled_mode=scheduled_mode)
            self.assertTrue(notified.wait(2), "operation did not finish")
            self.assertTrue(manager.shutdown(2))
        self.assertEqual(notify.call_count, 1)
        return notify.call_args

    def test_previous_version_is_snapshot_and_api_projection_is_unchanged(self):
        write_v2_record(record("android", version="7.0.0"), self.data)
        def discovery(*args, **kwargs):
            write_v2_record(record("android", version="7.1.0"), self.data)
            return {"items": [{"game_id": "hk4e", "platform": "android", "ok": True, "new": True, "version": "7.1.0", "path": "private/path"}]}
        manager = self.manager(discovery)
        call = self.run_job(manager)
        update = call.args[0]["discover"]["items"][0]
        self.assertEqual(update["previous_version"], "7.0.0")
        self.assertNotIn("path", update)
        state = self.store.read("latest_operation")
        self.assertEqual(set(state), JOB_FIELDS)
        self.assertNotIn("previous_version", state["result"]["discover"]["items"][0])
        self.assertIsNone(state["result"]["discover"]["items"][0]["path"])
        self.assertEqual(manager.latest()["result"], state["result"])
        self.assertFalse(call.kwargs["scheduled"])

    def test_older_or_equal_new_record_is_archive_not_downgrade(self):
        write_v2_record(record("android", version="7.0.0"), self.data)
        manager = self.manager(lambda *a, **kw: {"items": [{"game_id": "hk4e", "platform": "android", "ok": True, "new": True, "version": "6.9.0"}]})
        call = self.run_job(manager)
        item = call.args[0]["discover"]["items"][0]
        self.assertTrue(item["archived"])
        self.assertNotIn("previous_version", item)
        self.assertEqual(telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=False), (None, None))

    def test_pc_stages_deduplicate_and_keep_distinct_new_versions(self):
        write_v2_record(record("windows", version="7.0.0"), self.data)
        stages = [
            {"ok": True, "new": True, "version": "7.1.0", "name": "packages"},
            {"ok": True, "new": True, "version": "7.1.0", "name": "chunks"},
            {"ok": True, "new": True, "version": "6.9.0", "name": "historical"},
            {"ok": True, "new": False, "version": "7.0.0"},
        ]
        manager = self.manager(lambda *a, **kw: {"items": [{"game_id": "hk4e", "platform": "windows", "ok": True, "new": True, "version": None, "stages": stages}]})
        call = self.run_job(manager, scope="pc")
        items = call.args[0]["discover"]["items"]
        self.assertEqual([i["version"] for i in items], ["7.1.0", "6.9.0"])
        self.assertEqual(items[0]["previous_version"], "7.0.0")
        self.assertTrue(items[1]["archived"])
        text, _ = telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=True)
        self.assertIn("7.0.0 -> 7.1.0", text)
        self.assertNotIn("6.9.0", text)
        self.assertIsNone(manager.latest()["result"]["discover"]["items"][0]["version"])
        self.assertNotIn("stages", manager.latest()["result"]["discover"]["items"][0])

    def test_pc_partial_failure_keeps_successful_update_and_reports_failure(self):
        manager = self.manager(lambda *a, **kw: {"items": [{"game_id": "hk4e", "platform": "windows", "ok": False, "new": True, "version": "7.1.0", "error": "private secret", "stages": [
            {"ok": True, "new": True, "version": "7.1.0"}, {"ok": False, "new": False, "error": "private secret"},
        ]}]})
        call = self.run_job(manager, scope="pc")
        self.assertEqual(len(call.args[0]["discover"]["items"]), 1)
        self.assertEqual(call.args[0]["discover"]["failed"], 1)
        text, _ = telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=False)
        self.assertIn("官方发现失败", text)
        self.assertNotIn("private secret", text)

    def test_scheduled_mode_does_not_depend_on_log_marker(self):
        manager = self.manager()
        def discovery(*a, **kw):
            with manager._lock:
                manager._job["logs"] = ["marker removed"]
            return {"items": []}
        manager.discovery = discovery
        call = self.run_job(manager, actions=["discover", "probe"], scheduled_mode="normal")
        self.assertTrue(call.kwargs["scheduled"])
        text, delete_after = telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=True)
        self.assertIsNone(text)
        self.assertIsNone(delete_after)

    def test_probe_failure_payload_does_not_contain_exception_text_or_urls(self):
        write_v2_record(record("android"), self.data)
        def fail(*a, **kw):
            raise ProbeError("PRIVATE_TOKEN D:/private/repo https://secret.test/token", status=502)
        manager = self.manager(probe_fn=fail)
        call = self.run_job(manager, actions=["probe"])
        payload = call.args[0]
        self.assertEqual(payload["probe"]["items"][0]["error"], "ProbeError")
        self.assertNotIn("PRIVATE_TOKEN", str(payload))
        self.assertNotIn("https://", str(payload))
        self.assertEqual(manager.latest()["status"], "finished")

    def test_unconfigured_real_notifier_makes_zero_requests(self):
        manager = self.manager(lambda *a, **kw: {"items": [{"game_id": "hk4e", "platform": "android", "ok": True, "new": True, "version": "1.0.0"}]})
        done = Event()
        def notify(*a, **kw):
            try:
                return telegram_notify.notify_operation(*a, **kw)
            finally:
                done.set()
        with patch.object(admin_operations, "notify_operation", side_effect=notify):
            manager.start(["discover"], ["hk4e"], "android", 5, 1)
            self.assertTrue(done.wait(2))
            self.assertTrue(manager.shutdown(2))
        self.transport.assert_not_called()
        self.assertEqual(manager.latest()["status"], "finished")

    def test_notification_preparation_failure_does_not_change_discovery_result(self):
        manager = self.manager(lambda *a, **kw: {"items": [{"game_id": "hk4e", "platform": "android", "ok": True, "new": True, "version": "1.0.0"}]})
        with patch.object(admin_operations, "_notification_discovery", side_effect=RuntimeError("TOKEN")), self.assertLogs(admin_operations.LOGGER) as logs:
            call = self.run_job(manager, actions=["discover", "probe"], scheduled_mode="normal")
        self.assertEqual(manager.latest()["status"], "finished")
        self.assertTrue(manager.latest()["result"]["discover"]["items"][0]["new"])
        self.assertNotIn("TOKEN", str(logs.output))
        self.assertTrue(call.kwargs["scheduled"])
        text, delete_after = telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=True)
        self.assertIsNone(text)
        self.assertIsNone(delete_after)

    def test_unreadable_previous_version_baseline_does_not_invent_an_update(self):
        manager = self.manager(lambda *a, **kw: {"items": [{"game_id": "hk4e", "platform": "android", "ok": True, "new": True, "version": "1.0.0"}]})
        with patch.object(admin_operations, "_previous_versions", side_effect=OSError("private")), self.assertLogs(admin_operations.LOGGER):
            call = self.run_job(manager)
        self.assertEqual(manager.latest()["status"], "finished")
        self.assertEqual(telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=True), (None, None))

    def test_low_level_probe_only_does_not_discover_or_create_updates(self):
        with patch.object(admin_operations, "discover_games", side_effect=AssertionError("no discovery")) as discovery:
            manager = self.manager(discovery)
            call = self.run_job(manager, actions=["probe"])
        discovery.assert_not_called()
        self.assertIsNone(call.args[0]["discover"])
        self.assertEqual(telegram_notify.build_message(call.args[0], started_at="", finished_at="", scheduled=False), (None, None))

    def test_failed_notifier_runs_after_save_outside_lock_and_cannot_fail_next_job(self):
        manager = self.manager(lambda *a, **kw: {"items": []})
        first_notifying, release_first, second_discovering, release_second = (Event() for _ in range(4))
        calls = []
        def notify(*a, **kw):
            calls.append((a, kw))
            if len(calls) == 1:
                self.assertEqual(self.store.read("latest_operation")["status"], "finished")
                first_notifying.set()
                self.assertTrue(release_first.wait(2))
                raise RuntimeError("TOKEN https://api.telegram.org/botTOKEN/sendMessage")
        def second(*a, **kw):
            second_discovering.set()
            self.assertTrue(release_second.wait(2))
            return {"items": []}
        with patch.object(admin_operations, "notify_operation", side_effect=notify), self.assertLogs(admin_operations.LOGGER) as logs:
            first = manager.start(["discover"], ["hk4e"], "android", 5, 1)
            first_thread = manager._thread
            self.assertTrue(first_notifying.wait(2))
            self.assertEqual(manager.latest()["status"], "finished")
            manager.discovery = second
            next_job = manager.start(["discover"], ["hk4e"], "android", 5, 1)
            self.assertTrue(second_discovering.wait(2))
            release_first.set()
            first_thread.join(2)
            self.assertFalse(first_thread.is_alive())
            self.assertEqual(manager.latest()["job_id"], next_job["job_id"])
            self.assertEqual(manager.latest()["status"], "running")
            manager._finish(first["job_id"], "failed", {})
            self.assertEqual(len(calls), 1)
            release_second.set()
            manager._thread.join(2)
            self.assertFalse(manager._thread.is_alive())
        self.assertEqual(manager.latest()["status"], "finished")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("TOKEN", str(logs.output))
        self.assertNotIn("Telegram", str(manager.latest()["logs"]))

    def test_cancelled_job_notification_reports_cancellation(self):
        entered, release, notified = Event(), Event(), Event()
        def discovery(*a, **kw):
            entered.set()
            self.assertTrue(release.wait(2))
            return {"items": []}
        manager = self.manager(discovery)
        with patch.object(admin_operations, "notify_operation", side_effect=lambda *a, **kw: notified.set()) as notify:
            job = manager.start(["discover"], ["hk4e"], "android", 5, 1)
            self.assertTrue(entered.wait(2))
            manager.cancel(job["job_id"])
            release.set()
            self.assertTrue(notified.wait(2))
            self.assertTrue(manager.shutdown(2))
        self.assertEqual(notify.call_args.kwargs["status"], "cancelled")
        self.assertEqual(manager.latest()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
