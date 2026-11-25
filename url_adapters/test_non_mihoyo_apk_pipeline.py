import ast
from collections.abc import Mapping
from contextlib import ExitStack
from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit

from backend.schema_v2 import artifact_id, normalize_legacy_record, validate_v2_record
from url_adapters.android import hypergryph_launcher_latest, kuro_pns_manifest, kuro_wuwa_mc_manifest, perfectworld_webops
from url_adapters.android.hypergryph_apk_organizer import (
    HypergryphApkCollection,
    HypergryphApkOrganizationError,
    organize_hypergryph_apk,
)
from url_adapters.android.kuro_apk_organizer import (
    KuroApkCollection,
    KuroApkOrganizationError,
    organize_kuro_apk,
)
from url_adapters.android.mihoyo_apk_organizer import MihoyoApkCollection, organize_apk
from url_adapters.android.perfectworld_apk_organizer import (
    PerfectWorldApkCollection,
    PerfectWorldApkOrganizationError,
    organize_perfectworld_apk,
)


MODULES = (
    (kuro_wuwa_mc_manifest, "wuwa", "kuro", KuroApkCollection, organize_kuro_apk),
    (kuro_pns_manifest, "pns", "kuro", KuroApkCollection, organize_kuro_apk),
    (hypergryph_launcher_latest, "arknights", "hypergryph", HypergryphApkCollection, organize_hypergryph_apk),
    (perfectworld_webops, "nte", "perfectworld", PerfectWorldApkCollection, organize_perfectworld_apk),
)

SIGNED_ENDFIELD_URL = (
    "https://beyond.hycdn.cn/6LL0KJuqHBVz33WK/1.4/package/1/1/Android/"
    "1.4.3_N3kXcstgi31V2hpt/endfield-hg-1-1.4.3.apk?auth_key=expired"
)

