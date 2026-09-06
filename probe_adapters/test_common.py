import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from probe_adapters.common import ProbeError, probe_url, probe_head


class ProbeTransportTests(unittest.TestCase):
    URL = "https://autopatchcn.bh3.com/game.apk"

    def _curl(self, code: int, body: bytes, status: int = 206):
        def run(command, **kwargs):
            body_path = command[command.index("-o") + 1]
            Path(body_path).write_bytes(body)
            output = (
                f"HTTP/1.1 {status} Test\r\n"
                f"Content-Length: {len(body)}\r\n\r\n"
                "\n__GMI_PROBE_META__\n"
                f"http={status}\nurl={self.URL}\n"
            ).encode()
            return SimpleNamespace(stdout=output, stderr=b"", returncode=code)
        return run

    def test_curl_63_with_full_range_and_signature_is_accepted(self):
        with patch("probe_adapters.common.subprocess.run", side_effect=self._curl(63, b"PK\x03\x04" + b"x" * 12)):
            status, headers, url, prefix = probe_url(self.URL)
        self.assertEqual(status, 206)
        self.assertEqual(len(prefix), 16)
        self.assertTrue(prefix.startswith(b"PK\x03\x04"))

    def test_curl_63_short_or_empty_body_is_rejected(self):
        for body in (b"PK\x03\x04", b""):
            with self.subTest(length=len(body)), patch(
                "probe_adapters.common.subprocess.run", side_effect=self._curl(63, body)
            ):
                with self.assertRaises(ProbeError):
                    probe_url(self.URL)

    def test_curl_0_short_body_is_observation_for_adapter_to_reject(self):
        body = b"<Error><Code>InvalidObjectState</Code></Error>"
        with patch("probe_adapters.common.subprocess.run", side_effect=self._curl(0, body, status=403)):
            observation = probe_url(self.URL)
            status, headers, url, prefix = observation
        self.assertEqual(status, 403)
        self.assertEqual(prefix, body[:16])
        self.assertEqual(observation.body, body)
        self.assertEqual(len(tuple(observation)), 4)

    def test_transport_error_preserves_complete_small_error_body(self):
        body = (
            b"<Error><Code>InvalidObjectState</Code>"
            b"<Message>Object is archived</Message></Error>"
        )
        with patch("probe_adapters.common.subprocess.run", side_effect=self._curl(56, body, status=403)):
            with self.assertRaises(ProbeError) as raised:
                probe_url(self.URL)
        self.assertIn(b"<Code>InvalidObjectState</Code>", raised.exception.body)
        self.assertEqual(raised.exception.prefix, body[:16])

    def test_non_positive_timeout_is_rejected_before_curl(self):
        for value in (0, -1, True, "10"):
            with self.subTest(value=value), patch("probe_adapters.common.subprocess.run") as run:
                with self.assertRaises(ProbeError):
                    probe_url(self.URL, value)
                run.assert_not_called()

    def test_subprocess_timeout_is_converted_to_probe_error(self):
        with patch(
            "probe_adapters.common.subprocess.run",
            side_effect=subprocess.TimeoutExpired("curl", 15),
        ):
            with self.assertRaisesRegex(ProbeError, "curl 超时"):
                probe_url(self.URL, 10)

    def test_curl_command_keeps_snapshot_transport_limits(self):
        with patch("probe_adapters.common.subprocess.run", side_effect=self._curl(0, b"")) as run:
            probe_url(self.URL, 7)
        command = run.call_args.args[0]
        self.assertIn("--connect-timeout", command); self.assertIn("10", command)
        self.assertIn("--max-time", command); self.assertIn("7", command)
        self.assertIn("--max-redirs", command); self.assertIn("8", command)
        self.assertIn("--max-filesize", command); self.assertIn("4096", command)
        self.assertIn("--range", command); self.assertIn("0-15", command)


if __name__ == "__main__":
    unittest.main()
