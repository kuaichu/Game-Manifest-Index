from __future__ import annotations

import urllib.parse
import os
import threading
import unittest
from unittest.mock import patch

from backend import telegram_notify


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.payload


def _result(*, updates=None, probe=None):
    return {"discover": {"items": updates or []}, "probe": probe}


class TelegramNotifyTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_multi_update_message_uses_names_previous_versions_and_stats(self):
        text, delete_after = telegram_notify.build_message(
            _result(
                updates=[
                    {"game_id": "hk4e", "platform": "android", "version": "7.1.0", "previous_version": "7.0.0", "ok": True, "new": True},
                    {"game_id": "p5x", "platform": "android", "version": "1.5.8", "previous_version": "1.5.7", "ok": True, "new": True},
                    {"game_id": "tof", "platform": "windows", "version": "6.4.1", "previous_version": "6.4.0", "ok": True, "new": True},
                ],
                probe={"checked": 2991, "available": 2989, "unavailable": 0, "unknown": 0, "failed": 2, "items": []},
            ),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:01:57Z",
            scheduled=True,
        )
        self.assertIsNone(delete_after)
        self.assertIn("[GMI 资源巡检] 检测到版本更新", text)
        self.assertIn("• 原神 (Android): 7.0.0 -> 7.1.0", text)
        self.assertIn("• 女神异闻录：夜幕魅影 (Android): 1.5.7 -> 1.5.8", text)
        self.assertIn("• 幻塔 (PC): 6.4.0 -> 6.4.1", text)
        self.assertIn("耗时: 1分57秒 | 探活: 2,991 项 (2,989 可用 / 2 异常)", text)

    def test_single_update_message_is_compact(self):
        text, delete_after = telegram_notify.build_message(
            _result(
                updates=[{"game_id": "nte", "platform": "android", "version": "1.3.0", "previous_version": "1.2.1", "ok": True, "new": True}],
                probe={"checked": 1, "available": 1, "unavailable": 0, "unknown": 0, "failed": 0, "items": []},
            ),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:00:12Z",
            scheduled=False,
        )
        self.assertIsNone(delete_after)
        self.assertEqual(text, "[GMI 资源巡检] 发现新版本\n\n• 异环 (Android): 1.2.1 -> 1.3.0\n\n耗时: 12秒 | 探活正常")

    def test_unprobed_discovery_does_not_claim_probe_success(self):
        text, _ = telegram_notify.build_message(
            _result(updates=[{"game_id": "nte", "platform": "android", "version": "1.3.0", "ok": True, "new": True}]),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:00:12Z",
            scheduled=False,
        )
        self.assertIn("未执行探活", text)

    def test_scheduled_no_change_is_transient_heartbeat(self):
        text, delete_after = telegram_notify.build_message(
            _result(probe={"checked": 20, "available": 20, "unavailable": 0, "unknown": 0, "failed": 0, "items": []}),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:01:15Z",
            scheduled=True,
        )
        self.assertEqual(delete_after, 600)
        self.assertIn("[GMI 调度心跳] 巡检完成", text)
        self.assertIn("• 未检测到版本变动", text)
        self.assertIn("• 耗时: 1分15秒 | 探活正常", text)
        self.assertIn("(10 分钟后自动销毁)", text)

    def test_probe_failure_message_has_diagnostics(self):
        text, delete_after = telegram_notify.build_message(
            _result(probe={
                "checked": 2991, "available": 2989, "unavailable": 0, "unknown": 0, "failed": 2,
                "items": [
                    {"game_id": "wuwa", "platform": "android", "version": "0.7.0", "ok": False, "error": "ProbeError", "status": 502},
                    {"game_id": "bh3", "platform": "windows", "version": "3.9.1", "ok": False, "error": "ProbeError", "status": None, "detail": "连接超时"},
                ],
            }),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:02:10Z",
            scheduled=True,
        )
        self.assertIsNone(delete_after)
        self.assertIn("[GMI 巡检异常] 检测到探活失败", text)
        self.assertIn("• 鸣潮 (Android 0.7.0): ProbeError (HTTP 502)", text)
        self.assertIn("• 崩坏3 (PC 3.9.1): 连接超时", text)
        self.assertIn("总计: 2,991 项 | 失败: 2 项", text)

    def test_confirmed_unavailable_is_alerted_without_calling_it_a_transport_failure(self):
        text, delete_after = telegram_notify.build_message(
            _result(probe={
                "checked": 1, "available": 0, "unavailable": 1, "unknown": 0, "failed": 0,
                "items": [{"game_id": "wuwa", "platform": "android", "version": "0.7.0", "ok": True, "available": False, "reason": "HTTP 404"}],
            }),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:00:12Z",
            scheduled=True,
        )
        self.assertIsNone(delete_after)
        self.assertIn("检测到不可用链接", text)
        self.assertIn("• 鸣潮 (Android 0.7.0): 链接不可用 (HTTP 404)", text)
        self.assertIn("总计: 1 项 | 不可用: 1 项", text)

    def test_send_and_schedule_heartbeat_deletion(self):
        result = _result(probe={"checked": 1, "available": 1, "unavailable": 0, "unknown": 0, "failed": 0, "items": []})
        with patch.object(
            telegram_notify.urllib.request, "urlopen",
            return_value=_Response(b'{"ok": true, "result": {"message_id": 42}}'),
        ) as urlopen, patch.object(telegram_notify, "_delete_later") as delete_later:
            sent = telegram_notify.notify_operation(
                result, started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:00:01Z",
                scheduled=True, environ={"GMI_TELEGRAM_BOT_TOKEN": "secret", "GMI_TELEGRAM_CHAT_ID": "-1001"},
            )
        self.assertEqual(sent, [{"chat_id": "-1001", "ok": True}])
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        body = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(body["chat_id"], ["-1001"])
        self.assertEqual(delete_later.call_args.args, ("secret", "-1001", 42, 600))

    def test_delete_request_uses_message_id(self):
        with patch.object(
            telegram_notify.urllib.request, "urlopen",
            return_value=_Response(b'{"ok": true, "result": true}'),
        ) as urlopen:
            telegram_notify._delete_one("secret", "-1001", 42)
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/deleteMessage"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        self.assertEqual(
            urllib.parse.parse_qs(request.data.decode("utf-8")),
            {"chat_id": ["-1001"], "message_id": ["42"]},
        )

    def test_no_configuration_makes_no_http_requests(self):
        for environ in ({}, {"GMI_TELEGRAM_BOT_TOKEN": "secret"}, {"GMI_TELEGRAM_CHAT_ID": "-1"}):
            with patch.object(telegram_notify.urllib.request, "urlopen") as transport:
                self.assertEqual(telegram_notify.notify_operation(
                    _result(), started_at="", finished_at="", scheduled=True, environ=environ,
                ), [])
                transport.assert_not_called()

    def test_multiple_targets_continue_after_failure_and_logs_hide_credentials(self):
        with patch.object(telegram_notify.urllib.request, "urlopen", side_effect=[
            OSError("secret https://api.telegram.org/botsecret/sendMessage"),
            _Response(b'{"ok":true,"result":{"message_id":43}}'),
            _Response(b'{"ok":true,"result":{"message_id":44}}'),
        ]) as transport, patch.object(telegram_notify, "_delete_later") as delete_later, self.assertLogs(telegram_notify.LOGGER) as logs:
            sent = telegram_notify.notify_operation(
                _result(), started_at="", finished_at="", scheduled=True,
                environ={"GMI_TELEGRAM_BOT_TOKEN": "secret", "GMI_TELEGRAM_CHAT_ID": "-1, -2\n-3"},
            )
        self.assertEqual(sent, [{"chat_id": "-1", "ok": False}, {"chat_id": "-2", "ok": True}, {"chat_id": "-3", "ok": True}])
        self.assertEqual(transport.call_count, 3)
        self.assertTrue(all(call.kwargs["timeout"] == 10 for call in transport.call_args_list))
        self.assertEqual(delete_later.call_count, 2)
        self.assertNotIn("secret", str(logs.output))

    def test_delete_later_calls_transport_without_waiting_ten_minutes(self):
        done = threading.Event()
        def response(*args, **kwargs):
            done.set()
            return _Response(b'{"ok":true,"result":true}')
        with patch.object(telegram_notify.time, "sleep") as sleep, patch.object(
            telegram_notify.urllib.request, "urlopen", side_effect=response,
        ) as transport:
            telegram_notify._delete_later("secret", "-1", 42, 600)
            self.assertTrue(done.wait(2))
        sleep.assert_called_once_with(600)
        self.assertTrue(transport.call_args.args[0].full_url.endswith("/deleteMessage"))

    def test_raw_details_urls_paths_and_tokens_are_never_in_messages(self):
        secret = "PRIVATE_SECRET_ABC"
        text, _ = telegram_notify.build_message(
            _result(probe={"checked": 1, "failed": 1, "items": [{
                "game_id": "hk4e", "platform": "android", "version": "1.0.0",
                "ok": False, "error": secret, "detail": f"token={secret} D:/private/repo https://a.test/{secret}",
                "reason": secret, "url": f"https://a.test/{secret}",
            }]}), started_at="", finished_at="", scheduled=False,
        )
        self.assertIn("ProbeError", text)
        self.assertNotIn(secret, text)
        self.assertNotIn("private/repo", text)
        self.assertNotIn("https://", text)

    def test_updates_report_discovery_failures_and_terminal_status(self):
        result = _result(updates=[{"game_id": "hk4e", "platform": "android", "version": "7.1.0", "ok": True, "new": True}])
        result["discover"]["failed"] = 1
        for status, label in (("finished", "存在巡检异常"), ("failed", "任务失败"), ("cancelled", "任务已取消")):
            text, delete_after = telegram_notify.build_message(result, started_at="", finished_at="", scheduled=True, status=status)
            self.assertIn(label, text)
            self.assertIn("官方发现失败: 1 项", text)
            self.assertIsNone(delete_after)

    def test_archive_message_does_not_claim_a_new_release(self):
        text, _ = telegram_notify.build_message(
            _result(updates=[{"game_id": "hk4e", "platform": "windows", "version": "6.9.0", "archived": True, "ok": True, "new": True}]),
            started_at="", finished_at="", scheduled=False,
        )
        self.assertIn("新增归档版本 6.9.0", text)
        self.assertNotIn("发现新版本", text)
        self.assertNotIn("->", text)

    def test_failed_or_cancelled_manual_task_is_not_silently_omitted(self):
        for status, label in (("failed", "任务失败"), ("cancelled", "任务已取消")):
            text, delete_after = telegram_notify.build_message(_result(), started_at="", finished_at="", scheduled=False, status=status)
            self.assertIn(label, text)
            self.assertIsNone(delete_after)


if __name__ == "__main__":
    unittest.main()