ALL_TWELVE_GAME_CASES = (
    ("hk4e", "mihoyo", MihoyoApkCollection, organize_apk, None),
    ("hkrpg", "mihoyo", MihoyoApkCollection, organize_apk, None),
    ("nap", "mihoyo", MihoyoApkCollection, organize_apk, None),
    ("bh3", "mihoyo", MihoyoApkCollection, organize_apk, None),
    ("bh2", "mihoyo", MihoyoApkCollection, organize_apk, None),
    ("arknights", "hypergryph", HypergryphApkCollection, organize_hypergryph_apk, None),
    ("endfield", "hypergryph", HypergryphApkCollection, organize_hypergryph_apk, None),
    ("endfield", "hypergryph", HypergryphApkCollection, organize_hypergryph_apk, SIGNED_ENDFIELD_URL),
    ("wuwa", "kuro", KuroApkCollection, organize_kuro_apk, None),
    ("pns", "kuro", KuroApkCollection, organize_kuro_apk, None),
    ("tof", "perfectworld", PerfectWorldApkCollection, organize_perfectworld_apk, None),
    ("p5x", "perfectworld", PerfectWorldApkCollection, organize_perfectworld_apk, None),
    ("nte", "perfectworld", PerfectWorldApkCollection, organize_perfectworld_apk, None),
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


def _reference_canonical_url(vendor: str, game_id: str, final_url: str) -> str:
    parsed = urlsplit(final_url)
    if (
        vendor == "hypergryph"
        and game_id == "endfield"
        and parsed.hostname == "beyond.hycdn.cn"
        and "/Android/" in parsed.path
        and parsed.path.lower().endswith(".apk")
    ):
        return urlunsplit((
            "https",
            "beyond-prod.oss-cn-shanghai.aliyuncs.com",
            parsed.path,
            "",
            "",
        ))
    return final_url


def _legacy_reference_organize(collection: object, vendor: str) -> dict:
    source = deepcopy(dict(collection.record))  # type: ignore[attr-defined]
    source["provenance"] = {
        "source_kind": "official_sync",
        "source_name": collection.source_name,  # type: ignore[attr-defined]
        "source_url": collection.source_url,  # type: ignore[attr-defined]
    }
    output = normalize_legacy_record(source)
    artifact = output["artifacts"][0]
    candidate = artifact["urls"][0]
    final_url = source["url"]
    canonical_url = _reference_canonical_url(vendor, source["game_id"], final_url)
    candidate["url"] = canonical_url
    candidate["provider"] = vendor
    candidate["source_kind"] = "official"
    candidate["priority"] = 0
    status = source["status"]
    current = {} if canonical_url != final_url else dict(candidate.get("current") or {})
    current["state"] = "available"
    if status.get("http_code") is not None:
        current["http_code"] = status["http_code"]
    if status.get("last_checked_at") is not None:
        current["checked_at"] = status["last_checked_at"]
    size = source.get("size")
    if size is not None:
        artifact["size"] = size
        current["response_size"] = size
    checksum = source.get("checksum")
    if isinstance(checksum, Mapping):
        if checksum.get("etag") is not None:
            current["etag"] = checksum["etag"]
        if checksum.get("crc64") is not None:
            current["crc64"] = checksum["crc64"]
    if canonical_url == final_url:
        candidate["current"] = current
    else:
        candidate.pop("current", None)
    output["references"] = []
    validate_v2_record(output)
    return output


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

    def test_endfield_signed_apk_url_is_canonicalized_to_vendor_oss(self) -> None:
        output = organize_hypergryph_apk(
            HypergryphApkCollection(
                "https://launcher.example/endfield",
                collected_record("endfield", "hypergryph", url=SIGNED_ENDFIELD_URL),
            )
        )
        candidate = output["artifacts"][0]["urls"][0]
        self.assertEqual(
            candidate["url"],
            "https://beyond-prod.oss-cn-shanghai.aliyuncs.com/6LL0KJuqHBVz33WK/1.4/package/1/1/Android/1.4.3_N3kXcstgi31V2hpt/endfield-hg-1-1.4.3.apk",
        )
        self.assertNotIn("current", candidate)

    def test_all_twelve_games_match_legacy_normalizer_reference_across_field_combinations(self) -> None:
        variants = (
            ("full", lambda raw: raw),
            (
                "full_with_sha256_and_file_time",
                lambda raw: {
                    **raw,
                    "file_time": "2026-08-27T08:09:10Z",
                    "checksum": {"etag": "etag-2", "crc64": "crc-2", "md5": "a" * 32, "sha256": "b" * 64},
                },
            ),
            ("without_size_none", lambda raw: {**raw, "size": None}),
            ("without_size_omitted", lambda raw: {k: v for k, v in raw.items() if k != "size"}),
            ("without_checksum_none", lambda raw: {**raw, "checksum": None}),
            ("without_checksum_omitted", lambda raw: {k: v for k, v in raw.items() if k != "checksum"}),
            ("checksum_all_null", lambda raw: {**raw, "checksum": {"etag": None, "crc64": None, "md5": None}}),
            ("checksum_etag_only", lambda raw: {**raw, "checksum": {"etag": "only-etag"}}),
            ("without_file_time_omitted", lambda raw: {k: v for k, v in raw.items() if k != "file_time"}),
            ("without_version_code_none", lambda raw: {**raw, "version_code": None}),
            ("without_version_code_omitted", lambda raw: {k: v for k, v in raw.items() if k != "version_code"}),
            (
                "all_optional_omitted",
                lambda raw: {
                    k: v for k, v in raw.items()
                    if k not in {"size", "checksum", "file_time", "version_code"}
                } | {"status": {"available": True}},
            ),
        )
        for game_id, vendor, collection_cls, organizer, custom_url in ALL_TWELVE_GAME_CASES:
            for variant_name, transform in variants:
                with self.subTest(game_id=game_id, signed=bool(custom_url), variant=variant_name):
                    raw = transform(collected_record(game_id, vendor, url=custom_url))
                    collection = collection_cls(f"https://official.example.test/{game_id}", raw)
                    output = organizer(collection)
                    expected = _legacy_reference_organize(collection, vendor)
                    self.assertEqual(output, expected)
                    self.assertEqual(json.dumps(output), json.dumps(expected))
                    artifact = output["artifacts"][0]
                    self.assertEqual(artifact["artifact_id"], artifact_id(artifact, output))
                    if custom_url is not None:
                        self.assertNotIn("current", artifact["urls"][0])
                    else:
                        self.assertIn("current", artifact["urls"][0])

    def test_vendor_organizers_preserve_vendor_specific_error_classes(self) -> None:
        vendor_cases = (
            (HypergryphApkCollection, organize_hypergryph_apk, HypergryphApkOrganizationError, "hypergryph", "arknights"),
            (KuroApkCollection, organize_kuro_apk, KuroApkOrganizationError, "kuro", "wuwa"),
            (PerfectWorldApkCollection, organize_perfectworld_apk, PerfectWorldApkOrganizationError, "perfectworld", "nte"),
        )
        for collection_cls, organizer, error_cls, vendor, game_id in vendor_cases:
            base = collected_record(game_id, vendor)
            invalid_inputs = (
                object(),
                collection_cls("ftp://bad.example/entry", base),
                collection_cls("https://official.example.test/entry", "not-a-dict"),  # type: ignore[arg-type]
                collection_cls("https://official.example.test/entry", {**base, "vendor": "mihoyo"}),
                collection_cls("https://official.example.test/entry", {**base, "game_id": "hk4e"}),
                collection_cls("https://official.example.test/entry", {**base, "platform": "windows"}),
                collection_cls("https://official.example.test/entry", {**base, "channel": "taptap"}),
                collection_cls("https://official.example.test/entry", {**base, "filename": "installer.exe"}),
                collection_cls("https://official.example.test/entry", {**base, "url": "relative/path.apk"}),
                collection_cls("https://official.example.test/entry", {**base, "status": {"available": False}}),
                collection_cls("https://official.example.test/entry", {**base, "references": [{"kind": "chunk_manifest", "path": "a"}]}),
                collection_cls("https://official.example.test/entry", {**base, "version": None}),
                collection_cls("https://official.example.test/entry", {**base, "size": -5}),
                collection_cls("https://official.example.test/entry", {**base, "checksum": {"etag": 123}}),
            )
            for item in invalid_inputs:
                with self.subTest(vendor=vendor, item=item):
                    with self.assertRaises(error_cls):
                        organizer(item)  # type: ignore[arg-type]

        # Signed Endfield URL still validates observation status/checksum fields
        for bad_override in (
            {"status": {"available": True, "http_code": -1}},
            {"status": {"available": True, "unknown": 1}},
            {"checksum": {"etag": 123}},
        ):
            with self.subTest(endfield_bad_override=bad_override):
                with self.assertRaises(HypergryphApkOrganizationError):
                    organize_hypergryph_apk(
                        HypergryphApkCollection(
                            "https://launcher.example/endfield",
                            {**collected_record("endfield", "hypergryph", url=SIGNED_ENDFIELD_URL), **bad_override},
                        )
                    )

    def test_no_android_module_imports_normalize_legacy_record(self) -> None:
        android_dir = Path(__file__).resolve().parent / "android"
        for path in sorted(android_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "backend.legacy_record_normalizer", str(path))
                    for alias in node.names:
                        self.assertNotEqual(alias.name, "normalize_legacy_record", str(path))


if __name__ == "__main__":
    unittest.main()
