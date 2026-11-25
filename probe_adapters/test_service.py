import ast
import inspect
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import artifact_id
from probe_adapters.android import shared_generic_apk
from probe_adapters.common import ProbeError, ProbeObservation
from probe_adapters.registry import ANDROID_ADAPTERS, PC_ADAPTERS
from probe_adapters import service as probe_service
from probe_adapters.service import current_from_result, probe


def v2_record() -> dict:
    identity = {
        "vendor": "mihoyo", "game_id": "hk4e", "domain_id": "hk4e-android",
        "platform": "android", "channel": "official", "version": "7.0.0",
    }
    artifact = {
        "kind": "apk", "component": "game", "package_type": "full",
        "delivery_mode": "direct", "name": "game.apk",
        "urls": [{
            "url": "https://example.test/old.apk", "provider": "mihoyo",
            "source_kind": "official", "priority": 0,
        }],
    }
    artifact["artifact_id"] = artifact_id(artifact, record_identity=identity)
    return {
        "schema_version": 2, **identity, "version_code": None,
        "file_time": "manual-date", "artifacts": [artifact], "references": [],
    }


class ProbeServiceTests(unittest.TestCase):
    def test_bh3_retired_host_is_static_and_does_not_use_network(self):
        url = "https://app.bh3.com/public/Android/old.apk"
        with patch("probe_adapters.service.probe_url") as range_probe, patch("probe_adapters.service.probe_head") as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3")
        range_probe.assert_not_called()
        head_probe.assert_not_called()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "retired_official_host")
        self.assertIsNone(result["http_code"])

    def test_bh3_archive_403_range_failure_preserves_response_without_head(self):
        url = "https://bundle.bh3.com/public/Android/archived.apk"
        error = ProbeError("archived", returncode=56, status=403, final_url=url,
                           headers={}, body=b"<Error><Code>InvalidObjectState</Code></Error>")
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head",
            return_value=(200, {"content-length": "123", "x-oss-storage-class": "Archive"}, url),
        ) as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3", expected_size=123)
        head_probe.assert_not_called()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "oss_archive_not_restored")
        self.assertIsNone(result["metadata_http_code"])
        self.assertEqual(result["http_code"], 403)
        self.assertEqual(result["source_kind"], "official_storage_metadata")
        self.assertEqual(result["transport_returncode"], 56)

    def test_non_bh3_range_failure_does_not_use_head(self):
        url = "https://autopatchcn.yuanshen.com/game.apk"
        error = ProbeError("failed", returncode=56, final_url=url)
        with patch("probe_adapters.service.probe_url", side_effect=error), patch("probe_adapters.service.probe_head") as head_probe:
            with self.assertRaises(ProbeError) as ctx:
                probe(url, vendor="mihoyo", game_id="hk4e")
        head_probe.assert_not_called()
        self.assertEqual(getattr(ctx.exception, "adapter", None), "mihoyo_autopatch")

    def test_bh3_head_fallback_success_projects_official_storage_metadata(self):
        url = "https://bundle.bh3.com/public/Android/archived.apk"
        error = ProbeError(
            "reset", returncode=56, status=206, final_url=url,
            headers={"content-range": "bytes 0-15/456"},
        )
        head_headers = {
            "content-length": "456",
            "x-oss-storage-class": "Archive",
            "x-oss-hash-crc64ecma": "9999",
        }
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head",
            return_value=(200, head_headers, url),
        ) as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3", expected_size=456)
        head_probe.assert_called_once_with(url, 10)
        self.assertEqual(result["adapter"], "mihoyo_bh3_cdn")
        self.assertEqual(result["platform"], "android")
        self.assertIs(result["available"], False)
        self.assertIsNone(result["http_code"])
        self.assertEqual(result["metadata_http_code"], 200)
        self.assertEqual(result["size"], 456)
        self.assertEqual(result["observed_size"], 456)
        self.assertEqual(result["expected_size"], 456)
        self.assertEqual(result["crc64"], "9999")
        self.assertEqual(result["reason"], "oss_archive_not_restored")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["source_kind"], "official_storage_metadata")
        self.assertEqual(result["transport_returncode"], 56)
        self.assertEqual(result["bytes_received"], 0)

    def test_bh3_head_fallback_recovers_from_range_archive_evidence_when_head_fails(self):
        url = "https://bundle.bh3.com/public/Android/archived.apk"
        error = ProbeError(
            "reset", returncode=56, status=502, final_url=url,
            headers={"x-oss-hash-crc64ecma": "7777"},
            body=b"<Error><Code>InvalidObjectState</Code></Error>",
        )
        head_error = ProbeError("head timeout", returncode=28)
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head",
            side_effect=head_error,
        ) as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3", expected_size=456)
        head_probe.assert_called_once_with(url, 10)
        self.assertIs(result["available"], False)
        self.assertIsNone(result["http_code"])
        self.assertEqual(result["metadata_http_code"], 502)
        self.assertEqual(result["crc64"], "7777")
        self.assertEqual(result["reason"], "oss_archive_not_restored")
        self.assertEqual(result["source_kind"], "official_storage_metadata")
        self.assertEqual(result["transport_returncode"], 56)
        self.assertEqual(result["bytes_received"], 0)

    def test_bh3_head_fallback_redirect_to_retired_host_returns_static_preflight(self):
        url = "https://bundle.bh3.com/public/Android/old.apk"
        retired = "https://app.bh3.com/public/Android/old.apk"
        error = ProbeError("reset", returncode=56, final_url=url)
        with patch("probe_adapters.service.probe_url", side_effect=error), patch(
            "probe_adapters.service.probe_head",
            return_value=(200, {}, retired),
        ) as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3", expected_size=100)
        head_probe.assert_called_once_with(url, 10)
        self.assertIs(result["available"], False)
        self.assertEqual(result["url"], retired)
        self.assertIsNone(result["http_code"])
        self.assertEqual(result["reason"], "retired_official_host")
        self.assertEqual(result["source_kind"], "adapter_policy")

    def test_bh3_head_fallback_failure_paths_preserve_adapter_on_probe_error(self):
        url = "https://bundle.bh3.com/public/Android/unconfirmed.apk"
        range_error = ProbeError("reset", returncode=56, status=206, final_url=url)
        with patch("probe_adapters.service.probe_url", side_effect=range_error), patch(
            "probe_adapters.service.probe_head",
            return_value=(200, {"content-length": "456", "content-type": "application/vnd.android.package-archive"}, url),
        ):
            with self.assertRaisesRegex(ProbeError, r"HEAD fallback 无法确认资源（HTTP 200）") as unconfirmed_ctx:
                probe(url, vendor="mihoyo", game_id="bh3", expected_size=456)
        self.assertEqual(unconfirmed_ctx.exception.status, 200)
        self.assertEqual(unconfirmed_ctx.exception.final_url, url)
        self.assertEqual(getattr(unconfirmed_ctx.exception, "adapter", None), "mihoyo_bh3_cdn")

        head_error = ProbeError("head failed", returncode=28)
        with patch("probe_adapters.service.probe_url", side_effect=range_error), patch(
            "probe_adapters.service.probe_head",
            side_effect=head_error,
        ):
            with self.assertRaisesRegex(ProbeError, "head failed") as head_ctx:
                probe(url, vendor="mihoyo", game_id="bh3", expected_size=456)
        self.assertIs(head_ctx.exception, head_error)
        self.assertEqual(getattr(head_ctx.exception, "adapter", None), "mihoyo_bh3_cdn")

    def test_service_avoids_locals_and_all_availability_hooks_accept_evidence_kwargs(self):
        source = Path(probe_service.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=probe_service.__file__)
        locals_refs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "locals"
        ]
        self.assertEqual(locals_refs, [])

        evidence_kwargs = {
            "observed_size": 16,
            "expected_size": 16,
            "transport_returncode": 0,
            "bytes_received": 16,
        }
        checked = 0
        for adapter in (*ANDROID_ADAPTERS, *PC_ADAPTERS, shared_generic_apk):
            availability = getattr(adapter, "availability", None)
            if availability is None:
                continue
            checked += 1
            with self.subTest(adapter=adapter.NAME, module=adapter.__name__):
                params = inspect.signature(availability).parameters.values()
                has_var_keyword = any(
                    param.kind == inspect.Parameter.VAR_KEYWORD for param in params
                )
                accepted_names = {
                    param.name for param in params
                    if param.kind in (
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.KEYWORD_ONLY,
                    )
                }
                self.assertTrue(
                    has_var_keyword or set(evidence_kwargs).issubset(accepted_names),
                    f"{adapter.__name__}.availability does not accept all evidence kwargs",
                )
                verdict = availability(
                    206, "sample.apk", b"PK\x03\x04" + b"\x00" * 12, **evidence_kwargs,
                )
                self.assertIn(verdict, (True, False, None))
        self.assertGreater(checked, 0)

    def test_bh3_readable_range_does_not_use_head(self):
        url = "https://bundle.bh3.com/public/Android/readable.apk"
        with patch("probe_adapters.service.probe_url", return_value=(206, {"content-type": "application/vnd.android.package-archive"}, url, b"PK\x03\x04" + b"x" * 12)), patch("probe_adapters.service.probe_head") as head_probe:
            result = probe(url, vendor="mihoyo", game_id="bh3")
        head_probe.assert_not_called()
        self.assertTrue(result["available"])

    def test_successful_403_with_oss_archive_evidence_is_unavailable(self):
        cases = (
            ({"x-oss-storage-class": "Archive"}, b""),
            ({}, b"<?xml version='1.0'?><Error><Code>InvalidObjectState</Code></Error>"),
            (
                {"x-oss-storage-class": "Archive"},
                b"<?xml version='1.0'?><Error><Code>InvalidObjectState</Code></Error>",
            ),
        )
        urls = (
            ("https://ak.hycdn.cn/apk/202007081730-1150-token/game.apk", "hypergryph", "arknights", None),
            ("https://bundle.bh3.com/public/Android/archived.apk", "mihoyo", "bh3", None),
            ("https://bundle.bh3.com/ptpublic/rel/x/PC/BH3_v6.6.0_hash.7z", "mihoyo", "bh3", "windows"),
        )
        for headers, body in cases:
            for url, vendor, game_id, platform in urls:
                with self.subTest(headers=headers, body=bool(body), url=url), patch(
                    "probe_adapters.service.probe_url",
                    return_value=ProbeObservation(403, headers, url, body[:16], bytes_received=len(body), body=body),
                ):
                    result = probe(url, vendor=vendor, game_id=game_id, platform=platform)
                self.assertIs(result["available"], False)
                self.assertEqual(result["http_code"], 403)
                self.assertEqual(result["reason"], "oss_archive_not_restored")
                self.assertEqual(result["source_kind"], "official_storage_metadata")

    def test_archive_class_does_not_override_readable_200(self):
        url = "https://bundle.bh3.com/public/Android/readable.apk"
        body = b"PK\x03\x04" + b"x" * 12
        with patch(
            "probe_adapters.service.probe_url",
            return_value=ProbeObservation(
                200, {"x-oss-storage-class": "Archive"}, url, body,
                bytes_received=len(body), body=body,
            ),
        ):
            result = probe(url, vendor="mihoyo", game_id="bh3")
        self.assertIs(result["available"], True)

    def test_plain_403_is_unavailable_across_apk_and_pc_adapters(self):
        cases = (
            ("https://static.benghuai.com/Download/v9_7/game.apk", "mihoyo", "bh2", None),
            ("https://autopatchcn.yuanshen.com/game.apk", "mihoyo", "hk4e", None),
            ("https://bundle.bh3.com/public/Android/game.apk", "mihoyo", "bh3", None),
            ("https://ak.hycdn.cn/apk/202007081730-1150-token/game.apk", "hypergryph", "arknights", None),
            ("https://mirrors-package-mc.aki-game.com/client/download/token/game.apk", "kuro", "wuwa", None),
            ("https://autopatchcn.yuanshen.com/client/game.zip", "mihoyo", "hk4e", "windows"),
            ("https://bundle.bh3.com/ptpublic/rel/x/PC/BH3_v6.6.0_hash.7z", "mihoyo", "bh3", "windows"),
        )
        for url, vendor, game_id, platform in cases:
            for transport_error in (False, True):
                observation = ProbeObservation(403, {}, url, b"Forbidden", bytes_received=9, body=b"Forbidden")
                error = ProbeError("failed", returncode=56, status=403, final_url=url, prefix=b"Forbidden", body=b"Forbidden")
                with self.subTest(url=url, transport_error=transport_error), patch(
                    "probe_adapters.service.probe_url",
                    side_effect=error if transport_error else None,
                    return_value=observation,
                ), patch("probe_adapters.service.probe_head") as head_probe:
                    result = probe(url, vendor=vendor, game_id=game_id, platform=platform)
                head_probe.assert_not_called()
                self.assertIs(result["available"], False)
                self.assertEqual(result["http_code"], 403)
                self.assertEqual(result["reason"], "HTTP 403")
                self.assertEqual(result["source_kind"], "live_probe")
                self.assertEqual(result["transport_returncode"], 56 if transport_error else 0)

    def test_html_challenge_and_401_remain_unknown(self):
        cases = (
            ("https://static.benghuai.com/Download/v9_7/game.apk", 401, {}, b"Unauthorized", "mihoyo", "bh2"),
            (
                "https://mirrors-package-mc.aki-game.com/client/download/token/game.apk",
                200,
                {"content-type": "text/html", "error-info": "return by bot js challenge"},
                b"<script>challenge</script>",
                "kuro",
                "wuwa",
            ),
        )
        for url, status, headers, body, vendor, game_id in cases:
            with self.subTest(url=url), patch(
                "probe_adapters.service.probe_url",
                return_value=ProbeObservation(status, headers, url, body[:16], bytes_received=len(body), body=body),
            ):
                result = probe(url, vendor=vendor, game_id=game_id)
            self.assertIsNone(result["available"])
    def test_non_positive_timeout_is_rejected(self):
        for value in (0, -1, True, "10"):
            with self.subTest(value=value), patch("probe_adapters.service.probe_url") as run:
                with self.assertRaises(Exception):
                    probe("https://example.test/a.apk", timeout=value)
                run.assert_not_called()
    def test_dispatches_from_the_final_url_after_discovery_redirect(self) -> None:
        entry = "https://api-takumi.mihoyo.com/event/download_porter/link/ys_cn/official/android_default"
        final = "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk"
        with patch("probe_adapters.service.probe_url", return_value=(
            206,
            {"content-type": "application/vnd.android.package-archive"},
            final,
            b"PK\x03\x04",
        )):
            result = probe(entry, vendor="mihoyo", game_id="hk4e")
        self.assertEqual(result["adapter"], "mihoyo_autopatch")
        self.assertEqual(result["url"], final)

    def test_probes_apk_prefix_and_normalizes_metadata(self) -> None:
        with patch("probe_adapters.service.probe_url", return_value=(
            206,
            {
                "content-type": "application/vnd.android.package-archive",
                "content-range": "bytes 0-0/123",
                "etag": '"etag-value"',
                "last-modified": "Mon, 03 Aug 2026 09:25:07 GMT",
            },
            "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk",
            b"PK\x03\x04",
        )):
            result = probe(
                "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk",
                vendor="mihoyo",
                game_id="hk4e",
                timeout=1,
            )
        self.assertEqual(result["adapter"], "mihoyo_autopatch")
        self.assertIs(result["available"], True)
        self.assertEqual(result["size"], 123)
        self.assertEqual(result["etag"], "etag-value")
        self.assertEqual(result["file_time"], "2026-08-03T07:53:01Z")

    def test_403_404_and_410_are_definitely_unavailable(self) -> None:
        url = "https://static.benghuai.com/Download/v9_7/game.apk"
        for status in (403, 404, 410):
            with self.subTest(status=status), patch("probe_adapters.service.probe_url", return_value=(status, {}, url, b"")):
                self.assertIs(probe(url, vendor="mihoyo", game_id="bh2")["available"], False)

    def test_mihoyo_autopatch_rejects_a_successful_plain_text_placeholder(self) -> None:
        url = "https://autopatchcn.bhsr.com/client/cn/token/gw_An/StarRail_1.5.0.apk"
        with patch("probe_adapters.service.probe_url", return_value=(
            206,
            {"content-type": "text/plain", "content-range": "bytes 0-2/3"},
            url,
            b">.<",
        )):
            result = probe(url, vendor="mihoyo", game_id="hkrpg")

        self.assertEqual(result["size"], 3)
        self.assertIs(result["available"], False)

    def test_current_projection_ignores_non_probe_fields(self):
        identity = {"vendor": "mihoyo", "game_id": "hk4e", "platform": "android"}
        current = current_from_result(identity, "https://example.test/old.apk", {
            "url": "https://example.test/final.apk", "size": 123,
            "etag": "etag", "crc64": "crc", "md5": "md5",
            "http_code": 206, "available": True, "checked_at": "2026-08-24T00:00:00Z",
            "file_time": "2026-08-03T00:00:00Z", "reason": "ignored", "confidence": "ignored",
        })
        self.assertEqual(current, {
            "state": "available", "response_size": 123,
            "etag": "etag", "crc64": "crc", "http_code": 206,
            "checked_at": "2026-08-24T00:00:00Z", "final_url": "https://example.test/final.apk",
        })

    def test_current_projection_preserves_inputs_and_prefers_observed_size(self):
        identity = {"vendor": "mihoyo", "game_id": "hk4e", "platform": "android"}
        target = "https://example.test/old.apk"
        result = {"url": target, "available": True, "observed_size": 9, "size": 8}
        original = deepcopy(result)
        current = current_from_result(identity, target, result)
        self.assertEqual(current, {"state": "available", "response_size": 9})
        self.assertEqual(result, original)

    def test_current_projection_falls_back_to_size_when_observed_size_is_none(self):
        current = current_from_result({"platform": "android"}, "https://example.test/old.apk", {
            "available": True, "observed_size": None, "size": 8,
        })
        self.assertEqual(current["response_size"], 8)

    def test_current_projection_rejects_invalid_boundary_inputs(self):
        for identity, target, result in (
            ({"platform": "legacy"}, "https://example.test/a.apk", {}),
            ({"platform": "android"}, "", {}),
            ({"platform": "android"}, "https://example.test/a.apk", None),
        ):
            with self.subTest(identity=identity, target=target, result=result):
                with self.assertRaises(ProbeError):
                    current_from_result(identity, target, result)


if __name__ == "__main__":
    unittest.main()
