from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.admin_probe import stable_url_id
from backend.app import create_app
from backend.indexes import rebuild_index
from backend.schema_v2 import artifact_id, validate_v2_record
from backend.version_store import write_v2_record


TOKEN = "admin-version-token-123456"


def make_record(
    *,
    platform: str = "android",
    version: str = "1.0.0",
    visible: bool = True,
    reference: bool = True,
) -> dict:
    domain_id = f"hk4e-{'android' if platform == 'android' else 'pc'}"
    if platform == "android":
        item = {
            "kind": "apk",
            "component": "game",
            "package_type": "full",
            "delivery_mode": "direct",
            "name": "game.apk",
            "size": 10,
            "decompressed_size": 11,
            "checksum": {
                "md5": hashlib.md5(b"game").hexdigest(),
                "crc64": "17747051605820217472",
            },
            "urls": [
                {
                    "url": "https://example.test/game.apk",
                    "provider": "fixture",
                    "source_kind": "official",
                    "priority": 0,
                    "current": {
                        "state": "available",
                        "http_code": 200,
                        "checked_at": "2026-08-29T00:00:00Z",
                    },
                }
            ],
        }
    else:
        item = {
            "kind": "package",
            "component": "game",
            "package_type": "full",
            "delivery_mode": "archive",
            "name": "game.zip",
            "size": 20,
            "urls": [
                {
                    "url": "https://example.test/game.zip",
                    "provider": "fixture",
                    "source_kind": "official",
                    "priority": 0,
                }
            ],
        }
    record = {
        "schema_version": 2,
        "vendor": "mihoyo",
        "game_id": "hk4e",
        "domain_id": domain_id,
        "platform": platform,
        "channel": "official",
        "version": version,
        "version_code": 1 if platform == "android" else None,
        "file_time": "2026-01-01T00:00:00Z",
        "artifacts": [item],
        "references": ([{"kind": "chunk_manifest", "path": "manifests/a.json"}] if reference else []),
        "is_visible": visible,
        "provenance": {"source_kind": "official_sync", "source_name": "fixture"},
    }
    identity = {
        key: record[key]
        for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")
    }
    item["artifact_id"] = artifact_id(item, record_identity=identity)
    validate_v2_record(record)
    return record


def manual_payload(version: str = "2.0.0") -> dict:
    return {
        "version": version,
        "client_version": version,
        "file_path": "override.apk",
        "unpacked_size": 15,
        "files_checksum_type": "md5",
        "files_checksum_value": hashlib.md5(b"new").hexdigest(),
        "source_note": "accepted but not stored",
        "attributes": {
            "channel": "official",
            "version_code": 2,
            "file_created_at": "2026-02-01T00:00:00Z",
        },
        "artifacts": [
            {
                "kind": "file",
                "name": "new.apk",
                "part": 1,
                "size": 4,
                "urls": [
                    {
                        "url": "https://example.test/new.apk",
                        "priority": 0,
                        "source_kind": "manual",
                    }
                ],
            }
        ],
    }


def make_endfield_resources_record() -> dict:
    value = make_record(platform="windows", reference=False)
    value.update({
        "vendor": "hypergryph",
        "game_id": "endfield",
        "domain_id": "endfield-resources",
    })
    item = value["artifacts"][0]
    item.update({
        "kind": "resource",
        "component": "resource",
        "name": "VFS/ABCD/file.chk",
        "checksum": {"md5": hashlib.md5(b"resource").hexdigest()},
        "urls": [{
            "url": "https://beyond.hycdn.cn/release/files/VFS/ABCD/file.chk",
            "provider": "beyond.hycdn.cn",
            "source_kind": "official",
            "priority": 0,
        }],
    })
    for key in ("package_type", "delivery_mode", "part", "decompressed_size", "manifest"):
        item.pop(key, None)
    identity = {
        key: value[key]
        for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")
    }
    item["artifact_id"] = artifact_id(item, record_identity=identity)
    validate_v2_record(value)
    return value


class VersionAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.data = base / "data"
        self.state = base / "state"
        self.data.mkdir()
        self.android = make_record()
        write_v2_record(self.android, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "android")
        self.client = TestClient(
            create_app(self.data, state_root=self.state, admin_token=TOKEN),
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def auth(token: str = TOKEN) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def record_path(self, version: str = "1.0.0") -> Path:
        return self.data / "mihoyo" / "hk4e" / "android" / f"{version}.json"

    def test_auth_is_required_before_admin_contract(self):
        disabled = TestClient(
            create_app(self.data, state_root=self.state / "disabled", admin_token=None),
        )
        self.assertEqual(disabled.get("/api/v1/admin/catalog").status_code, 503)
        self.assertEqual(self.client.get("/api/v1/admin/catalog").status_code, 401)
        malformed = self.client.post(
            "/api/v1/admin/domains/hk4e-android/versions",
            headers=self.auth("wrong-admin-token-123456"),
            json={"version_code": "bad"},
        )
        self.assertEqual(malformed.status_code, 401)

    def test_catalog_handles_manifest_directories_and_projects_real_capabilities(self):
        pc = make_record(platform="windows")
        write_v2_record(pc, self.data)
        rebuild_index(self.data, "mihoyo", "hk4e", "windows")
        manifest_dir = self.data / "mihoyo" / "hk4e" / "pc" / "chunk-manifests"
        manifest_dir.mkdir()
        (manifest_dir / "fixture.json").write_text("{}", encoding="utf-8")

        response = self.client.get("/api/v1/admin/catalog", headers=self.auth())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        domains = {item["id"]: item for item in body["domains"]}
        self.assertEqual(domains["hk4e-android"]["platform"], "android")
        self.assertIn("apk", domains["hk4e-android"]["capabilities"])
        self.assertEqual(domains["hk4e-pc"]["platform"], "windows")
        self.assertIn("packages", domains["hk4e-pc"]["capabilities"])
        game = next(item for item in body["games"] if item["id"] == "hk4e")
        self.assertEqual((game["platform"], game["version_count"]), ("multi", 2))

    def test_catalog_and_version_list_include_registered_secondary_pc_domain(self):
        value = make_endfield_resources_record()
        write_v2_record(value, self.data)
        rebuild_index(
            self.data, "hypergryph", "endfield", "windows", "endfield-resources",
        )

        catalog = self.client.get("/api/v1/admin/catalog", headers=self.auth())
        self.assertEqual(catalog.status_code, 200)
        domain = next(
            item for item in catalog.json()["domains"]
            if item["id"] == "endfield-resources"
        )
        self.assertEqual((domain["game_id"], domain["platform"], domain["version_count"]),
                         ("endfield", "windows", 1))

        versions = self.client.get(
            "/api/v1/admin/domains/endfield-resources/versions", headers=self.auth(),
        )
        self.assertEqual(versions.status_code, 200)
        self.assertEqual([item["version"] for item in versions.json()["items"]], ["1.0.0"])

    def test_hidden_version_remains_admin_visible_but_not_public(self):
        hidden = self.client.patch(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0",
            headers=self.auth(),
            json={"is_visible": False},
        )
        self.assertEqual(hidden.status_code, 200)
        items = self.client.get(
            "/api/v1/admin/domains/hk4e-android/versions", headers=self.auth(),
        ).json()["items"]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["is_visible"])
        self.assertEqual(
            self.client.get("/api/v1/domains/hk4e-android/versions").status_code,
            404,
        )
        restored = self.client.patch(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0",
            headers=self.auth(),
            json={"is_visible": True},
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/domains/hk4e-android/versions").status_code,
            200,
        )

    def test_manual_post_creates_valid_canonical_record_without_apk_part(self):
        response = self.client.post(
            "/api/v1/admin/domains/hk4e-android/versions",
            headers=self.auth(),
            json=manual_payload(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("未自动探活", response.json()["probe_error"])
        saved = json.loads(self.record_path("2.0.0").read_text(encoding="utf-8"))
        validate_v2_record(saved)
        artifact = saved["artifacts"][0]
        self.assertEqual(saved["version_code"], 2)
        self.assertEqual(saved["file_time"], "2026-02-01T00:00:00Z")
        self.assertEqual(saved["provenance"]["source_kind"], "manual")
        self.assertEqual((artifact["kind"], artifact["name"]), ("apk", "override.apk"))
        self.assertNotIn("part", artifact)
        self.assertEqual(artifact["decompressed_size"], 15)
        identity = {
            key: saved[key]
            for key in ("vendor", "game_id", "domain_id", "platform", "channel", "version")
        }
        self.assertEqual(artifact["artifact_id"], artifact_id(artifact, record_identity=identity))
        duplicate = self.client.post(
            "/api/v1/admin/domains/hk4e-android/versions",
            headers=self.auth(),
            json=manual_payload(),
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_manual_payload_is_strict_and_rejects_unsafe_urls(self):
        payload = manual_payload("3.0.0")
        payload["unexpected"] = True
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/domains/hk4e-android/versions",
                headers=self.auth(),
                json=payload,
            ).status_code,
            422,
        )
        payload = manual_payload("3.0.0")
        payload["version_code"] = "3"
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/domains/hk4e-android/versions",
                headers=self.auth(),
                json=payload,
            ).status_code,
            422,
        )
        payload = manual_payload("3.0.0")
        payload["artifacts"][0]["urls"][0]["url"] = "file:///etc/passwd"
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/domains/hk4e-android/versions",
                headers=self.auth(),
                json=payload,
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.patch(
                "/api/v1/admin/domains/hk4e-android/versions/1.0.0/editable",
                headers=self.auth(),
                json={"artifacts": []},
            ).status_code,
            422,
        )

    def test_editable_round_trip_preserves_manual_and_probe_ownership(self):
        original = json.loads(self.record_path().read_text(encoding="utf-8"))
        editable = self.client.get(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0/editable",
            headers=self.auth(),
        ).json()
        old_artifact = original["artifacts"][0]
        self.assertEqual(
            editable["artifacts"][0]["urls"][0]["id"],
            stable_url_id(old_artifact["artifact_id"], 0, old_artifact["urls"][0]["url"]),
        )
        artifact_payload = copy.deepcopy(editable["artifacts"][0])
        for candidate in artifact_payload["urls"]:
            candidate.pop("id", None)
        response = self.client.patch(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0/editable",
            headers=self.auth(),
            json={
                "file_path": "renamed.apk",
                "attributes": {"channel": "beta", "version_code": 2},
                "artifacts": [artifact_payload],
            },
        )
        self.assertEqual(response.status_code, 200)
        saved = json.loads(self.record_path().read_text(encoding="utf-8"))
        validate_v2_record(saved)
        candidate = saved["artifacts"][0]["urls"][0]
        self.assertEqual((saved["channel"], saved["version_code"]), ("beta", 2))
        self.assertEqual(saved["artifacts"][0]["name"], "renamed.apk")
        self.assertEqual(saved["references"], original["references"])
        self.assertEqual(saved["provenance"], original["provenance"])
        self.assertEqual(saved["is_visible"], original["is_visible"])
        self.assertEqual(candidate["provider"], "fixture")
        self.assertEqual(candidate["current"], old_artifact["urls"][0]["current"])
        self.assertEqual(saved["artifacts"][0]["checksum"], old_artifact["checksum"])
        self.assertNotEqual(saved["artifacts"][0]["artifact_id"], old_artifact["artifact_id"])

    def test_changed_url_drops_old_current_and_uses_manual_provider(self):
        editable = self.client.get(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0/editable",
            headers=self.auth(),
        ).json()
        artifact_payload = editable["artifacts"][0]
        artifact_payload["urls"] = [
            {
                "url": "https://example.test/changed.apk",
                "priority": 0,
                "source_kind": "manual",
            }
        ]
        response = self.client.patch(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0/editable",
            headers=self.auth(),
            json={"artifacts": [artifact_payload]},
        )
        self.assertEqual(response.status_code, 200)
        candidate = json.loads(self.record_path().read_text(encoding="utf-8"))["artifacts"][0]["urls"][0]
        self.assertEqual(candidate["provider"], "manual")
        self.assertNotIn("current", candidate)

    def test_delete_rebuilds_index_and_preserves_orphan_manifest(self):
        manifest = self.data / "mihoyo" / "hk4e" / "android" / "manifests" / "a.json"
        manifest.parent.mkdir()
        manifest.write_text("{}", encoding="utf-8")
        response = self.client.delete(
            "/api/v1/admin/domains/hk4e-android/versions/1.0.0",
            headers=self.auth(),
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(self.record_path().exists())
        self.assertFalse((self.record_path().parent / "index.json").exists())
        self.assertTrue(manifest.exists())
        catalog = self.client.get("/api/v1/admin/catalog", headers=self.auth()).json()
        domain = next(item for item in catalog["domains"] if item["id"] == "hk4e-android")
        self.assertEqual(domain["version_count"], 0)

    def test_unsupported_mutations_are_explicit_409(self):
        calls = (
            ("post", "/api/v1/admin/games", {}),
            ("patch", "/api/v1/admin/games/hk4e", {}),
            ("delete", "/api/v1/admin/games/hk4e", None),
            ("post", "/api/v1/admin/domains", {}),
            ("patch", "/api/v1/admin/domains/hk4e-android", {}),
            ("delete", "/api/v1/admin/domains/hk4e-android", None),
            (
                "post",
                "/api/v1/admin/domains/hk4e-android/versions/1.0.0/artifacts/edit",
                {},
            ),
        )
        for method, path, payload in calls:
            response = getattr(self.client, method)(
                path,
                headers=self.auth(),
                **({"json": payload} if payload is not None else {}),
            )
            self.assertEqual((method, path, response.status_code), (method, path, 409))

    def test_corrupt_and_identity_mismatched_records_are_not_skipped(self):
        bad = self.record_path("bad")
        bad.write_text("{broken", encoding="utf-8")
        response = self.client.get(
            "/api/v1/admin/domains/hk4e-android/versions", headers=self.auth(),
        )
        self.assertEqual(response.status_code, 500)
        bad.unlink()

        mismatch = copy.deepcopy(self.android)
        mismatch["version"] = "1.0.0"
        bad.write_text(json.dumps(mismatch), encoding="utf-8")
        response = self.client.get(
            "/api/v1/admin/domains/hk4e-android/versions", headers=self.auth(),
        )
        self.assertEqual(response.status_code, 500)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_record_is_rejected(self):
        link = self.record_path("link")
        try:
            os.symlink(self.record_path(), link)
        except OSError:
            self.skipTest("symlink creation not permitted")
        response = self.client.get(
            "/api/v1/admin/domains/hk4e-android/versions", headers=self.auth(),
        )
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
