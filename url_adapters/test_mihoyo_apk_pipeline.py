import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import validate_v2_record
from url_adapters.android.mihoyo_apk_organizer import (
    MihoyoApkCollection,
    MihoyoApkOrganizationError,
    organize_apk,
)
from url_adapters.android import mihoyo_download_porter


def record(game_id="hk4e"):
    return {"vendor": "mihoyo", "game_id": game_id, "platform": "android", "channel": "official",
            "version": "7.0.0", "version_code": 700, "filename": "game_7.0.0.apk",
            "url": "https://cdn.example.test/game_7.0.0.apk", "size": 12,
            "checksum": {"etag": "e", "crc64": "c", "md5": "a" * 32}, "file_time": None,
            "status": {"http_code": 206, "available": True, "last_checked_at": "2026-08-27T00:00:00Z"}}


class MihoyoPipelineTests(unittest.TestCase):
    def test_organizer_emits_canonical_official_record(self):
        output = organize_apk(MihoyoApkCollection("https://official.example.test/hk4e", record()))
        validate_v2_record(output)
        self.assertEqual(output["provenance"]["source_kind"], "official_sync")
        self.assertEqual(output["artifacts"][0]["urls"][0]["provider"], "mihoyo")

    def test_discover_persists_v2_record(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            mihoyo_download_porter, "fetch_record", return_value=record()
        ), patch.object(mihoyo_download_porter, "endpoint", return_value="https://official.example/hk4e"):
            path = mihoyo_download_porter.discover("hk4e", Path(directory), 3)
            self.assertTrue(path.exists())
            validate_v2_record(__import__("json").loads(path.read_text(encoding="utf-8")))

    def test_organizer_failure_is_wrapped_with_cause(self):
        expected = MihoyoApkOrganizationError("bad collection")
        with patch.object(mihoyo_download_porter, "organize_apk", side_effect=expected):
            with self.assertRaises(mihoyo_download_porter.AdapterError) as raised:
                mihoyo_download_porter.discover_collection(object(), Path("unused"))
        self.assertIs(raised.exception.__cause__, expected)


if __name__ == "__main__":
    unittest.main()
