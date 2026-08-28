import unittest

from url_adapters.android.mihoyo_bh2_download_page import version_from_filename


class Bh2VersionTests(unittest.TestCase):
    def test_uses_the_game_version_before_the_build_number(self) -> None:
        self.assertEqual(
            version_from_filename("Original.StripResource_9.7.8_310_4ij.shell.apk"),
            "9.7.8",
        )
        self.assertEqual(
            version_from_filename("Original.StripResource_9.8.8_311_32va.shell.apk"),
            "9.8.8",
        )

    def test_returns_none_for_unrelated_names(self) -> None:
        self.assertIsNone(version_from_filename("bh2_android.apk"))


if __name__ == "__main__":
    unittest.main()
