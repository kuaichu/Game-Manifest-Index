import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.indexes import IndexReadError, index_path, read_index, rebuild_index, rebuild_indexes


def make_record(platform, version, *, vendor="v", game_id="g", domain="d", visible=True,
                artifacts=None, references=None, state="available", size=10):
    if artifacts is None:
        artifacts = [{"kind": "apk" if platform == "android" else "package", "component": "game",
                      "package_type": "full", "size": size,
                      "urls": [{"url": "https://example.invalid/a", "current": {"state": state}}]}]
    return {"vendor": vendor, "game_id": game_id, "domain_id": domain, "platform": platform,
            "version": version, "file_time": "t", "is_visible": visible, "artifacts": artifacts,
            "references": [] if references is None else references}


def write_record(directory, name, value):
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


class IndexTests(unittest.TestCase):
    def test_nondefault_resource_index_is_isolated_from_same_version_default_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            default = root / "hypergryph" / "endfield" / "pc"
            resources = default / "domains" / "endfield-resources"
            resources.mkdir(parents=True)
            write_record(default, "1.0.json", make_record("windows", "1.0", vendor="hypergryph", game_id="endfield", domain="endfield-pc"))
            resource = {"kind": "resource", "component": "resource", "name": "data/a.bin", "size": 7,
                        "checksum": {"md5": "a" * 32}, "urls": [{"url": "https://example.invalid/a"}]}
            write_record(resources, "1.0.json", make_record("windows", "1.0", vendor="hypergryph", game_id="endfield", domain="endfield-resources", artifacts=[resource]))
            paths = rebuild_indexes(root)
            default_index = read_index(default / "index.json")
            resource_index = read_index(resources / "index.json")
            self.assertIn(default / "index.json", paths)
            self.assertIn(resources / "index.json", paths)
            self.assertEqual(default_index["domain_id"], "endfield-pc")
            self.assertEqual(resource_index["domain_id"], "endfield-resources")
            self.assertEqual(resource_index["versions"][0]["size"], 7)

    def test_nondefault_index_path_rejects_unregistered_or_unsafe_domains(self):
        root = Path("data")
        for domain in ("other-resources", "../endfield-resources"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                index_path(root, "hypergryph", "endfield", "windows", domain)

    def test_android_projection_and_numeric_sort(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "android"
            directory.mkdir(parents=True)
            write_record(directory, "a.json", make_record("android", "2.10", size=12))
            write_record(directory, "b.json", make_record("android", "2.9"))
            result = read_index(rebuild_index(root, "v", "g", "android"))
            self.assertEqual([x["version"] for x in result["versions"]], ["2.10", "2.9"])
            self.assertEqual(result["versions"][0], {"version": "2.10", "updated_at": "t", "available": True, "size": 12})

    def test_pc_multiple_full_sizes_and_ignores_segments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "pc"
            directory.mkdir(parents=True)
            artifacts = [{"kind": "package", "component": "game", "package_type": kind, "size": size,
                          "urls": [{"url": f"https://example.invalid/{size}", "current": {"state": "available"}}]}
                         for kind, size in (("full", 11), ("full", 13), ("segment", 99))]
            write_record(directory, "v.json", make_record("windows", "1", artifacts=artifacts))
            self.assertEqual(read_index(rebuild_index(root, "v", "g", "pc"))["versions"][0]["size"], 24)

    def test_pc_segment_fallback_sums_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "pc"
            directory.mkdir(parents=True)
            artifacts = [{"kind": "package", "component": "game", "package_type": "segment", "part": part,
                          "size": size, "urls": [{"url": str(part), "current": {"state": "available"}}]}
                         for part, size in ((1, 4), (2, 6))]
            write_record(directory, "v.json", make_record("windows", "1", artifacts=artifacts))
            self.assertEqual(read_index(rebuild_index(root, "v", "g", "pc"))["versions"][0]["size"], 10)

    def test_pc_chunk_manifest_reference_only_version_is_indexed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "pc"
            directory.mkdir(parents=True)
            write_record(directory, "v.json", make_record(
                "windows", "1", artifacts=[],
                references=[{"kind": "chunk_manifest", "path": "chunk-manifests/1.json"}],
            ))
            self.assertEqual(
                read_index(rebuild_index(root, "v", "g", "pc"))["versions"],
                [{"version": "1", "updated_at": "t", "available": None, "size": None}],
            )

    def test_pc_does_not_index_non_browsable_reference_only_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "pc"
            directory.mkdir(parents=True)
            write_record(directory, "bad-kind.json", make_record(
                "windows", "1", artifacts=[],
                references=[{"kind": "other", "path": "chunk-manifests/1.json"}],
            ))
            write_record(directory, "bad-path.json", make_record(
                "windows", "2", artifacts=[],
                references=[{"kind": "chunk_manifest", "path": "../chunk-manifests/2.json"}],
            ))
            self.assertFalse(rebuild_index(root, "v", "g", "pc").exists())

    def test_pc_availability_aggregation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "pc"
            directory.mkdir(parents=True)
            for version, states in (("false", ("available", "unavailable")), ("true", ("available", "available")),
                                    ("unknown", ("available", "unknown"))):
                artifacts = [{"kind": "package", "component": "game", "package_type": "full", "size": 1,
                              "urls": [{"url": str(i), "current": {"state": state}}]}
                             for i, state in enumerate(states)]
                write_record(directory, version + ".json", make_record("windows", version, artifacts=artifacts))
            entries = read_index(rebuild_index(root, "v", "g", "pc"))["versions"]
            self.assertEqual({x["version"]: x["available"] for x in entries}, {"false": False, "true": True, "unknown": None})

    def test_filters_hidden_corrupt_nonobject_missing_and_mismatched_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "android"
            directory.mkdir(parents=True)
            write_record(directory, "good.json", make_record("android", "1"))
            (directory / "corrupt.json").write_text("{", encoding="utf-8")
            (directory / "list.json").write_text("[]", encoding="utf-8")
            write_record(directory, "hidden.json", make_record("android", "2", visible=False))
            write_record(directory, "vendor.json", make_record("android", "3", vendor="other"))
            write_record(directory, "game.json", make_record("android", "4", game_id="other"))
            write_record(directory, "platform.json", make_record("windows", "5"))
            write_record(directory, "missing.json", make_record("android", ""))
            self.assertEqual([x["version"] for x in read_index(rebuild_index(root, "v", "g", "android"))["versions"]], ["1"])

    def test_domain_id_consistent_conflict_and_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "android"
            directory.mkdir(parents=True)
            write_record(directory, "a.json", make_record("android", "1", domain="same"))
            write_record(directory, "b.json", make_record("android", "2", domain="same"))
            self.assertEqual(read_index(rebuild_index(root, "v", "g", "android"))["domain_id"], "same")
            write_record(directory, "b.json", make_record("android", "2", domain="other"))
            self.assertNotIn("domain_id", read_index(rebuild_index(root, "v", "g", "android")))
            write_record(directory, "b.json", make_record("android", "2", domain=None))
            self.assertNotIn("domain_id", read_index(rebuild_index(root, "v", "g", "android")))

    def test_empty_directory_removes_existing_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "android"
            directory.mkdir(parents=True)
            write_record(directory, "v.json", make_record("android", "1"))
            path = rebuild_index(root, "v", "g", "android")
            (directory / "v.json").unlink()
            rebuild_index(root, "v", "g", "android")
            self.assertFalse(path.exists())

    def test_read_index_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.json"
            self.assertIsNone(read_index(path))
            for raw in ("{", "[]", "{}", '{"versions": {}}'):
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(IndexReadError): read_index(path)
            path.write_text('{"versions": []}', encoding="utf-8")
            self.assertEqual(read_index(path), {"versions": []})

    def test_read_index_rejects_directory_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "index.json"
            directory.mkdir()
            with self.assertRaises(IndexReadError): read_index(directory)
            link = root / "link.json"
            try: link.symlink_to(directory)
            except (OSError, NotImplementedError): self.skipTest("symlinks unavailable")
            with self.assertRaises(IndexReadError): read_index(link)

    def test_unsafe_components_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for value in ("", ".", "..", "bad/name", "bad\\name", "bad*name", "bad\x00name"):
                with self.assertRaises(ValueError): index_path(root, value, "g", "android")
                with self.assertRaises(ValueError): rebuild_index(root, "v", value, "android")
            self.assertEqual(list(root.iterdir()), [])

    def test_rebuild_index_enters_data_file_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "v" / "g" / "android"
            directory.mkdir(parents=True)
            write_record(directory, "v.json", make_record("android", "1"))
            entered = []

            class Lock:
                def __enter__(self): entered.append(True)
                def __exit__(self, *args): return False

            with patch("backend.indexes.data_file_lock", return_value=Lock()):
                rebuild_index(root, "v", "g", "android")
            self.assertEqual(entered, [True])

    def test_root_rebuild_only_processes_android_and_pc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            android = root / "v" / "g" / "android"
            pc = root / "v" / "g" / "pc"
            other = root / "v" / "g" / "other"
            android.mkdir(parents=True)
            pc.mkdir()
            other.mkdir()
            write_record(android, "a.json", make_record("android", "1"))
            write_record(pc, "p.json", make_record("windows", "1"))
            write_record(other, "o.json", make_record("android", "1"))
            paths = rebuild_indexes(root)
            self.assertEqual({path.parent.name for path in paths}, {"android", "pc"})
            self.assertFalse((other / "index.json").exists())


if __name__ == "__main__":
    unittest.main()
