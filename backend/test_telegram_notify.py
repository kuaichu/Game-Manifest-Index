from __future__ import annotations

import urllib.parse
import os
import io
import ssl
import urllib.error
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


def _update():
    return {"game_id": "hk4e", "platform": "android", "version": "7.1.0", "ok": True, "new": True}


class TelegramNotifyTests(unittest.TestCase):
    def setUp(self):
        # Windows OpenSSL needs its OS directory variables even with mock HTTP.
        platform_env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
        env = patch.dict(os.environ, platform_env, clear=True)
        env.start()
        self.addCleanup(env.stop)
        transport = patch.object(telegram_notify.urllib.request, "urlopen", side_effect=AssertionError("unexpected HTTP"))
        transport.start()
        self.addCleanup(transport.stop)

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

    def test_scheduled_no_change_is_silent(self):
        text, delete_after = telegram_notify.build_message(
            _result(probe={"checked": 20, "available": 20, "unavailable": 0, "unknown": 0, "failed": 0, "items": []}),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:01:15Z",
            scheduled=True,
        )
        self.assertIsNone(delete_after)
        self.assertIsNone(text)

    def test_probe_failure_message_has_diagnostics(self):
        text, delete_after = telegram_notify.build_message(
            _result(updates=[_update()], probe={
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
        self.assertIn("存在巡检异常", text)
        self.assertIn("• 鸣潮 (Android 0.7.0): ProbeError (HTTP 502)", text)
        self.assertIn("• 崩坏3 (PC 3.9.1): 连接超时", text)
        self.assertIn("2,991 项", text)
        self.assertIn("2 异常", text)

    def test_confirmed_unavailable_is_alerted_without_calling_it_a_transport_failure(self):
        text, delete_after = telegram_notify.build_message(
            _result(updates=[_update()], probe={
                "checked": 1, "available": 0, "unavailable": 1, "unknown": 0, "failed": 0,
                "items": [{"game_id": "wuwa", "platform": "android", "version": "0.7.0", "ok": True, "available": False, "reason": "HTTP 404"}],
            }),
            started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:00:12Z",
            scheduled=True,
        )
        self.assertIsNone(delete_after)
        self.assertIn("存在巡检异常", text)
        self.assertIn("• 鸣潮 (Android 0.7.0): 链接不可用 (HTTP 404)", text)
        self.assertIn("1 不可用", text)

    def test_send_new_version_uses_bounded_verified_transport(self):
        result = _result(updates=[_update()], probe={"checked": 1, "available": 1, "unavailable": 0, "unknown": 0, "failed": 0, "items": []})
        with patch.object(
            telegram_notify.urllib.request, "urlopen",
            return_value=_Response(b'{"ok": true, "result": {"message_id": 42}}'),
        ) as urlopen:
            sent = telegram_notify.notify_operation(
                result, started_at="2026-09-24T00:00:00Z", finished_at="2026-09-24T00:00:01Z",
                scheduled=True, environ={"GMI_TELEGRAM_BOT_TOKEN": "secret", "GMI_TELEGRAM_CHAT_ID": "-1001"},
            )
        self.assertEqual(sent, [{"chat_id": "-1001", "ok": True}])
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        body = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(body["chat_id"], ["-1001"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        self.assertEqual(urlopen.call_args.kwargs["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(urlopen.call_args.kwargs["context"].check_hostname)

    def test_ssl_context_supplements_default_trust_with_certifi(self):
        with patch.object(telegram_notify.ssl, "create_default_context") as defaults:
            context = telegram_notify._ssl_context()
        defaults.assert_called_once_with()
        context.load_verify_locations.assert_called_once_with(cafile=telegram_notify.certifi.where())
        actual = telegram_notify._ssl_context()
        self.assertEqual(actual.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(actual.check_hostname)
        self.assertGreater(actual.cert_store_stats()["x509_ca"], 0)

    def test_no_configuration_makes_no_http_requests(self):
        for environ in ({}, {"GMI_TELEGRAM_BOT_TOKEN": "secret"}, {"GMI_TELEGRAM_CHAT_ID": "-1"}):
            with patch.object(telegram_notify.urllib.request, "urlopen") as transport:
                self.assertEqual(telegram_notify.notify_operation(
                    _result(updates=[_update()]), started_at="", finished_at="", scheduled=True, environ=environ,
                ), [])
                transport.assert_not_called()

    def test_multiple_targets_continue_after_failure_and_logs_hide_credentials(self):
        with patch.object(telegram_notify.urllib.request, "urlopen", side_effect=[
            OSError("secret https://api.telegram.org/botsecret/sendMessage"),
            _Response(b'{"ok":true,"result":{"message_id":43}}'),
            _Response(b'{"ok":true,"result":{"message_id":44}}'),
        ]) as transport, self.assertLogs(telegram_notify.LOGGER) as logs:
            sent = telegram_notify.notify_operation(
                _result(updates=[_update()]), started_at="", finished_at="", scheduled=True,
                environ={"GMI_TELEGRAM_BOT_TOKEN": "secret", "GMI_TELEGRAM_CHAT_ID": "-1, -2\n-3"},
            )
        self.assertEqual(sent, [{"chat_id": "-1", "ok": False}, {"chat_id": "-2", "ok": True}, {"chat_id": "-3", "ok": True}])
        self.assertEqual(transport.call_count, 3)
        self.assertTrue(all(call.kwargs["timeout"] == 10 for call in transport.call_args_list))
        self.assertNotIn("secret", str(logs.output))

    def test_temporary_http_failures_retry_then_succeed(self):
        for code in (429, 502, 503):
            with self.subTest(code=code), patch.object(telegram_notify.time, "sleep") as sleep, patch.object(
                telegram_notify.urllib.request, "urlopen", side_effect=[
                    urllib.error.HTTPError("https://secret.test", code, "secret", {}, io.BytesIO(b'{"parameters":{"retry_after":1}}')),
                    _Response(b'{"ok":true,"result":{"message_id":42}}'),
                ],
            ) as transport:
                self.assertEqual(telegram_notify._send_one("secret", "-1", "text"), 42)
                self.assertEqual(transport.call_count, 2)
                sleep.assert_called_once_with(1)

    def test_connection_and_timeout_failures_retry_at_most_three_attempts(self):
        with patch.object(telegram_notify.time, "sleep") as sleep, patch.object(
            telegram_notify.urllib.request, "urlopen", side_effect=[
                urllib.error.URLError(TimeoutError("secret")), ConnectionResetError("secret"),
                _Response(b'{"ok":true,"result":{"message_id":42}}'),
            ],
        ) as transport:
            self.assertEqual(telegram_notify._send_one("secret", "-1", "text"), 42)
        self.assertEqual(transport.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        with patch.object(telegram_notify.time, "sleep") as sleep, patch.object(
            telegram_notify.urllib.request, "urlopen", side_effect=TimeoutError("secret"),
        ) as transport, self.assertLogs(telegram_notify.LOGGER) as logs:
            sent = telegram_notify.notify_operation(_result(updates=[_update()]), started_at="", finished_at="", scheduled=True,
                environ={"GMI_TELEGRAM_BOT_TOKEN": "secret", "GMI_TELEGRAM_CHAT_ID": "-1"})
        self.assertEqual(sent, [{"chat_id": "-1", "ok": False}])
        self.assertEqual(transport.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertNotIn("secret", str(logs.output))

    def test_client_rejection_and_certificate_errors_are_not_retried(self):
        errors = [urllib.error.HTTPError("https://secret.test", code, "secret", {}, None) for code in (400, 401, 403)]
        errors.extend([ssl.SSLCertVerificationError("secret"), urllib.error.URLError(ssl.SSLCertVerificationError("secret"))])
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(telegram_notify.time, "sleep") as sleep, patch.object(
                telegram_notify.urllib.request, "urlopen", side_effect=error,
            ) as transport:
                with self.assertRaises(type(error)):
                    telegram_notify._send_one("secret", "-1", "text")
                self.assertEqual(transport.call_count, 1)
                sleep.assert_not_called()

    def test_long_flood_wait_is_not_retried_immediately(self):
        error = urllib.error.HTTPError("https://secret.test", 429, "secret", {}, io.BytesIO(b'{"parameters":{"retry_after":60}}'))
        with patch.object(telegram_notify.time, "sleep") as sleep, patch.object(
            telegram_notify.urllib.request, "urlopen", side_effect=error,
        ) as transport:
            with self.assertRaises(urllib.error.HTTPError):
                telegram_notify._send_one("secret", "-1", "text")
        self.assertEqual(transport.call_count, 1)
        sleep.assert_not_called()

    def test_raw_details_urls_paths_and_tokens_are_never_in_messages(self):
        secret = "PRIVATE_SECRET_ABC"
        text, _ = telegram_notify.build_message(
            _result(updates=[_update()], probe={"checked": 1, "failed": 1, "items": [{
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

    def test_archive_only_is_silent(self):
        text, _ = telegram_notify.build_message(
            _result(updates=[{"game_id": "hk4e", "platform": "windows", "version": "6.9.0", "archived": True, "ok": True, "new": True}]),
            started_at="", finished_at="", scheduled=False,
        )
        self.assertIsNone(text)

    def test_no_update_or_pure_errors_are_silent_in_manual_and_scheduled_runs(self):
        configured = {"GMI_TELEGRAM_BOT_TOKEN": "secret", "GMI_TELEGRAM_CHAT_ID": "-1"}
        results = [_result(), _result(probe={"checked": 1, "failed": 1}), _result(probe={"checked": 1, "unavailable": 1}),
            {"discover": {"failed": 1, "items": []}}, _result(updates=[{**_update(), "archived": True}])]
        for scheduled in (False, True):
            for status in ("finished", "failed", "cancelled"):
                for result in results:
                    with patch.object(telegram_notify.urllib.request, "urlopen") as transport:
                        self.assertEqual(telegram_notify.notify_operation(result, started_at="", finished_at="", scheduled=scheduled, status=status, environ=configured), [])
                        transport.assert_not_called()

    def test_mixed_pc_updates_exclude_archive_versions(self):
        updates = [{**_update(), "platform": "windows"}, {**_update(), "platform": "windows", "version": "6.9.0", "archived": True}]
        text, delete_after = telegram_notify.build_message(_result(updates=updates), started_at="", finished_at="", scheduled=True)
        self.assertIn("7.1.0", text)
        self.assertNotIn("6.9.0", text)
        self.assertNotIn("归档", text)
        self.assertIsNone(delete_after)


if __name__ == "__main__":
    unittest.main()
