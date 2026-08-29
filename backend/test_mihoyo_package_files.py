from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api_contract import create_api_app
from backend.indexes import rebuild_indexes
from backend.manifest_readers import ManifestNotFound, ManifestUpstream
from backend.mihoyo_package_files import PackageFilesUpstream, _ArchiveReader, _scattered_root
from backend.schema_v2 import artifact_id


def make_archive() -> bytes:
    raw = b'{"remoteName":"Game/Bin/Star Rail.exe","fileSize":7,"md5":"' + b"a" * 32 + b'"}\n'
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pkg_version", raw)
    return output.getvalue()


def make_duplicate_archive() -> bytes:
    raw = b'{"remoteName":"Game.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pkg_version", raw)
        archive.writestr("pkg_version", raw)
    return output.getvalue()


class PackageUpstream:
    def __init__(self, *, direct: bytes | None = None, archives: dict[str, bytes] | None = None):
        self.direct = direct
        self.archives = archives or {}
        self.calls: list[tuple[str, str]] = []

    def get_bytes(self, url: str, *, allowed_hosts, max_bytes: int, expected_size=None):
        self.calls.append(("bytes", url))
        if self.direct is None:
            raise ManifestNotFound("no pkg_version")
        if not url.endswith("/pkg_version"):
            raise AssertionError("complete package download attempted")
        return self.direct, {"content-length": str(len(self.direct))}

    def get_range(self, url: str, *, start: int, end: int, allowed_hosts, max_bytes: int):
        self.calls.append(("range", url))
        body = self.archives[url]
        value = body[start : end + 1]
        return value, {"content-range": f"bytes {start}-{end}/{len(body)}", "content-length": str(len(value))}


class MissingOrFormatUpstream:
    def __init__(self, *, archive: bytes | None = None, range_missing: bool = False):
        self.archive = archive
        self.range_missing = range_missing

    def get_bytes(self, url: str, *, allowed_hosts, max_bytes: int, expected_size=None):
        raise ManifestNotFound("official resource missing")

    def get_range(self, url: str, *, start: int, end: int, allowed_hosts, max_bytes: int):
        if self.range_missing:
            raise ManifestNotFound("official resource missing")
        assert self.archive is not None
        body = self.archive[start : end + 1]
        return body, {"content-range": f"bytes {start}-{end}/{len(self.archive)}", "content-length": str(len(body))}


class MixedRangeUpstream:
    def __init__(self, upstream_url: str):
        self.upstream_url = upstream_url

    def get_bytes(self, url: str, *, allowed_hosts, max_bytes: int, expected_size=None):
        raise ManifestNotFound("official resource missing")

    def get_range(self, url: str, *, start: int, end: int, allowed_hosts, max_bytes: int):
        if url == self.upstream_url:
            raise ManifestUpstream("invalid range response")
        raise ManifestNotFound("official resource missing")


class TailThenMissingUpstream:
    def __init__(self, url: str):
        self.url = url
        self.tail_done = False

    def get_range(self, url: str, *, start: int, end: int, allowed_hosts, max_bytes: int):
        if not self.tail_done:
            self.tail_done = True
            body = b"x" * (end - start + 1)
            return body, {"content-range": f"bytes {start}-{end}/10", "content-length": str(len(body))}
        raise ManifestNotFound("official resource missing")


class MihoyoPackageFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state_root = Path(self.state.name)

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.state.cleanup()

    def record(self, game_id: str, version: str, artifacts: list[dict], references: list[dict] | None = None) -> dict:
        value = {
            "schema_version": 2, "vendor": "mihoyo", "game_id": game_id,
            "domain_id": f"{game_id}-pc", "platform": "windows", "channel": "official",
            "version": version, "version_code": None, "file_time": None,
            "artifacts": artifacts, "references": references or [], "is_visible": True,
            "provenance": {"source_kind": "official_sync", "source_name": "fixture"},
        }
        identity = {key: value[key] for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")}
        for item in artifacts:
            item["artifact_id"] = artifact_id(item, record_identity=identity)
        return value

    def package(self, game_id: str, version: str, url: str, *, part: int | None = None, package_type: str = "full", current: dict | None = None, priority: int = 0, provider: str = "mihoyo", source_kind: str = "official", size: int = 100) -> dict:
        item = {
            "kind": "package", "component": "game", "package_type": package_type,
            "delivery_mode": "archive", "name": f"{game_id}-{version}.7z" + (f".{part:03}" if part else ""),
            "size": size, "checksum": {"md5": "b" * 32},
            "urls": [{"url": url, "provider": provider, "source_kind": source_kind, "priority": priority}],
        }
        if part is not None:
            item["part"] = part
        if current is not None:
            item["urls"][0]["current"] = current
        return item

    def write(self, value: dict) -> None:
        path = self.root / "mihoyo" / value["game_id"] / "pc"
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{value['version']}.json").write_text(json.dumps(value), encoding="utf-8")
        rebuild_indexes(self.root)

    def client(self, upstream: PackageUpstream) -> TestClient:
        return TestClient(create_api_app(self.root, upstream, state_root=self.state_root))

    def test_scattered_root_rewrites_package_dir_case_insensitively_with_canonical_spelling(self):
        cases = (
            ("nap", "https://autopatchcn.juequling.com/client/PC/volumezip/Game.7z", "https://autopatchcn.juequling.com/client/PC/SplitAudioZip"),
            ("nap", "https://autopatchcn.juequling.com/client/PC/VolumeZip/Game.7z", "https://autopatchcn.juequling.com/client/PC/SplitAudioZip"),
            ("hkrpg", "https://autopatchcn.bhsr.com/client/PC/DOWNLOAD/Game.7z", "https://autopatchcn.bhsr.com/client/PC/unzip"),
            ("bh3", "https://autopatchcn.bh3.com/client/pc/GAME.7z", "https://autopatchcn.bh3.com/client/PC/extract"),
        )
        for game_id, url, expected in cases:
            self.assertEqual(_scattered_root(game_id, url), expected)

    def test_direct_pkg_version_matrix_uses_each_games_canonical_scattered_root(self):
        cases = (
            ("hk4e", "5.5.0", "https://autopatchcn.yuanshen.com/client_app/download/pc_zip/release/YuanShen.zip", "https://autopatchcn.yuanshen.com/client_app/download/pc_zip/release/ScatteredFiles"),
            ("hkrpg", "4.4.0", "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z", "https://autopatchcn.bhsr.com/client/cn/release/PC/unzip"),
            ("nap", "3.1.0", "https://autopatchcn.juequling.com/client/cn/release/VolumeZip/Zenless.7z", "https://autopatchcn.juequling.com/client/cn/release/SplitAudioZip"),
            ("bh3", "4.2.0", "https://autopatchcn.bh3.com/client/cn/release/PC/BH3.7z", "https://autopatchcn.bh3.com/client/cn/release/PC/extract"),
        )
        raw = b'{"remoteName":"Game.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
        for game_id, version, url, scattered_url in cases:
            with self.subTest(game_id=game_id):
                self.write(self.record(game_id, version, [self.package(game_id, version, url, size=10)]))
                upstream = PackageUpstream(direct=raw)
                response = self.client(upstream).get(
                    f"/api/v1/domains/{game_id}-pc/versions/{version}/files", params={"source": "package"}
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["fetch_mode"], "official_scattered_files")
                self.assertEqual(upstream.calls[0], ("bytes", scattered_url + "/pkg_version"))

    def test_pkg_version_and_all_range_candidates_missing_is_stable_not_found(self):
        url = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z"
        value = self.record("hkrpg", "4.4.0", [self.package("hkrpg", "4.4.0", url, size=100)])
        self.write(value)
        response = self.client(MissingOrFormatUpstream(range_missing=True)).get(
            "/api/v1/domains/hkrpg-pc/versions/4.4.0/files", params={"source": "package"}
        )
        self.assertEqual((response.status_code, response.json()["error"]["code"], response.json()["error"]["message"]), (404, "file_not_found", "官方历史资源不可用"))
        self.assertNotIn("EOCD", response.text)

    def test_pkg_version_missing_but_range_7z_is_unsupported_without_eocd(self):
        url = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z"
        value = self.record("hkrpg", "4.4.0", [self.package("hkrpg", "4.4.0", url, size=100)])
        self.write(value)
        archive = b"7z\xbc\xaf'\x1c" + b"\x00" * 94
        response = self.client(MissingOrFormatUpstream(archive=archive)).get(
            "/api/v1/domains/hkrpg-pc/versions/4.4.0/files", params={"source": "package"}
        )
        self.assertEqual((response.status_code, response.json()["error"]["code"], response.json()["error"]["message"]), (422, "package_format_unsupported", "该完整包格式暂不支持读取文件列表"))
        self.assertNotIn("EOCD", response.text)

    def test_mixed_range_failure_and_missing_is_upstream_not_private_missing(self):
        first = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/first.7z"
        second = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/second.7z"
        artifact = self.package("hkrpg", "4.4.0", first, size=100)
        artifact["urls"].append({"url": second, "provider": "mihoyo", "source_kind": "official", "priority": 0})
        value = self.record("hkrpg", "4.4.0", [artifact])
        self.write(value)
        response = self.client(MixedRangeUpstream(first)).get(
            "/api/v1/domains/hkrpg-pc/versions/4.4.0/files", params={"source": "package"}
        )
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (502, "upstream_error"))
        self.assertNotIn("file_not_found", response.text)

    def test_mixed_range_failure_and_missing_in_read_archive_is_upstream(self):
        first = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/first.7z"
        second = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/second.7z"
        reader = _ArchiveReader(
            [[{"url": first, "size": 1}, {"url": second, "size": 1}]],
            MixedRangeUpstream(first),
        )
        with self.assertRaises(PackageFilesUpstream):
            reader.read_archive(0, 1)
        with self.assertRaises(PackageFilesUpstream):
            reader.tail()

    def test_successful_tail_then_missing_range_is_upstream_not_not_found(self):
        url = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/game.7z"
        reader = _ArchiveReader([[{"url": url, "size": 10}]], TailThenMissingUpstream(url))
        self.assertEqual(len(reader.tail()), 10)
        with self.assertRaises(PackageFilesUpstream):
            reader.read_archive(0, 1)

    def test_full_archive_direct_pkg_version_and_download_url(self):
        url = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z"
        value = self.record("hkrpg", "4.4.0", [self.package("hkrpg", "4.4.0", url, size=10)])
        raw = b'{"remoteName":"Game/Bin/Star Rail.exe","fileSize":7,"md5":"' + b"a" * 32 + b'"}\n'
        self.write(value)
        upstream = PackageUpstream(direct=raw)
        client = self.client(upstream)
        response = client.get("/api/v1/domains/hkrpg-pc/versions/4.4.0/files", params={"source": "package", "path": "Game/Bin"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["source"], body["fetch_mode"], body["network_bytes"]), ("package_pkg_version", "official_scattered_files", len(raw)))
        self.assertEqual(body["items"][0]["download_url"], "https://autopatchcn.bhsr.com/client/cn/release/PC/unzip/Game/Bin/Star%20Rail.exe")
        detail = client.get("/api/v1/domains/hkrpg-pc/versions/4.4.0/file", params={"source": "package", "path": "Game/Bin/Star Rail.exe"})
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["download_url"], body["items"][0]["download_url"])

    def test_segmented_archive_falls_back_to_bounded_range_in_part_order(self):
        archive = make_archive()
        split = len(archive) // 2
        pieces = [archive[:split], archive[split:]]
        urls = [
            "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z.001",
            "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z.002",
        ]
        value = self.record("hkrpg", "4.4.0", [
            self.package("hkrpg", "4.4.0", urls[1], part=2, package_type="segment", size=len(pieces[1])),
            self.package("hkrpg", "4.4.0", urls[0], part=1, package_type="segment", size=len(pieces[0])),
        ])
        self.write(value)
        upstream = PackageUpstream(archives=dict(zip(urls, pieces)))
        response = self.client(upstream).get("/api/v1/domains/hkrpg-pc/versions/4.4.0/file", params={"source": "package", "path": "Game/Bin/Star Rail.exe"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["fetch_mode"], "package_zip_member")
        self.assertGreater(response.json()["network_bytes"], 0)
        self.assertEqual([kind for kind, _ in upstream.calls if kind == "range"].count("range"), len([call for call in upstream.calls if call[0] == "range"]))
        self.assertTrue(any(kind == "bytes" and url.endswith("/pkg_version") for kind, url in upstream.calls))

    def test_candidate_requires_official_mihoyo_cdn_and_prefers_available_then_priority(self):
        unavailable = "https://autopatchcn.bhsr.com/client/cn/release/unavailable/PC/download/StarRail.7z"
        available_high_priority = "https://autopatchcn.bhsr.com/client/cn/release/high-priority/PC/download/StarRail.7z"
        available_low_priority = "https://autopatchcn.bhsr.com/client/cn/release/low-priority/PC/download/StarRail.7z"
        artifact = self.package("hkrpg", "4.4.0", unavailable, size=10, priority=0)
        artifact["urls"].extend([
            {"url": "https://evil.example/StarRail.7z", "provider": "mihoyo", "source_kind": "official", "priority": 0},
            {"url": available_high_priority, "provider": "mihoyo", "source_kind": "official", "priority": 5, "current": {"state": "available"}},
            {"url": available_low_priority, "provider": "mihoyo", "source_kind": "official", "priority": 1, "current": {"state": "available"}},
            {"url": "https://autopatchcn.bhsr.com/client/cn/release/PC/download/nope.7z", "provider": "community", "source_kind": "official", "priority": 0},
        ])
        value = self.record("hkrpg", "4.4.0", [artifact])
        self.write(value)
        raw = b'{"remoteName":"Game.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
        upstream = PackageUpstream(direct=raw)
        body = self.client(upstream).get("/api/v1/domains/hkrpg-pc/versions/4.4.0/files", params={"source": "package"}).json()
        self.assertEqual(body["fetch_mode"], "official_scattered_files")
        self.assertEqual(upstream.calls[0][1], "https://autopatchcn.bhsr.com/client/cn/release/low-priority/PC/unzip/pkg_version")

    def test_cache_hit_avoids_network_and_corrupt_cache_fails(self):
        url = "https://autopatchcn.yuanshen.com/client_app/download/pc_zip/release/YuanShen.zip"
        value = self.record("hk4e", "5.5.0", [self.package("hk4e", "5.5.0", url, size=10)])
        self.write(value)
        raw = b'{"remoteName":"YuanShen.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
        upstream = PackageUpstream(direct=raw)
        client = self.client(upstream)
        first = client.get("/api/v1/domains/hk4e-pc/versions/5.5.0/files", params={"source": "package"})
        self.assertEqual(first.status_code, 200, first.text)
        calls = len(upstream.calls)
        self.assertEqual(client.get("/api/v1/domains/hk4e-pc/versions/5.5.0/files", params={"source": "package"}).status_code, 200)
        self.assertEqual(len(upstream.calls), calls)
        cache_files = list(self.state_root.glob("cache/package-files/hk4e/5.5.0/*/files.json"))
        self.assertEqual(len(cache_files), 1)
        cache_files[0].write_text("{broken", encoding="utf-8")
        broken = client.get("/api/v1/domains/hk4e-pc/versions/5.5.0/files", params={"source": "package"})
        self.assertEqual((broken.status_code, broken.json()["error"]["code"]), (500, "corrupt_manifest"))

    def test_cache_schema_mismatch_fails_explicitly(self):
        url = "https://autopatchcn.yuanshen.com/client_app/download/pc_zip/release/YuanShen.zip"
        value = self.record("hk4e", "5.5.0", [self.package("hk4e", "5.5.0", url, size=10)])
        self.write(value)
        raw = b'{"remoteName":"YuanShen.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
        upstream = PackageUpstream(direct=raw)
        client = self.client(upstream)
        self.assertEqual(client.get("/api/v1/domains/hk4e-pc/versions/5.5.0/files", params={"source": "package"}).status_code, 200)
        cache_file = next(self.state_root.glob("cache/package-files/hk4e/5.5.0/*/files.json"))
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        cache["schema_version"] = 999
        cache_file.write_text(json.dumps(cache), encoding="utf-8")
        broken = client.get("/api/v1/domains/hk4e-pc/versions/5.5.0/files", params={"source": "package"})
        self.assertEqual((broken.status_code, broken.json()["error"]["code"]), (500, "corrupt_manifest"))

    def test_historical_vendor_owned_bh3_cdn_is_accepted(self):
        url = "https://bundle.bh3.com/tmp/pc/BH3_v4.2.0.7z"
        value = self.record("bh3", "4.2.0", [self.package("bh3", "4.2.0", url, size=10)])
        self.write(value)
        raw = b'{"remoteName":"BH3.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
        response = self.client(PackageUpstream(direct=raw)).get(
            "/api/v1/domains/bh3-pc/versions/4.2.0/files", params={"source": "package"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["items"])

    def test_duplicate_pkg_version_member_is_rejected(self):
        url = "https://autopatchcn.bhsr.com/client/cn/release/PC/download/StarRail.7z"
        value = self.record("hkrpg", "4.4.0", [self.package("hkrpg", "4.4.0", url, size=len(make_duplicate_archive()))])
        self.write(value)
        upstream = PackageUpstream(archives={url: make_duplicate_archive()})
        response = self.client(upstream).get(
            "/api/v1/domains/hkrpg-pc/versions/4.4.0/files", params={"source": "package"}
        )
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (502, "upstream_error"))

    def test_bad_identity_path_and_host_are_rejected(self):
        url = "https://autopatchcn.juequling.com/package_download/release/VolumeZip/game.zip"
        value = self.record("nap", "3.1.0", [self.package("nap", "3.1.0", url, size=10)])
        self.write(value)
        raw = b'{"remoteName":"Game.exe","fileSize":1,"md5":"' + b"a" * 32 + b'"}\n'
        client = self.client(PackageUpstream(direct=raw))
        self.assertEqual(client.get("/api/v1/domains/nap-pc/versions/3.1.0/files", params={"source": "package", "identity": "bad identity"}).status_code, 400)
        self.assertEqual(client.get("/api/v1/domains/nap-pc/versions/3.1.0/files", params={"source": "package", "path": "../x"}).status_code, 400)
        bad_host = self.record(
            "nap", "3.1.0", [self.package("nap", "3.1.0", "https://evil.example/release/game.zip")]
        )
        self.write(bad_host)
        rejected = self.client(PackageUpstream(direct=raw)).get("/api/v1/domains/nap-pc/versions/3.1.0/files", params={"source": "package"})
        self.assertEqual(rejected.status_code, 404)


if __name__ == "__main__":
    unittest.main()
