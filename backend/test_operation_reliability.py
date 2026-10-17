from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread
from unittest.mock import patch

from backend.admin_state import AdminStateError
from backend.test_admin_sync_operations import AdminFixture, fake_probe


class OperationStartReliabilityTests(AdminFixture):
    payload = {"actions": ["discover"], "scope": "android", "all_games": False, "game_ids": ["hk4e"]}

    def test_snapshot_failure_reports_storage_error_and_releases_slot(self):
        client = self.client()
        manager = client.app.state.admin_operations
        with patch.object(manager.store, "write", side_effect=AdminStateError("private path")):
            with self.assertLogs("backend.admin_operations", level="ERROR"):
                response = client.post("/api/v1/admin/operations/start", headers=self.auth(), json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "admin_state_unavailable")
        self.assertNotIn("private path", response.text)
        self.assertNotIn(manager.latest()["status"], {"running", "cancelling"})
        retry = client.post("/api/v1/admin/operations/start", headers=self.auth(), json=self.payload)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(manager.shutdown(2))

    def test_thread_start_failure_is_terminal_and_retryable(self):
        client = self.client()
        manager = client.app.state.admin_operations
        with patch("backend.admin_operations.Thread") as thread_class:
            thread_class.return_value.start.side_effect = RuntimeError("private failure")
            response = client.post("/api/v1/admin/operations/start", headers=self.auth(), json=self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "operation_start_failed")
        self.assertNotIn("private failure", response.text)
        self.assertEqual(manager.latest()["status"], "failed")
        self.assertEqual(manager.store.read("latest_operation")["status"], "failed")
        self.assertTrue(manager.shutdown(0))
        retry = client.post("/api/v1/admin/operations/start", headers=self.auth(), json=self.payload)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(manager.shutdown(2))


class ProbeStatusReliabilityTests(AdminFixture):
    def test_manual_probe_overrides_old_job_then_new_job_overrides_manual(self):
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def controlled(url, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test timeout")
            return fake_probe(url, **kwargs)

        # Fixed time also checks ordering when both operations start in the same second.
        client = self.client(probe_fn=controlled, clock=lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
        manager = client.app.state.admin_operations
        with patch("backend.admin_operations.notify_operation"):
            manager.start(["probe"], [], "android", 1, 1)
            self.assertTrue(manager.shutdown(2))

        responses = []
        worker = Thread(target=lambda: responses.append(client.post(
            "/api/v1/admin/probe/url", headers=self.auth(),
            json={"url": "https://autopatchcn.yuanshen.com/test.apk"},
        )))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            running = client.get("/api/v1/admin/probe/status", headers=self.auth()).json()
            self.assertEqual((running["status"], running["family"]), ("running", "single"))
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(responses[0].status_code, 200)
        finished = client.get("/api/v1/admin/probe/status", headers=self.auth()).json()
        self.assertEqual((finished["status"], finished["family"]), ("finished", "single"))

        with patch("backend.admin_operations.notify_operation"):
            manager.start(["probe"], [], "pc", 1, 1)
            self.assertTrue(manager.shutdown(2))
        newest = client.get("/api/v1/admin/probe/status", headers=self.auth()).json()
        self.assertEqual(newest["family"], "pc")

    def test_failed_manual_probe_finishes_with_failure_log_and_releases_slot(self):
        client = self.client()
        response = client.post("/api/v1/admin/probe/url", headers=self.auth(), json={"url": "invalid"})
        self.assertEqual(response.status_code, 422)
        status = client.get("/api/v1/admin/probe/status", headers=self.auth()).json()
        self.assertEqual(status["status"], "finished")
        self.assertIn("同步探活失败", status["log"])
        self.assertNotIn("同步探活完成", status["log"])
        client.app.state.admin_operations.begin_manual_probe()
        client.app.state.admin_operations.end_manual_probe()

    def test_returned_probe_failures_are_not_logged_as_success(self):
        def failing_probe(*args, **kwargs):
            raise ValueError("private probe failure")

        client = self.client(probe_fn=failing_probe)
        url = self.android["artifacts"][0]["urls"][0]["url"]
        for route, payload in (
            ("/api/v1/admin/probe/url", {"url": url}),
            ("/api/v1/admin/probe/urls", {"urls": [url]}),
            ("/api/v1/admin/domains/hk4e-android/versions/1.0.0/probe", None),
        ):
            with self.subTest(route=route):
                response = client.post(route, headers=self.auth(), json=payload)
                self.assertEqual(response.status_code, 200)
                status = client.get("/api/v1/admin/probe/status", headers=self.auth()).json()
                self.assertEqual(status["status"], "finished")
                self.assertIn("同步探活失败", status["log"])
                self.assertNotIn("private probe failure", str(status))
