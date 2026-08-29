from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import zstandard
from fastapi.testclient import TestClient

from backend.api_contract import create_api_app
from backend.app import app
from backend.indexes import rebuild_indexes
from backend.manifest_readers import (
    HttpUpstream,
    ManifestNotFound,
    ManifestTimeout,
    ManifestUpstream,
    _proto_class,
)
from backend.schema_v2 import artifact_id

# Fixed clock for probe-evidence freshness assertions; never the real system date.
FROZEN_NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


def artifact(name: str, *, kind: str = "package", delivery: str = "direct", size: int = 10,
             manifest: dict | None = None, current: dict | None = None) -> dict:
    result = {
        "kind": kind,
        "component": "game",
        "package_type": "full",
        "delivery_mode": delivery,
        "name": name,
        "size": size,
        "decompressed_size": size + 1,
        "checksum": {"md5": hashlib.md5(name.encode()).hexdigest()},
        "urls": [{
            "url": f"https://official.example/{name}",
            "provider": "fixture",
            "source_kind": "official",
            "priority": 0,
            **({"current": current} if current is not None else {}),
        }],
    }
    if manifest is not None:
        result["manifest"] = manifest
    return result


def record(vendor: str, game: str, platform: str, version: str, artifacts: list[dict],
           *, references: list[dict] | None = None, visible: bool = True,
           provenance: dict | None = None) -> dict:
    domain = f"{game}-{'android' if platform == 'android' else 'pc'}"
    value = {
        "schema_version": 2,
        "vendor": vendor,
        "game_id": game,
        "domain_id": domain,
        "platform": platform,
        "channel": "official",
        "version": version,
        "version_code": 123 if platform == "android" else None,
        "file_time": "2026-08-29T00:00:00Z",
        "artifacts": artifacts,
        "references": references or [],
        "is_visible": visible,
        "provenance": provenance or {"source_kind": "official_sync", "source_name": "fixture"},
    }
    identity = {key: value[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
    for item in artifacts:
        item["artifact_id"] = artifact_id(item, record_identity=identity)
    return value


def write_record(root: Path, value: dict) -> Path:
    disk = "android" if value["platform"] == "android" else "pc"
    directory = root / value["vendor"] / value["game_id"] / disk
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{value['version']}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def chunk_fixture() -> tuple[dict, bytes, bytes]:
    message = _proto_class()()
    first = message.Assets.add(AssetName="Game/Bin/a.dat", AssetType=0, AssetSize=12, AssetHashMd5="a" * 32)
    first.AssetChunks.add(
        ChunkName="chunk-a", ChunkDecompressedHashMd5="b" * 32,
        ChunkOnFileOffset=0, ChunkSize=7, ChunkSizeDecompressed=12,
    )
    message.Assets.add(AssetName="root.exe", AssetType=0, AssetSize=5, AssetHashMd5="c" * 32)
    raw = message.SerializeToString()
    compressed = zstandard.ZstdCompressor().compress(raw)
    entry = {
        "category": {"id": 1, "name": "game"},
        "manifest": {
            "id": "manifest-game",
            "checksum": hashlib.md5(raw).hexdigest(),
            "compressed_size": len(compressed),
            "uncompressed_size": len(raw),
        },
        "component": "game",
        "language": None,
        "matching_field": "game",
        "stats": {"compressed_size": 7, "uncompressed_size": 17, "file_count": 2, "chunk_count": 1},
        "manifest_download": {
            "url_prefix": "https://autopatchcn.yuanshen.com/manifests",
            "url_suffix": "",
            "compression": 1,
            "encryption": 0,
        },
        "chunk_download": {
            "url_prefix": "https://autopatchcn.yuanshen.com/chunks",
            "url_suffix": "",
            "compression": 0,
            "encryption": 0,
        },
    }
    document = {
        "schema_version": 1,
        "vendor": "mihoyo",
        "game_id": "hk4e",
        "domain_id": "hk4e-pc",
        "platform": "windows",
        "version": "2.0.0",
        "build_id": "build-2",
        "manifests": [entry],
        "provenance": {"source_kind": "official_sync", "source_name": "fixture", "source_url": "https://official.example/chunks"},
    }
    return document, compressed, b"1234567"


class FakeUpstream:
    def __init__(self, manifest: bytes, chunk: bytes) -> None:
        self.manifest = manifest
        self.chunk = chunk
        self.calls: list[str] = []

    def get_bytes(self, url: str, *, allowed_hosts, max_bytes: int, expected_size: int | None = None):
        self.calls.append(url)
        body = getattr(self, "package", None) if "/pkg_version" in url else self.manifest if "/manifests/" in url else self.chunk
        if body is None:
            body = self.chunk
        if expected_size is not None and len(body) != expected_size:
            raise ManifestUpstream("官方资源长度不匹配")
        if len(body) > max_bytes:
            raise ManifestUpstream("官方资源过大")
        return body, {"content-type": "application/octet-stream", "etag": "fixture"}


class TemporaryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        old = record("mihoyo", "hk4e", "android", "1.0.0", [
            artifact("common.apk", kind="apk", size=10),
            artifact("removed.apk", kind="apk", size=20),
        ])
        new = record("mihoyo", "hk4e", "android", "2.0.0", [
            artifact("common.apk", kind="apk", size=15, current={"state": "available", "http_code": 206, "checked_at": "2026-08-29T01:00:00Z"}),
            artifact("added.apk", kind="apk", size=30),
        ], provenance={"source_kind": "official_sync", "source_name": "fixture", "source_url": "https://official.example/api?token=secret"})
        write_record(self.root, old)
        write_record(self.root, new)

        self.chunk_doc, manifest_body, chunk_body = chunk_fixture()
        pc = record(
            "mihoyo", "hk4e", "windows", "2.0.0", [artifact("game.zip")],
            references=[{"kind": "chunk_manifest", "path": "chunk-manifests/2.0.0.json", "build_id": "build-2", "source": {"source_kind": "official_sync"}}],
        )
        write_record(self.root, pc)
        chunk_path = self.root / "mihoyo" / "hk4e" / "pc" / "chunk-manifests"
        chunk_path.mkdir()
        (chunk_path / "2.0.0.json").write_text(json.dumps(self.chunk_doc), encoding="utf-8")

        for vendor, game, base, files in (
            ("kuro", "wuwa", "https://pcdownload-aliyun.aki-game.com/files/", {"resource": [{"dest": "Client/Bin/a.dll", "size": 7, "md5": "a" * 32}, {"dest": "root.exe", "size": 5, "md5": "b" * 32}]}),
            (
                "perfectworld",
                "nte",
                "https://yhcdn1.wmupd.com/clientRes/publish_PC/Res/",
                {"files": [{"dest": "Client/Bin/b.dll", "size": 9, "md5": "c" * 32, "object": f"c/{'c' * 32}.9"}]},
            ),
        ):
            manifest = {"path": "manifests/1.0.0/files.json", "base_urls": [{"url": base, "provider": vendor, "source_kind": "official", "priority": 0}]}
            value = record(vendor, game, "windows", "1.0.0", [artifact("files.json", delivery="file_manifest", manifest=manifest)])
            write_record(self.root, value)
            document = {"schema_version": 1, "vendor": vendor, "game_id": game, "domain_id": f"{game}-pc", "platform": "windows", "version": "1.0.0", **files}
            target = self.root / vendor / game / "pc" / "manifests" / "1.0.0"
            target.mkdir(parents=True)
            (target / "files.json").write_text(json.dumps(document), encoding="utf-8")

        rebuild_indexes(self.root)
        self.upstream = FakeUpstream(manifest_body, chunk_body)
        self.client = TestClient(create_api_app(self.root, self.upstream, state_root=Path(self.state.name)))

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.state.cleanup()

    def get(self, path: str, status: int = 200):
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, response.text)
        return response

    def test_factory_uses_injected_root_and_inventory(self):
        games = self.get("/api/v1/games").json()
        self.assertEqual([item["id"] for item in games], ["hk4e", "wuwa", "nte"])
        domains = sum((self.get(f"/api/v1/games/{game['id']}/domains").json() for game in games), [])
        self.assertEqual({item["id"] for item in domains}, {"hk4e-android", "hk4e-pc", "wuwa-pc", "nte-pc"})

    def test_hidden_record_is_404(self):
        hidden = record("mihoyo", "hk4e", "android", "hidden", [artifact("hidden.apk", kind="apk")], visible=False)
        write_record(self.root, hidden)
        self.get("/api/v1/domains/hk4e-android/versions/hidden", 404)

    def test_corrupt_record_is_500(self):
        (self.root / "mihoyo" / "hk4e" / "android" / "1.0.0.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.get("/api/v1/domains/hk4e-android/versions", 500).json()["error"]["code"], "corrupt_record")

    def test_index_identity_and_entry_mismatch_are_500(self):
        index_path = self.root / "mihoyo" / "hk4e" / "android" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["game_id"] = "wuwa"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        self.assertEqual(self.get("/api/v1/games", 500).json()["error"]["code"], "index_mismatch")

    def test_chunk_only_higher_version_is_globally_sorted(self):
        chunk_only = record(
            "mihoyo", "hk4e", "windows", "3.0.0", [],
            references=[{"kind": "chunk_manifest", "path": "chunk-manifests/3.0.0.json", "build_id": "build-3", "source": {"source_kind": "official_sync"}}],
        )
        write_record(self.root, chunk_only)

        versions = self.get("/api/v1/domains/hk4e-pc/versions").json()["items"]
        self.assertEqual([item["version"] for item in versions], ["3.0.0", "2.0.0"])
        self.assertTrue(versions[0]["attributes"]["has_chunk"])
        domains = self.get("/api/v1/games/hk4e/domains").json()
        pc_domain = next(item for item in domains if item["id"] == "hk4e-pc")
        self.assertEqual(pc_domain["latest_version"], "3.0.0")

    def test_missing_indexed_record_is_500(self):
        (self.root / "mihoyo" / "hk4e" / "android" / "2.0.0.json").unlink()
        self.assertEqual(self.get("/api/v1/games", 500).json()["error"]["code"], "index_mismatch")

    def test_android_and_pc_version_mappers_are_flat_and_redacted(self):
        expected = {"vendor", "game_id", "platform", "channel", "version", "version_code", "filename", "url", "size", "checksum", "file_time", "status"}
        for path in (
            "/api/v1/domains/hk4e-android/versions/2.0.0",
            "/api/v1/domains/wuwa-pc/versions/1.0.0",
        ):
            body = self.get(path).json()
            self.assertEqual(set(body), expected)
            raw = json.dumps(body)
            self.assertNotIn("schema_version", raw)
            self.assertNotIn("manifest", raw)
            self.assertNotIn(str(self.root), raw)

    def test_provenance_query_is_redacted(self):
        item = self.get("/api/v1/domains/hk4e-android/versions").json()["items"][0]
        self.assertNotIn("source_url", item["provenance"])
        self.assertNotIn("secret", json.dumps(item))

    def get_probed_url(self, path: str):
        with patch("backend.api_contract._utc_now", lambda: FROZEN_NOW):
            return self.get(path).json()["items"][0]["urls"][0]

    def test_current_projection_marks_probed_currents_verified(self):
        url = self.get_probed_url("/api/v1/domains/hk4e-android/versions/2.0.0/artifacts?q=common")
        current = url["current"]
        self.assertEqual(current["reason"], "HTTP 206")
        self.assertEqual(current["evidence_status"], "verified")
        self.assertEqual(current["source_kind"], "live_probe")
        self.assertEqual(current["observed_at"], "2026-08-29T01:00:00Z")
        self.assertEqual(current["expires_at"], "2026-08-29T21:00:00Z")
        self.assertEqual(url["evidence_status"], "verified")

    def test_probe_evidence_freshness_boundary_is_20_hours(self):
        cases = {
            # FROZEN_NOW is 2026-08-29T12:00:00Z; a full 20 hours turns stale.
            "5.0.0": ("2026-08-28T16:01:00Z", "verified"),
            "5.1.0": ("2026-08-28T16:00:00Z", "stale"),
            "5.2.0": ("2026-08-20T00:00:00Z", "stale"),
        }
        for version, (checked_at, _) in cases.items():
            write_record(self.root, record("mihoyo", "hk4e", "android", version, [
                artifact("common.apk", kind="apk", current={"state": "available", "http_code": 206, "checked_at": checked_at}),
            ]))
        rebuild_indexes(self.root)
        for version, (checked_at, expected) in cases.items():
            url = self.get_probed_url(f"/api/v1/domains/hk4e-android/versions/{version}/artifacts?q=common")
            self.assertEqual(url["current"]["evidence_status"], expected, version)
            self.assertEqual(url["current"]["source_kind"], "live_probe")
            self.assertEqual(url["current"]["observed_at"], checked_at)
            self.assertEqual(url["current"]["expires_at"], "2026-08-29T12:01:00Z" if version == "5.0.0" else "2026-08-29T12:00:00Z" if version == "5.1.0" else "2026-08-20T20:00:00Z")
            self.assertEqual(url["evidence_status"], expected)

    def test_stale_evidence_keeps_the_real_state(self):
        write_record(self.root, record("mihoyo", "hk4e", "android", "6.0.0", [
            artifact("common.apk", kind="apk", current={"state": "unavailable", "http_code": 404, "checked_at": "2026-08-20T00:00:00Z"}),
        ]))
        write_record(self.root, record("mihoyo", "hk4e", "android", "6.1.0", [
            artifact("common.apk", kind="apk", current={"state": "unknown", "http_code": 503, "checked_at": "2026-08-20T00:00:00Z"}),
        ]))
        rebuild_indexes(self.root)
        unavailable = self.get_probed_url("/api/v1/domains/hk4e-android/versions/6.0.0/artifacts?q=common")
        unknown = self.get_probed_url("/api/v1/domains/hk4e-android/versions/6.1.0/artifacts?q=common")
        self.assertEqual((unavailable["current"]["state"], unavailable["current"]["evidence_status"]), ("unavailable", "stale"))
        self.assertEqual((unknown["current"]["state"], unknown["current"]["evidence_status"]), ("unknown", "stale"))

    def test_future_checked_at_is_not_verified(self):
        write_record(self.root, record("mihoyo", "hk4e", "android", "6.2.0", [
            artifact("common.apk", kind="apk", current={"state": "available", "http_code": 206, "checked_at": "2026-08-29T13:00:00Z"}),
        ]))
        rebuild_indexes(self.root)
        url = self.get_probed_url("/api/v1/domains/hk4e-android/versions/6.2.0/artifacts?q=common")
        self.assertEqual(url["current"]["evidence_status"], "unverified")
        self.assertEqual(url["current"]["source_kind"], "canonical_current")
        self.assertIsNone(url["current"]["expires_at"])
        self.assertEqual(url["evidence_status"], "unverified")

    def test_probed_outcomes_keep_their_real_state(self):
        states = {
            "3.0.0": {"state": "available", "http_code": 206, "checked_at": "2026-08-29T01:00:00Z"},
            "3.1.0": {"state": "unavailable", "http_code": 404, "checked_at": "2026-08-29T01:10:00Z"},
            "3.2.0": {"state": "unknown", "http_code": 503, "checked_at": "2026-08-29T01:20:00Z"},
        }
        for version, current in states.items():
            write_record(self.root, record("mihoyo", "hk4e", "android", version, [
                artifact("common.apk", kind="apk", current=current),
            ]))
        rebuild_indexes(self.root)
        for version, expected in states.items():
            url = self.get_probed_url(f"/api/v1/domains/hk4e-android/versions/{version}/artifacts?q=common")
            self.assertEqual(url["current"]["evidence_status"], "verified")
            self.assertEqual(url["current"]["source_kind"], "live_probe")
            self.assertEqual(url["current"]["state"], expected["state"])
            self.assertEqual(url["evidence_status"], "verified")

    def test_current_without_valid_probe_timestamp_stays_unverified(self):
        write_record(self.root, record("mihoyo", "hk4e", "android", "4.0.0", [
            artifact("common.apk", kind="apk", current={"state": "available", "http_code": 200}),
        ]))
        write_record(self.root, record("mihoyo", "hk4e", "android", "4.1.0", [
            artifact("common.apk", kind="apk", current={"state": "available", "http_code": 200, "checked_at": "not-a-timestamp"}),
        ]))
        write_record(self.root, record("mihoyo", "hk4e", "android", "4.1.1", [
            artifact("common.apk", kind="apk", current={"state": "available", "http_code": 200, "checked_at": "2026-08-29Z"}),
        ]))
        rebuild_indexes(self.root)
        for version in ("4.0.0", "4.1.0", "4.1.1"):
            url = self.get_probed_url(f"/api/v1/domains/hk4e-android/versions/{version}/artifacts?q=common")
            self.assertEqual(url["current"]["evidence_status"], "unverified")
            self.assertEqual(url["current"]["source_kind"], "canonical_current")
            self.assertIsNone(url["current"]["expires_at"])
            self.assertEqual(url["evidence_status"], "unverified")

    def test_missing_current_keeps_unverified_url_evidence(self):
        write_record(self.root, record("mihoyo", "hk4e", "android", "4.2.0", [artifact("common.apk", kind="apk")]))
        rebuild_indexes(self.root)
        url = self.get("/api/v1/domains/hk4e-android/versions/4.2.0/artifacts?q=common").json()["items"][0]["urls"][0]
        self.assertIsNone(url["current"])
        self.assertEqual(url["evidence_status"], "unverified")

    def test_artifact_filters_sort_and_cursor(self):
        page = self.get("/api/v1/domains/hk4e-android/versions/2.0.0/artifacts?kind=apk&availability_state=unknown&limit=1").json()
        self.assertEqual(len(page["items"]), 1)
        self.assertIsNone(page["next_cursor"])
        self.get("/api/v1/domains/hk4e-android/versions/2.0.0/artifacts?cursor=-1", 400)

    def test_artifact_filter_enums_are_400(self):
        for query in ("kind=nope", "availability_state=maybe", "limit=0"):
            body = self.get(f"/api/v1/domains/hk4e-android/versions/2.0.0/artifacts?{query}", 400).json()
            self.assertEqual(set(body["error"]), {"code", "message", "details"})

    def test_compare_has_added_removed_changed_and_complete_summary(self):
        body = self.get("/api/v1/domains/hk4e-android/compare?from_version=1.0.0&to_version=2.0.0&limit=1&change=added").json()
        self.assertEqual(body["summary"], {"added": 1, "removed": 1, "changed": 1, "size_delta": 15})
        self.assertEqual(body["items"][0]["change"], "added")
        self.assertTrue(all(isinstance(value, (str, int, bool, type(None))) for value in body["items"][0]["identity"].values()))

    def test_compare_kind_change_and_cursor_validation(self):
        base = "/api/v1/domains/hk4e-android/compare?from_version=1.0.0&to_version=2.0.0"
        for query in ("change=nope", "kind=nope", "cursor=bad"):
            self.get(f"{base}&{query}", 400)

    def test_leads_existing_and_missing(self):
        self.assertEqual(self.get("/api/v1/domains/hk4e-pc/leads").json(), {"items": []})
        self.assertEqual(self.get("/api/v1/domains/missing-pc/leads", 404).json()["error"]["code"], "domain_not_found")

    def test_chunk_collection_and_detail_redact_recipes_with_password(self):
        collection = self.get("/api/v1/domains/hk4e-pc/chunk-manifests").json()["items"]
        self.assertEqual(collection[0]["build_id"], "build-2")
        path = self.root / "mihoyo" / "hk4e" / "pc" / "chunk-manifests" / "2.0.0.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["manifests"][0]["manifest_download"]["password"] = "secret"
        path.write_text(json.dumps(document), encoding="utf-8")
        detail = self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/chunk-manifests").json()
        self.assertNotIn("password", json.dumps(detail))
        self.assertNotIn("manifest_download", detail["manifests"][0])

    def test_kuro_and_perfectworld_are_package_files_not_chunk_collection(self):
        for domain in ("wuwa-pc", "nte-pc"):
            self.get(f"/api/v1/domains/{domain}/chunk-manifests", 404)
            page = self.get(f"/api/v1/domains/{domain}/versions/1.0.0/files?source=package").json()
            self.assertEqual(page["source"], "package")
            self.assertTrue(page["items"])
        perfectworld = self.get("/api/v1/domains/nte-pc/versions/1.0.0/file?source=package&path=Client/Bin/b.dll").json()
        self.assertTrue(perfectworld["download_url"].endswith(f"/c/{'c' * 32}.9"))
        self.assertNotIn("Client/Bin/b.dll", perfectworld["download_url"])

    def test_historical_file_manifest_without_base_url_remains_browsable(self):
        record_path = self.root / "kuro" / "wuwa" / "pc" / "1.0.0.json"
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["artifacts"][0]["manifest"].pop("base_urls")
        record_path.write_text(json.dumps(value), encoding="utf-8")
        page = self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files?source=package").json()
        self.assertTrue(page["items"])
        self.assertNotIn("download_url", page["items"][0])

    def test_source_selection_auto_chunk_then_package(self):
        chunk = self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/files?source=auto&identity=game").json()
        package = self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files?source=auto&identity=game").json()
        self.assertEqual((chunk["source"], package["source"]), ("chunk", "package"))
        self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files?source=chunk", 404)
        self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files?source=bad", 400)

    def test_mihoyo_v2_archive_package_is_publicly_browsable(self):
        package = artifact("StarRail_4.4.0.7z.001", delivery="archive", size=10)
        package["package_type"] = "segment"
        package["part"] = 1
        package["urls"][0].update({
            "url": "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail_4.4.0.7z.001",
            "provider": "mihoyo",
            "source_kind": "official",
        })
        value = record(
            "mihoyo", "hkrpg", "windows", "4.4.0", [package],
            references=[{
                "kind": "chunk_manifest", "path": "chunk-manifests/4.4.0.json", "build_id": "build-4.4",
                "source": {"source_kind": "third_party_history"},
            }],
        )
        write_record(self.root, value)
        rebuild_indexes(self.root)
        self.upstream.package = b'{"remoteName":"Game/Bin/StarRail.exe","fileSize":7,"md5":"' + ("a" * 32).encode() + b'"}\n'
        response = self.client.get("/api/v1/domains/hkrpg-pc/versions/4.4.0/files?source=package&identity=game&path=Game/Bin&limit=1")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source"], "package_pkg_version")
        detail = self.client.get("/api/v1/domains/hkrpg-pc/versions/4.4.0/file?source=package&identity=game&path=Game/Bin/StarRail.exe")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["download_url"], "https://autopatchcn.bhsr.com/client/cn/release/PC/unzip/Game/Bin/StarRail.exe")

    def test_auto_falls_back_to_package_when_chunk_identity_is_absent(self):
        record_path = self.root / "kuro" / "wuwa" / "pc" / "1.0.0.json"
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["references"] = [{
            "kind": "chunk_manifest", "path": "chunk-manifests/1.0.0.json", "build_id": "build-kuro",
            "source": {"source_kind": "official_sync"},
        }]
        record_path.write_text(json.dumps(value), encoding="utf-8")
        document = copy.deepcopy(self.chunk_doc)
        document.update({"vendor": "kuro", "game_id": "wuwa", "domain_id": "wuwa-pc", "version": "1.0.0", "build_id": "build-kuro"})
        target = record_path.parent / "chunk-manifests"
        target.mkdir()
        (target / "1.0.0.json").write_text(json.dumps(document), encoding="utf-8")
        identity = value["artifacts"][0]["artifact_id"]
        body = self.get(f"/api/v1/domains/wuwa-pc/versions/1.0.0/files?source=auto&identity={identity}").json()
        self.assertEqual(body["source"], "package")
        self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files?source=chunk&identity=missing", 404)

    def test_upstream_timeout_and_failure_have_distinct_envelopes(self):
        class Failure:
            def __init__(self, error): self.error = error
            def get_bytes(self, *args, **kwargs): raise self.error
        contract = self.client.app.state.contract
        for error, status, code in (
            (ManifestTimeout("timeout"), 504, "upstream_timeout"),
            (ManifestUpstream("failed"), 502, "upstream_error"),
        ):
            contract.upstream = Failure(error)
            body = self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/files?source=chunk", status).json()
            self.assertEqual(body["error"]["code"], code)

    def test_package_tree_has_folders_files_prefix_and_pagination(self):
        root = self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/artifact-tree?kind=file&limit=1").json()
        self.assertEqual(root["folders"][0]["path"], "Client")
        self.assertEqual(root["next_cursor"], "1")
        child = self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/artifact-tree?kind=file&prefix=Client/Bin").json()
        self.assertEqual(child["items"][0]["name"], "Client/Bin/a.dll")

    def test_tree_enums_and_paths_are_400(self):
        base = "/api/v1/domains/wuwa-pc/versions/1.0.0/artifact-tree"
        for query in ("kind=bad", "availability_state=maybe", "kind=file&prefix=../x", "kind=file&cursor=bad"):
            self.get(f"{base}?{query}", 400)

    def test_version_file_and_chunk_file_detail(self):
        local = self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/file?source=package&path=Client/Bin/a.dll").json()
        chunk = self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/chunk-manifests/game/file?path=Game/Bin/a.dat").json()
        self.assertEqual(local["md5"], "a" * 32)
        self.assertEqual(chunk["chunk_count"], 1)
        self.assertNotIn("password", json.dumps(chunk))

    def test_strict_file_paths_are_400(self):
        base = "/api/v1/domains/wuwa-pc/versions/1.0.0/file?source=package&path="
        for value in ("../x", "/x", "C:x", "https://evil/x", "a\\b", "a//b", "./x"):
            self.get(base + httpx.QueryParams({"x": value})["x"], 400)

    def test_manifest_identity_tamper_is_500(self):
        path = self.root / "kuro" / "wuwa" / "pc" / "manifests" / "1.0.0" / "files.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["game_id"] = "hk4e"
        path.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files", 500).json()["error"]["code"], "manifest_identity_mismatch")

    def test_manifest_size_limit_is_500(self):
        path = self.root / "kuro" / "wuwa" / "pc" / "manifests" / "1.0.0" / "files.json"
        with patch("backend.api_contract.MAX_DOCUMENT_BYTES", path.stat().st_size - 1):
            self.assertEqual(self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files", 500).json()["error"]["code"], "corrupt_manifest")

    def test_manifest_symlink_is_rejected(self):
        path = self.root / "kuro" / "wuwa" / "pc" / "manifests" / "1.0.0" / "files.json"
        outside = self.root / "outside.json"
        outside.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        try:
            os.symlink(outside, path)
        except OSError:
            self.skipTest("symlink creation is unavailable")
        self.get("/api/v1/domains/wuwa-pc/versions/1.0.0/files", 500)

    def test_chunk_content_success_not_found_and_bad_name(self):
        response = self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/chunk-content?identity=game&name=chunk-a")
        self.assertEqual(response.content, b"1234567")
        self.assertEqual(response.headers["etag"], "fixture")
        self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/chunk-content?identity=game&name=missing", 404)
        self.get("/api/v1/domains/hk4e-pc/versions/2.0.0/chunk-content?identity=game&name=a%2Fb", 400)

    def test_validation_and_framework_errors_are_sanitized(self):
        for path, status in (("/api/v1/domains/hk4e-pc/versions/2.0.0/files?limit=0", 400), ("/api/v1/no-such", 404)):
            body = self.get(path, status).json()
            self.assertEqual(set(body), {"error"})
            self.assertEqual(set(body["error"]), {"code", "message", "details"})
            self.assertNotIn(str(self.root), json.dumps(body))

    def test_no_admin_routes(self):
        self.assertFalse(any(route.path.startswith("/api/v1/admin") for route in self.client.app.routes))


class CheckedInContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_checked_in_inventory_is_12_games_and_20_domains(self):
        games = self.client.get("/api/v1/games").json()
        self.assertEqual(len(games), 12)
        domains = [domain for game in games for domain in self.client.get(f"/api/v1/games/{game['id']}/domains").json()]
        self.assertEqual(len(domains), 20)

    def test_checked_in_android_mihoyo_kuro_and_perfectworld_records(self):
        for path in (
            "/api/v1/domains/nap-android/versions/3.1",
            "/api/v1/domains/nap-pc/versions/3.1.0",
            "/api/v1/domains/wuwa-pc/versions/3.6.0",
            "/api/v1/domains/nte-pc/versions/1.3.13",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("schema_version", response.json())

    def test_checked_in_chunk_only_version_has_non_fabricated_flat_projection(self):
        response = self.client.get("/api/v1/domains/hk4e-pc/versions/7.0.0")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["filename"], body["url"], body["size"]), ("", "", 0))
        self.assertEqual(body["status"]["available"], None)

    def test_checked_in_three_manifest_families(self):
        chunk = self.client.get("/api/v1/domains/nap-pc/versions/3.1.0/chunk-manifests")
        kuro = self.client.get("/api/v1/domains/wuwa-pc/versions/3.6.0/files?source=package&limit=2")
        perfectworld = self.client.get("/api/v1/domains/nte-pc/versions/1.3.13/files?source=package&limit=2")
        self.assertEqual((chunk.status_code, kuro.status_code, perfectworld.status_code), (200, 200, 200))
        self.assertEqual((kuro.json()["source"], perfectworld.json()["source"]), ("package", "package"))
        self.assertNotIn("password", chunk.text)
        object_detail = self.client.get(
            "/api/v1/domains/tof-pc/versions/6.3.3/file"
            "?source=package&path=Client/WindowsNoEditor/Hotta/Binaries/Win64/QRSL.exe"
        )
        self.assertEqual(object_detail.status_code, 200, object_detail.text)
        self.assertEqual(
            object_detail.json()["download_url"],
            "https://htcdn1.wmupd.com/clientRes/Windows55/Res/5/506d4fcf56cb36de55bd9f9b633c315f.171088480",
        )
        historical = self.client.get("/api/v1/domains/wuwa-pc/versions/1.0.2/files?source=package&limit=1")
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertNotIn("download_url", historical.json()["items"][0])


class HttpUpstreamTests(unittest.TestCase):
    def test_range_success_validates_headers_and_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["range"], "bytes=2-4")
            return httpx.Response(
                206,
                content=b"def",
                headers={"content-range": "bytes 2-4/10", "content-length": "3"},
            )

        body, headers = HttpUpstream(transport=httpx.MockTransport(handler)).get_range(
            "https://autopatchcn.yuanshen.com/files/a.bin",
            start=2,
            end=4,
            allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}),
            max_bytes=10,
        )
        self.assertEqual(body, b"def")
        self.assertEqual(headers["content-range"], "bytes 2-4/10")

    def test_range_rejects_invalid_content_range_or_length(self):
        for headers in (
            {"content-range": "bytes 1-4/10", "content-length": "3"},
            {"content-range": "bytes 2-4/10", "content-length": "4"},
        ):
            transport = httpx.MockTransport(lambda _: httpx.Response(206, content=b"def", headers=headers))
            with self.assertRaises(ManifestUpstream):
                HttpUpstream(transport=transport).get_range(
                    "https://autopatchcn.yuanshen.com/files/a.bin",
                    start=2,
                    end=4,
                    allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}),
                    max_bytes=10,
                )

    def test_range_timeout_is_mapped(self):
        timeout = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)))
        with self.assertRaises(ManifestTimeout):
            HttpUpstream(transport=timeout).get_range(
                "https://autopatchcn.yuanshen.com/files/a.bin",
                start=0,
                end=1,
                allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}),
                max_bytes=10,
            )

    def test_redirect_is_revalidated_and_bounded(self):
        calls = []
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if len(calls) == 1:
                return httpx.Response(302, headers={"location": "/files/next.bin"})
            return httpx.Response(200, content=b"ok", headers={"content-length": "2"})
        body, _ = HttpUpstream(transport=httpx.MockTransport(handler)).get_bytes(
            "https://autopatchcn.yuanshen.com/files/a.bin",
            allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}), max_bytes=2, expected_size=2,
        )
        self.assertEqual(body, b"ok")
        self.assertEqual(len(calls), 2)

    def test_redirect_host_or_path_escape_is_rejected(self):
        for location in ("https://evil.example/files/a", "/other/a"):
            transport = httpx.MockTransport(lambda _: httpx.Response(302, headers={"location": location}))
            with self.assertRaises(ManifestUpstream):
                HttpUpstream(transport=transport).get_bytes(
                    "https://autopatchcn.yuanshen.com/files/a.bin",
                    allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}), max_bytes=10,
                )

    def test_timeout_and_oversize_are_distinct(self):
        timeout = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)))
        with self.assertRaises(ManifestTimeout):
            HttpUpstream(transport=timeout).get_bytes(
                "https://autopatchcn.yuanshen.com/files/a", allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}), max_bytes=2,
            )
        oversize = httpx.MockTransport(lambda _: httpx.Response(200, content=b"abc", headers={"content-length": "3"}))
        with self.assertRaises(ManifestUpstream):
            HttpUpstream(transport=oversize).get_bytes(
                "https://autopatchcn.yuanshen.com/files/a", allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}), max_bytes=2,
            )

    def test_404_is_file_not_found_and_userinfo_is_rejected(self):
        missing = httpx.MockTransport(lambda _: httpx.Response(404))
        with self.assertRaises(ManifestNotFound):
            HttpUpstream(transport=missing).get_bytes(
                "https://autopatchcn.yuanshen.com/files/a", allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}), max_bytes=2,
            )
        with self.assertRaises(ManifestUpstream):
            HttpUpstream().get_bytes(
                "https://secret@autopatchcn.yuanshen.com/files/a", allowed_hosts=frozenset({"autopatchcn.yuanshen.com"}), max_bytes=2,
            )


if __name__ == "__main__":
    unittest.main()
