from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.admin_state import AdminStateError, AdminStateStore
from backend.app import create_app
from backend.indexes import rebuild_index
from backend.probe_scheduler import APSchedulerTimer, ProbeScheduler
from backend.test_admin_sync_operations import fake_probe, record
from backend.version_store import write_v2_record


class ManualTimer:
    def __init__(self):
        self.callback = None
        self.stopped = False

    def start(self, callback):
        self.callback = callback

    def stop(self):
        self.stopped = True


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AdminStateStore(Path(self.temp.name))
        self.now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        self.operations = Mock()
        self.operations.latest.side_effect = KeyError("latest")
        self.operations.start.return_value = {"job_id": "scheduled-1"}
        self.timer = ManualTimer()
        self.scheduler = self.make_scheduler()
        self.addCleanup(self.scheduler.stop)

    def make_scheduler(self, **kwargs):
        return ProbeScheduler(self.store, self.operations, authorized=True,
                              timer=kwargs.pop("timer", self.timer), clock=lambda: self.now, **kwargs)

    def enable(self, hours=1, mode="normal"):
        self.store.write_schedule("probe", {"enabled": True, "interval_hours": hours, "mode": mode})

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)
        self.scheduler.tick()

    def test_disabled_and_unconfigured_auth_do_not_trigger(self):
        self.scheduler.start()
        self.advance(days=10)
        self.operations.start.assert_not_called()
        self.assertIsNone(self.scheduler.status()["next_run_at"])
        self.enable()
        timer = ManualTimer()
        disabled = ProbeScheduler(self.store, self.operations, authorized=False, timer=timer)
        disabled.start()
        disabled.tick()
        self.assertIsNone(timer.callback)
        self.operations.start.assert_not_called()
        self.assertFalse(disabled.status()["running"])

    def test_first_cycle_exact_due_and_no_repeat(self):
        self.enable()
        self.scheduler.start()
        self.scheduler.start()
        self.advance(minutes=59, seconds=59)
        self.operations.start.assert_not_called()
        self.advance(seconds=1)
        args, kwargs = self.operations.start.call_args
        self.assertEqual(args[0], ["discover", "probe"])
        self.assertEqual(args[2:], ("all", 10, 8))
        self.assertIn("hk4e", args[1])
        self.assertEqual(kwargs, {"scheduled_mode": "normal"})
        self.assertEqual(self.scheduler.status()["last_job_id"], "scheduled-1")
        self.assertEqual(self.scheduler.status()["next_run_at"], "2026-09-14T02:00:00Z")
        self.scheduler.tick()
        self.operations.start.assert_called_once()

    def test_restart_keeps_deadline_and_coalesces_missed_runs(self):
        self.enable()
        self.scheduler.start()
        self.scheduler.stop()
        self.now += timedelta(hours=8)
        restarted = self.make_scheduler(timer=ManualTimer())
        self.addCleanup(restarted.stop)
        restarted.start()
        restarted.tick()
        self.operations.start.assert_called_once()
        self.assertEqual(restarted.status()["next_run_at"], "2026-09-14T09:00:00Z")

    def test_plan_change_and_disable_take_effect(self):
        self.enable()
        self.scheduler.start()
        self.advance(minutes=30)
        self.enable(hours=2, mode="full")
        self.scheduler.tick()
        self.assertEqual(self.scheduler.status()["next_run_at"], "2026-09-14T02:30:00Z")
        self.advance(hours=2)
        self.assertEqual(self.operations.start.call_args.kwargs["scheduled_mode"], "full")
        self.store.write_schedule("probe", {"enabled": False, "interval_hours": 2, "mode": "full"})
        self.scheduler.tick()
        self.advance(days=5)
        self.operations.start.assert_called_once()
        self.assertFalse(self.scheduler.status()["enabled"])
        self.assertIsNone(self.scheduler.status()["next_run_at"])

    def test_busy_and_racing_manual_job_keep_due_work_pending(self):
        self.enable()
        self.scheduler.start()
        self.operations.latest.side_effect = None
        self.operations.latest.return_value = {"status": "running"}
        self.advance(hours=1)
        self.operations.start.assert_not_called()
        self.operations.latest.return_value = {"status": "finished"}
        self.operations.start.side_effect = RuntimeError("operation_already_running")
        self.scheduler.tick()
        self.assertEqual(self.scheduler.status()["next_run_at"], "2026-09-14T01:00:00Z")
        self.operations.start.side_effect = None
        self.advance(seconds=5)
        self.assertEqual(self.operations.start.call_count, 2)
        self.assertEqual(self.scheduler.status()["last_started_at"], "2026-09-14T01:00:05Z")

    def test_corrupt_state_and_failed_reservation_do_not_dispatch(self):
        self.enable()
        self.store.write("probe_scheduler", {"bad": "shape"})
        with self.assertLogs("backend.probe_scheduler", level="ERROR"):
            self.scheduler.start()
        self.assertEqual(self.scheduler.status()["error"], "scheduler_state_invalid")
        self.operations.start.assert_not_called()
        # Restore only the isolated test document and test a storage failure at dispatch.
        self.store._path("probe_scheduler").unlink()
        self.scheduler.tick()
        with patch.object(self.store, "write", side_effect=AdminStateError("disk unavailable")):
            with self.assertLogs("backend.probe_scheduler", level="ERROR"):
                self.advance(hours=1)
        self.operations.start.assert_not_called()
        self.scheduler.tick()
        self.operations.start.assert_called_once()

    def test_start_failure_is_visible_and_retries_next_cycle(self):
        self.enable()
        self.scheduler.start()
        self.operations.start.side_effect = ValueError("sensitive details")
        with self.assertLogs("backend.probe_scheduler", level="ERROR") as logs:
            self.advance(hours=1)
        self.assertNotIn("sensitive details", str(logs.output))
        self.scheduler.tick()
        self.operations.start.assert_called_once()
        self.assertEqual(self.scheduler.status()["error"], "scheduled_probe_start_failed")
        self.operations.start.side_effect = None
        self.advance(hours=1)
        self.assertIsNone(self.scheduler.status()["error"])
        self.assertEqual(self.operations.start.call_count, 2)

    def test_stopped_timer_cannot_launch_work(self):
        self.enable()
        self.scheduler.start()
        self.scheduler.stop()
        self.advance(days=1)
        self.operations.start.assert_not_called()
        self.assertTrue(self.timer.stopped)

    def test_real_portable_timer_fires_and_stops(self):
        fired = Event()
        timer = APSchedulerTimer(poll_seconds=0.02)
        timer.start(fired.set)
        try:
            self.assertTrue(fired.wait(2), "real timer did not execute callback")
        finally:
            timer.stop()
        self.assertIsNone(timer._scheduler)


