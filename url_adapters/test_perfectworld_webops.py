import unittest
from pathlib import Path
from unittest.mock import patch

from url_adapters.android.perfectworld_webops import dated_version, discover


class PerfectWorldVersionTests(unittest.TestCase):
    def test_uses_the_date_token_from_the_apk_filename(self) -> None:
        self.assertEqual(dated_version("ht_QRSL-20240711.apk"), "20240711")
        self.assertEqual(dated_version("p5x_1_official_20240701.apk"), "20240701")
        self.assertEqual(dated_version("yh_gw_20260423.apk"), "20260423")

    def test_nte_discovery_uses_the_main_apk_manifest_version(self) -> None:
        url = "https://yhapk.wmupd.com/webops/yh/yh_gw_20260813.apk"
        body = f'var yh_download_json = {{"android":"{url}"}};'
        record = {"game_id": "nte", "version": "1.3.0"}
        with (
            patch("url_adapters.android.perfectworld_webops.read_small", return_value=body),
            patch(
                "url_adapters.android.perfectworld_webops.remote_apk_version",
                return_value=("1.3.0", 130),
            ) as manifest,
            patch("url_adapters.android.perfectworld_webops.fetch_record", return_value=record) as fetch,
            patch("url_adapters.android.perfectworld_webops.discover_collection", return_value=Path("1.3.0.json")),
        ):
            path = discover("nte", Path("data"), timeout=9)

        self.assertEqual(path.name, "1.3.0.json")
        manifest.assert_called_once_with(
            url, 9, expected_package="com.hottagames.yh.laohu",
        )
        self.assertEqual(fetch.call_args.kwargs["version"], "1.3.0")
        self.assertEqual(fetch.call_args.kwargs["version_code"], 130)

    def test_tof_discovery_uses_the_main_apk_manifest_version(self) -> None:
        url = "https://htapk.wmupd.com/webops/ht/ht_QRSL-20240711.apk"
        body = f'var ht_download_json = {{"android":"{url}"}};'
        record = {"game_id": "tof", "version": "4.2.670.136938"}
        with (
            patch("url_adapters.android.perfectworld_webops.read_small", return_value=body),
            patch(
                "url_adapters.android.perfectworld_webops.remote_apk_version",
                return_value=("4.2.670.136938", 670),
            ) as manifest,
            patch("url_adapters.android.perfectworld_webops.fetch_record", return_value=record) as fetch,
            patch(
                "url_adapters.android.perfectworld_webops.discover_collection",
                return_value=Path("4.2.670.136938.json"),
            ),
        ):
            path = discover("tof", Path("data"), timeout=9)

        self.assertEqual(path.name, "4.2.670.136938.json")
        manifest.assert_called_once_with(
            url, 9, expected_package="com.pwrd.hotta.laohu",
        )
        self.assertEqual(fetch.call_args.kwargs["version"], "4.2.670.136938")
        self.assertEqual(fetch.call_args.kwargs["version_code"], 670)

    def test_p5x_discovery_uses_the_main_apk_manifest_version(self) -> None:
        url = "https://p5xapk.wmupd.com/webops/p5x/p5x_1_official_20260621.apk"
        body = f'var p5x_download_json = {{"android":"{url}"}};'
        record = {"game_id": "p5x", "version": "1.5.4"}
        with (
            patch("url_adapters.android.perfectworld_webops.read_small", return_value=body),
            patch(
                "url_adapters.android.perfectworld_webops.remote_apk_version",
                return_value=("1.5.4", 291),
            ) as manifest,
            patch("url_adapters.android.perfectworld_webops.fetch_record", return_value=record) as fetch,
            patch("url_adapters.android.perfectworld_webops.discover_collection", return_value=Path("1.5.4.json")),
        ):
            path = discover("p5x", Path("data"), timeout=9)

        self.assertEqual(path.name, "1.5.4.json")
        manifest.assert_called_once_with(
            url, 9, expected_package="com.pwrd.persona5x.laohu",
        )
        self.assertEqual(fetch.call_args.kwargs["version"], "1.5.4")
        self.assertEqual(fetch.call_args.kwargs["version_code"], 291)


if __name__ == "__main__":
    unittest.main()
