import json
import tempfile
import unittest
from pathlib import Path

from backend.schema_v2 import validate_v2_record
from url_adapters.pc import mihoyo_game_packages
from url_adapters.pc.mihoyo_package_organizer import (
    GAME_IDENTITIES,
    MihoyoPackageCollection,
    MihoyoPackageOrganizationError,
    organize_complete,
    organize_packages_and_patches,
    package_source_url,
)


def package(name, marker="a", *, language=None, size="12", decompressed_size="20"):
    value = {
        "url": f"https://autopatchcn.example.test/client/{name}",
        "md5": marker * 32,
        "size": size,
        "decompressed_size": decompressed_size,
    }
    if language is not None:
        value["language"] = language
    return value


def collection(major_audio, patch_audio=None, *, game_id="hk4e"):
    hoyoplay_id, biz = GAME_IDENTITIES[game_id]
    patches = [] if patch_audio is None else [{
        "version": "5.4.0",
        "game_pkgs": [package("game_5.4.0_5.5.0_hdiff.zip")],
        "audio_pkgs": patch_audio,
    }]
    return MihoyoPackageCollection(
        game_id=game_id,
        hoyoplay_game_id=hoyoplay_id,
        source_url=package_source_url(game_id),
        payload={
            "retcode": 0,
            "data": {"game_packages": [{
                "game": {"id": hoyoplay_id, "biz": biz},
                "main": {
                    "major": {
                        "version": "5.5.0",
                        "game_pkgs": [package("YuanShen_5.5.0.zip.001")],
                        "audio_pkgs": major_audio,
                    },
                    "patches": patches,
                },
                "pre_download": {"major": {"audio_pkgs": [
                    package("future_voice.zip", language="zh-cn")
                ]}},
            }]},
        },
    )


class MihoyoVoiceTests(unittest.TestCase):
    def test_complete_record_appends_four_official_voice_languages(self):
        source = collection([
            package("Audio_Chinese_5.5.0.zip", "a", language="zh-cn"),
            package("Audio_English_5.5.0.zip", "b", language="en-us"),
            package("Audio_Japanese_5.5.0.zip", "c", language="ja-jp"),
            package("Audio_Korean_5.5.0.zip", "d", language="ko-kr"),
        ])
        game_only = organize_packages_and_patches(source)
        complete = organize_complete(source)
        validate_v2_record(complete)

        self.assertTrue(all(item["component"] == "game" for item in game_only["artifacts"]))
        voices = [item for item in complete["artifacts"] if item["component"] == "voice"]
        self.assertEqual([item["language"] for item in voices], ["zh-cn", "en-us", "ja-jp", "ko-kr"])
        self.assertTrue(all(item["kind"] == "package" and item["package_type"] == "optional" for item in voices))
        self.assertNotIn("future_voice.zip", {item["name"] for item in complete["artifacts"]})

    def test_voice_patch_uses_language_and_routes_without_part(self):
        source = collection(
            [package("Chinese.7z", language="zh-cn")],
            [
                package("audio_zh-cn_5.4.0_5.5.0_hdiff_a.7z", "b", language="zh-cn"),
                package("audio_en-us_5.4.0_5.5.0_hdiff_b.7z.001", "c", language="en-us"),
            ],
        )
        complete = organize_complete(source)
        patches = [item for item in complete["artifacts"] if item["component"] == "voice" and item["kind"] == "patch"]
        self.assertEqual(len(patches), 2)
        self.assertEqual({(item["route_from"], item["route_to"]) for item in patches}, {("5.4.0", "5.5.0")})
        self.assertEqual({item["language"] for item in patches}, {"zh-cn", "en-us"})
        self.assertTrue(all("part" not in item for item in patches))

    def test_voice_segments_use_basename_parts_and_require_continuity(self):
        complete = organize_complete(collection([
            package("Chinese.zip.002", "b", language="zh-cn"),
            package("Chinese.zip.001", "a", language="zh-cn"),
        ]))
        voices = [item for item in complete["artifacts"] if item["component"] == "voice"]
        self.assertEqual([(item["package_type"], item["part"]) for item in voices], [
            ("segment", 2), ("segment", 1)
        ])

        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "从 1 开始且连续"):
            organize_complete(collection([
                package("Chinese.zip.001", "a", language="zh-cn"),
                package("Chinese.zip.003", "c", language="zh-cn"),
            ]))

    def test_unknown_language_and_duplicate_voice_identity_are_rejected(self):
        for language in ("fr-fr", ["zh-cn"]):
            with self.subTest(language=language), self.assertRaisesRegex(
                MihoyoPackageOrganizationError, "官方语音语言"
            ):
                organize_complete(collection([package("Unknown.zip", language=language)]))

        duplicate = [
            package("Chinese.zip", "a", language="zh-cn"),
            package("Chinese.zip", "b", language="zh-cn"),
        ]
        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "文件名重复"):
            organize_complete(collection(duplicate))

    def test_empty_voice_arrays_keep_game_record_valid(self):
        complete = organize_complete(collection([]))
        validate_v2_record(complete)
        self.assertTrue(all(item["component"] == "game" for item in complete["artifacts"]))

    def test_voice_only_patch_route_does_not_require_game_package(self):
        source = collection(
            [],
            [package("audio_zh-cn_patch.zip", language="zh-cn")],
        )
        source.payload["data"]["game_packages"][0]["main"]["patches"][0]["game_pkgs"] = []
        complete = organize_complete(source)
        patches = [item for item in complete["artifacts"] if item["kind"] == "patch"]
        self.assertEqual([(item["component"], item["language"]) for item in patches], [("voice", "zh-cn")])

    def test_voice_artifact_id_is_stable_for_transport_metadata(self):
        first = organize_complete(collection([
            package("Chinese.zip", "a", language="zh-cn")
        ]))["artifacts"][-1]
        changed_package = package("Chinese.zip", "f", language="zh-cn", size="99")
        changed_package["url"] = "https://another.example.test/Chinese.zip"
        changed = organize_complete(collection([changed_package]))["artifacts"][-1]
        self.assertEqual(first["artifact_id"], changed["artifact_id"])

    def test_discovery_persists_all_components_atomically(self):
        source = collection(
            [package("Chinese.zip", language="zh-cn")],
            [package("audio_zh-cn_patch.zip", "b", language="zh-cn")],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = mihoyo_game_packages.discover_collection(source, Path(directory))
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            {(item["component"], item["kind"]) for item in record["artifacts"]},
            {("game", "package"), ("game", "patch"), ("voice", "package"), ("voice", "patch")},
        )


if __name__ == "__main__":
    unittest.main()