class SchedulerAppTests(unittest.TestCase):
    def test_lifespan_authenticated_save_and_due_probe_without_manual_post(self):
        with tempfile.TemporaryDirectory() as temp:
            data, state = Path(temp) / "data", Path(temp) / "state"
            data.mkdir()
            write_v2_record(record("android"), data)
            rebuild_index(data, "mihoyo", "hk4e", "android")
            now = [datetime(2026, 9, 14, tzinfo=timezone.utc)]
            called = Event()
            def probe(url, **kwargs):
                called.set()
                return fake_probe(url, **kwargs)
            discovery = Mock(return_value={"items": []})
            timer = APSchedulerTimer(poll_seconds=0.02)
            app = create_app(data, state_root=state, admin_token="fixture-token",
                             discovery=discovery, probe_fn=probe,
                             clock=lambda: now[0], scheduler_timer=timer)
            auth = {"Authorization": "Bearer fixture-token"}
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/v1/admin/probe/scheduler").status_code, 401)
                response = client.put("/api/v1/admin/probe/schedule", headers=auth,
                                      json={"enabled": True, "interval_hours": 1, "mode": "normal"})
                self.assertEqual(response.status_code, 200)
                status = client.get("/api/v1/admin/probe/scheduler", headers=auth).json()
                self.assertTrue(status["running"])
                self.assertEqual(status["next_run_at"], "2026-09-14T01:00:00Z")
                self.assertFalse(called.is_set())
                now[0] += timedelta(hours=1)
                self.assertTrue(called.wait(3), "timer did not dispatch the due probe")
                deadline = time.monotonic() + 3
                while True:
                    job = client.get("/api/v1/admin/operations/latest", headers=auth).json()
                    if job["status"] == "finished":
                        break
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                self.assertEqual(job["result"]["probe"]["checked"], 1)
                self.assertTrue(discovery.called)
                saved = json.loads((data / "mihoyo/hk4e/android/1.0.0.json").read_text())
                self.assertEqual(saved["artifacts"][0]["urls"][0]["current"]["state"], "available")
            self.assertFalse(app.state.probe_scheduler.status()["running"])
            self.assertIsNone(timer._scheduler)


if __name__ == "__main__":
    unittest.main()
