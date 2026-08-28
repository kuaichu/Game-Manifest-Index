import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from backend.schema_v2 import validate_v2_record
from url_adapters.common import AdapterError
from url_adapters.pc import mihoyo_game_packages
from url_adapters.pc.mihoyo_package_organizer import (
    GAME_IDENTITIES,
    MihoyoPackageCollection,
    MihoyoPackageOrganizationError,
    organize_packages,
    package_source_url,
)


def package(name, marker="a", *, size=12, decompressed_size=20, language=None):
    value = {
        "url": f"https://autopatchcn.example.test/client/{name}",
        "md5": marker * 32,
        "size": size,
        "decompressed_size": decompressed_size,
    }
    if language is not None:
        value["language"] = language
    return value


def payload(game_id="hk4e", game_packages=None):
    hoyoplay_id, biz = GAME_IDENTITIES[game_id]
    return {
        "retcode": 0,
        "message": "OK",
        "data": {
            "game_packages": [{
                "game": {"id": hoyoplay_id, "biz": biz},
                "main": {
                    "major": {
                        "version": "5.5.0",
                        "game_pkgs": game_packages if game_packages is not None else [
                            package("YuanShen_5.5.0.zip.001", "a"),
                            package("YuanShen_5.5.0.zip.002", "b"),
                        ],
                        "audio_pkgs": [package("Audio_Chinese.zip", "c", language="zh-cn")],
                        "res_list_url": "https://official.example.test/res_list",
                    },
                    "patches": [{
                        "version": "5.4.0",
                        "game_pkgs": [package("patch.zip", "d")],
                        "audio_pkgs": [],
                    }],
                },
                "pre_download": {"major": {"game_pkgs": [package("future.zip", "e")]}},
            }]
        },
    }


def collection(game_id="hk4e", body=None):
    hoyoplay_id, _ = GAME_IDENTITIES[game_id]
    return MihoyoPackageCollection(
        game_id=game_id,
        hoyoplay_game_id=hoyoplay_id,
        source_url=package_source_url(game_id),
        payload=body or payload(game_id),
    )


