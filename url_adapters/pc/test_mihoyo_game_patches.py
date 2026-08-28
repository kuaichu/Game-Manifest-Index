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
    organize_packages,
    organize_packages_and_patches,
    package_source_url,
)


def package(name, marker="a", *, size="12", decompressed_size="20", language=None):
    value = {
        "url": f"https://autopatchcn.example.test/client/{name}",
        "md5": marker * 32,
        "size": size,
        "decompressed_size": decompressed_size,
    }
    if language is not None:
        value["language"] = language
    return value


def collection(patches, *, game_id="hk4e"):
    hoyoplay_id, biz = GAME_IDENTITIES[game_id]
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
                        "audio_pkgs": [package("Audio_Chinese.zip", "c", language="zh-cn")],
                    },
                    "patches": [
                        {**patch, "audio_pkgs": patch.get("audio_pkgs", [])}
                        if isinstance(patch, dict) else patch
                        for patch in patches
                    ] if isinstance(patches, list) else patches,
                },
                "pre_download": {"major": {"game_pkgs": [package("future.zip", "d")]}},
            }]},
        },
    )


class MihoyoGamePatchTests(unittest.TestCase):
    def test_combined_record_preserves_package_and_maps_routes(self):
        source = collection([
            {"version": "5.4.0", "game_pkgs": [package("game_5.4.0_5.5.0_hdiff_a.zip", "b")]},
            {"version": "5.3.0", "game_pkgs": [package("game_5.3.0_5.5.0_hdiff_b.7z", "e")]},
        ])
        package_only = organize_packages(source)
        combined = organize_packages_and_patches(source)
        validate_v2_record(combined)

        self.assertEqual([item["kind"] for item in package_only["artifacts"]], ["package"])
        self.assertEqual([item["kind"] for item in combined["artifacts"]], ["package", "patch", "patch"])
        self.assertEqual(
            [(item["route_from"], item["route_to"]) for item in combined["artifacts"][1:]],
            [("5.4.0", "5.5.0"), ("5.3.0", "5.5.0")],
        )
        self.assertNotIn("Audio_Chinese.zip", {item["name"] for item in combined["artifacts"]})
        self.assertNotIn("future.zip", {item["name"] for item in combined["artifacts"]})

    def test_multi_file_route_creates_independent_patches_without_part(self):
        combined = organize_packages_and_patches(collection([{
            "version": "5.4.0",
            "game_pkgs": [
                package("game_5.4.0_5.5.0_a.zip", "a"),
                package("game_5.4.0_5.5.0_b.zip.001", "b"),
            ],
        }]))
        patches = [item for item in combined["artifacts"] if item["kind"] == "patch"]
        self.assertEqual(len(patches), 2)
        self.assertTrue(all(item["package_type"] == "differential" for item in patches))
        self.assertTrue(all("part" not in item for item in patches))
        self.assertEqual(len({item["artifact_id"] for item in patches}), 2)

    def test_patch_artifact_id_is_stable_for_transport_metadata(self):
        first_source = collection([{
            "version": "5.4.0",
            "game_pkgs": [package("game_5.4.0_5.5.0_hdiff.zip")],
        }])
        changed_source = collection([{
            "version": "5.4.0",
            "game_pkgs": [{
                **package("game_5.4.0_5.5.0_hdiff.zip", "f", size="99"),
                "url": "https://another.example.test/game_5.4.0_5.5.0_hdiff.zip",
            }],
        }])
        first = organize_packages_and_patches(first_source)["artifacts"][1]
        changed = organize_packages_and_patches(changed_source)["artifacts"][1]
        self.assertEqual(first["artifact_id"], changed["artifact_id"])

        changed_route = organize_packages_and_patches(collection([{
            "version": "5.3.0",
            "game_pkgs": [package("game_5.4.0_5.5.0_hdiff.zip")],
        }]))["artifacts"][1]
        self.assertNotEqual(first["artifact_id"], changed_route["artifact_id"])

    def test_empty_patch_list_keeps_package_record_valid(self):
        combined = organize_packages_and_patches(collection([]))
        validate_v2_record(combined)
        self.assertEqual([item["kind"] for item in combined["artifacts"]], ["package"])

    def test_invalid_route_shape_and_duplicate_name_are_rejected(self):
        invalid_cases = [
            ([{"version": "", "game_pkgs": []}], "非空字符串"),
            ([{"version": "5.5.0", "game_pkgs": []}], "目标版本相同"),
            ([{"version": "5.4.0", "game_pkgs": None}], "必须是数组"),
            (None, "main.patches 必须是数组"),
        ]
        for patches, message in invalid_cases:
            with self.subTest(message=message), self.assertRaisesRegex(MihoyoPackageOrganizationError, message):
                organize_packages_and_patches(collection(patches))

        duplicate = [{
            "version": "5.4.0",
            "game_pkgs": [
                package("same.zip", "a"),
                package("same.zip", "b"),
            ],
        }]
        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "文件名重复"):
            organize_packages_and_patches(collection(duplicate))

        invalid_package = [{
            "version": "5.4.0",
            "game_pkgs": [{**package("patch.zip"), "md5": "not-md5"}],
        }]
        with self.assertRaisesRegex(MihoyoPackageOrganizationError, "32 位十六进制"):
            organize_packages_and_patches(collection(invalid_package))

    def test_discovery_persists_combined_record_without_losing_packages(self):
        source = collection([{
            "version": "5.4.0",
            "game_pkgs": [package("game_5.4.0_5.5.0_hdiff.zip")],
        }])
        with tempfile.TemporaryDirectory() as directory:
            path = mihoyo_game_packages.discover_collection(source, Path(directory))
            record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({item["kind"] for item in record["artifacts"]}, {"package", "patch"})


if __name__ == "__main__":
    unittest.main()
