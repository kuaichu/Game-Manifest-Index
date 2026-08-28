import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from backend.schema_v2 import validate_v2_record
from url_adapters.android import hypergryph_launcher_latest, kuro_pns_manifest, kuro_wuwa_mc_manifest, perfectworld_webops
from url_adapters.android.hypergryph_apk_organizer import HypergryphApkCollection, organize_hypergryph_apk
from url_adapters.android.kuro_apk_organizer import KuroApkCollection, organize_kuro_apk
from url_adapters.android.perfectworld_apk_organizer import PerfectWorldApkCollection, organize_perfectworld_apk


MODULES = (
    (kuro_wuwa_mc_manifest, "wuwa", "kuro", KuroApkCollection, organize_kuro_apk),
    (kuro_pns_manifest, "pns", "kuro", KuroApkCollection, organize_kuro_apk),
    (hypergryph_launcher_latest, "arknights", "hypergryph", HypergryphApkCollection, organize_hypergryph_apk),
    (perfectworld_webops, "nte", "perfectworld", PerfectWorldApkCollection, organize_perfectworld_apk),
)


def collected_record(game_id: str, vendor: str, *, url: str | None = None) -> dict:
    return {
        "vendor": vendor,
        "game_id": game_id,
        "platform": "android",
        "channel": "official",
        "version": "1.2.3",
        "version_code": 123,
        "filename": f"{game_id}_1.2.3.apk",
        "url": url or f"https://cdn.example.test/{game_id}_1.2.3.apk",
        "size": 123,
        "checksum": {"etag": "etag", "crc64": "crc", "md5": "a" * 32},
        "file_time": None,
        "status": {"http_code": 206, "available": True, "last_checked_at": "2026-08-27T00:00:00Z"},
    }


class NonMihoyoApkPipelineTests(unittest.TestCase):
    def test_organizers_emit_strict_v2_records(self) -> None:
        for module, game_id, vendor, collection_type, organizer in MODULES:
            with self.subTest(game_id=game_id):
                collection = collection_type(
                    f"https://official.example.test/{game_id}",
                    collected_record(game_id, vendor),
                )
                output = organizer(collection)
                validate_v2_record(output)
                self.assertEqual(output["schema_version"], 2)
                self.assertEqual(output["provenance"]["source_kind"], "official_sync")
                self.assertEqual(output["artifacts"][0]["urls"][0]["provider"], vendor)

    def test_collect_only_reads_official_sources_and_does_not_write(self) -> None:
        cases = (
            (kuro_wuwa_mc_manifest, "wuwa", '{"version":"1.2.3","primary":"https://cdn.example/wuwa.apk"}', {}),
            (kuro_pns_manifest, "pns", '{"version":"1.2.3","primary":"https://cdn.example/pns.apk"}', {}),
            (hypergryph_launcher_latest, "arknights", None, {}),
            (perfectworld_webops, "nte", 'var yh_download_json = {"android":"https://yhapk.wmupd.com/nte.apk"};', {"remote_apk_version": ("1.2.3", 123)}),
        )
        for module, game_id, body, extras in cases:
            with self.subTest(game_id=game_id), tempfile.TemporaryDirectory() as directory:
                record = collected_record(game_id, next(v for _, g, v, _, _ in MODULES if g == game_id))
                patches = [
                    patch.object(module, "endpoint", return_value=f"https://official.example/{game_id}"),
                    patch.object(module, "fetch_record", return_value=record),
                ]
                if body is not None:
                    patches.append(patch.object(module, "read_small", return_value=body))
                if "remote_apk_version" in extras:
                    patches.append(patch.object(module, "remote_apk_version", return_value=extras["remote_apk_version"]))
                with ExitStack() as stack:
                    for item in patches:
                        stack.enter_context(item)
                    collection = module.collect(game_id, 3)
                self.assertEqual(collection.record["game_id"], game_id)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_discover_passes_canonical_record_to_shared_persistence(self) -> None:
        for module, game_id, vendor, collection_type, _ in MODULES:
            with self.subTest(game_id=game_id):
                collection = collection_type(
                    f"https://official.example.test/{game_id}",
                    collected_record(game_id, vendor),
                )
                expected = Path(f"{game_id}.json")
                with patch.object(module, "collect", return_value=collection), patch.object(
                    module, "persist_v2_record", return_value=expected,
                ) as persist:
                    self.assertEqual(module.discover(game_id, Path("unused"), 3), expected)
                record, root = persist.call_args.args
                validate_v2_record(record)
                self.assertEqual(root, Path("unused"))

    def test_legacy_is_not_overwritten_and_v2_refresh_keeps_visibility(self) -> None:
        module = kuro_wuwa_mc_manifest
        collection = KuroApkCollection(
            "https://official.example.test/wuwa",
            collected_record("wuwa", "kuro"),
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "collect", return_value=collection):
            target = Path(directory) / "kuro/wuwa/android/1.2.3.json"
            target.parent.mkdir(parents=True)
            legacy = collection.record
            raw = json.dumps(legacy, ensure_ascii=False, indent=2) + "\n"
            target.write_text(raw, encoding="utf-8")
            self.assertEqual(module.discover("wuwa", Path(directory), 3), target)
            self.assertEqual(target.read_text(encoding="utf-8"), raw)

            old = organize_kuro_apk(collection)
            old["is_visible"] = False
            target.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            refreshed = KuroApkCollection(
                collection.source_url,
                collected_record("wuwa", "kuro", url="https://cdn.example.test/wuwa-refreshed.apk"),
            )
            with patch.object(module, "collect", return_value=refreshed):
                stored = json.loads(module.discover("wuwa", Path(directory), 3).read_text(encoding="utf-8"))
            validate_v2_record(stored)
            self.assertFalse(stored["is_visible"])
            self.assertEqual(stored["artifacts"][0]["urls"][0]["url"], refreshed.record["url"])

    def test_hypergryph_entry_uses_final_url_platform_inference(self) -> None:
        record = collected_record("arknights", "hypergryph")
        with patch.object(hypergryph_launcher_latest, "endpoint", return_value="https://launcher.example/latest"), patch.object(
            hypergryph_launcher_latest, "fetch_record", return_value=record,
        ) as fetch:
            hypergryph_launcher_latest.collect("arknights", 3)
        self.assertIsNone(fetch.call_args.kwargs["platform"])

if __name__ == "__main__":
    unittest.main()