class MihoyoPackageOrganizerTests(unittest.TestCase):
    def test_cn_source_matrix_uses_official_endpoint(self):
        expected_ids = {
            "hk4e": "1Z8W5NHUQb",
            "hkrpg": "64kMb5iAWu",
            "nap": "x6znKlJ0xK",
            "bh3": "osvnlOc0S8",
        }
        for game_id, hoyoplay_id in expected_ids.items():
            with self.subTest(game_id=game_id):
                parsed = urlsplit(package_source_url(game_id))
                self.assertEqual((parsed.scheme, parsed.netloc), ("https", "hyp-api.mihoyo.com"))
                self.assertEqual(
                    parse_qs(parsed.query),
                    {"launcher_id": ["jGHBHlcOq1"], "game_ids[]": [hoyoplay_id]},
                )

    def test_only_main_major_game_packages_become_segments(self):
        record = organize_packages(collection())
        validate_v2_record(record)
        self.assertEqual(record["platform"], "windows")
        self.assertEqual(record["provenance"]["source_kind"], "official_sync")
        self.assertEqual(len(record["artifacts"]), 2)
        self.assertEqual([item["part"] for item in record["artifacts"]], [1, 2])
        self.assertEqual({item["package_type"] for item in record["artifacts"]}, {"segment"})
        self.assertNotIn("Audio_Chinese.zip", {item["name"] for item in record["artifacts"]})
        self.assertNotIn("patch.zip", {item["name"] for item in record["artifacts"]})
        self.assertNotIn("future.zip", {item["name"] for item in record["artifacts"]})

    def test_part_comes_from_basename_not_array_position(self):
        body = payload(game_packages=[
            package("YuanShen_5.5.0.zip.002", "b"),
            package("YuanShen_5.5.0.zip.001", "a"),
        ])
        record = organize_packages(collection(body=body))
        self.assertEqual([item["part"] for item in record["artifacts"]], [2, 1])

    def test_full_and_segments_are_both_preserved(self):
        body = payload(game_packages=[
            package("YuanShen_5.5.0.zip", "c"),
            package("YuanShen_5.5.0.zip.001", "a"),
            package("YuanShen_5.5.0.zip.002", "b"),
        ])
        record = organize_packages(collection(body=body))
        self.assertEqual(
            [(item["package_type"], item.get("part")) for item in record["artifacts"]],
            [("full", None), ("segment", 1), ("segment", 2)],
        )

    def test_single_bh3_archive_is_full(self):
        body = payload("bh3", [package("BH3_v8.4.0_589030804b01.7z")])
        record = organize_packages(collection("bh3", body))
        self.assertEqual(record["artifacts"][0]["package_type"], "full")
        self.assertNotIn("part", record["artifacts"][0])

    def test_decimal_string_sizes_are_normalized_to_integers(self):
        body = payload(game_packages=[package(
            "YuanShen_5.5.0.zip.001", size="10737418240", decompressed_size="21485322240"
        )])
        record = organize_packages(collection(body=body))
        artifact = record["artifacts"][0]
        self.assertEqual(artifact["size"], 10737418240)
        self.assertEqual(artifact["decompressed_size"], 21485322240)

    def test_artifact_id_ignores_url_size_and_checksum(self):
        first = organize_packages(collection())
        changed_body = payload()
        changed_body["data"]["game_packages"][0]["main"]["major"]["game_pkgs"][0].update({
            "url": "https://another.example.test/YuanShen_5.5.0.zip.001",
            "md5": "f" * 32,
            "size": 99,
        })
        second = organize_packages(collection(body=changed_body))
        self.assertEqual(first["artifacts"][0]["artifact_id"], second["artifacts"][0]["artifact_id"])

    def test_non_contiguous_segments_are_rejected(self):
        body = payload(game_packages=[
            package("YuanShen_5.5.0.zip.001"),
            package("YuanShen_5.5.0.zip.003", "b"),
        ])
        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "从 1 开始且连续"):
            organize_packages(collection(body=body))

    def test_wrong_business_identity_and_external_source_are_rejected(self):
        wrong_biz = payload()
        wrong_biz["data"]["game_packages"][0]["game"]["biz"] = "hk4e_global"
        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "唯一匹配"):
            organize_packages(collection(body=wrong_biz))
        external = collection()
        external = MihoyoPackageCollection(
            external.game_id, external.hoyoplay_game_id,
            "https://third-party.example.test/getGamePackages", external.payload,
        )
        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "官方"):
            organize_packages(external)


class MihoyoPackageCollectorTests(unittest.TestCase):
    def test_collect_uses_bounded_reader_and_parses_object(self):
        body = payload()
        with patch.object(mihoyo_game_packages, "read_small", return_value=json.dumps(body)) as reader:
            result = mihoyo_game_packages.collect("hk4e", 7)
        reader.assert_called_once_with(package_source_url("hk4e"), 7)
        self.assertEqual(result.payload, body)

    def test_collect_rejects_invalid_timeout_and_json(self):
        for timeout in (0, -1, True):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(AdapterError, "正整数"):
                mihoyo_game_packages.collect("hk4e", timeout)
        with patch.object(mihoyo_game_packages, "read_small", return_value="not-json"):
            with self.assertRaisesRegex(AdapterError, "无效 JSON"):
                mihoyo_game_packages.collect("hk4e", 3)

    def test_discover_collection_persists_v2_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = mihoyo_game_packages.discover_collection(collection(), Path(directory))
            self.assertEqual(path.parts[-4:], ("mihoyo", "hk4e", "pc", "5.5.0.json"))
            record = json.loads(path.read_text(encoding="utf-8"))
            validate_v2_record(record)

    def test_organizer_failure_is_wrapped_with_cause(self):
        expected = MihoyoPackageOrganizationError("bad package response")
        with patch.object(mihoyo_game_packages, "organize_complete", side_effect=expected):
            with self.assertRaises(AdapterError) as raised:
                mihoyo_game_packages.discover_collection(collection(), Path("unused"))
        self.assertIs(raised.exception.__cause__, expected)


if __name__ == "__main__":
    unittest.main()
