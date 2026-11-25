"""Discover or import official Manjuu PC launcher packageconfig releases."""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import tempfile
import time
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

from backend.schema_v2 import SchemaValidationError, artifact_id, validate_v2_record
from backend.storage_locks import DATA_LOCK, data_file_lock
from backend.version_store import record_index_transaction, write_v2_record
from url_adapters.common import AdapterError, print_error

PACKAGECONFIG_URL = "https://api-grp.manjuu.com/pc-launcher/client/gameversion/packageconfig"
CDN = "https://syncstation.manjuu.com"
SALT_ENV = "GMI_MANJUU_LAUNCHER_SALT"
KEY_ENV = "GMI_MANJUU_MANIFEST_KEY"
IV_ENV = "GMI_MANJUU_MANIFEST_IV"
_LAUNCHER_ID = "93cdd43e096046138053253dc56d3562"
_APP_ID = "354"
_CHANNEL = "C000"
_SUB_CHANNEL = "SC000"
_LAUNCHER_VERSION = "1.0.1.1"
_PACKAGECONFIG_QUERY = f"launcherId={_LAUNCHER_ID}&uid="
_CATALOG_LIMIT = 1 << 20
_MANIFEST_LIMIT = 32 << 20
_DOCUMENT_LIMIT = 16 << 20  # Limit used by the API when opening a local manifest.
_MD5 = re.compile(r"[0-9a-fA-F]{32}")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){3}")
_CHUNK = "azurpromilia/pg_chunk/c000/"
_ITEMS = "azurpromilia/pg_item_v2/c000/"
_FILES = "azurpromilia/pg_item_v2/target/"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def _opener():
    return build_opener(_NoRedirect(), HTTPSHandler(context=_ssl_context()))


def _official_url(path: str, prefix: str) -> str:
    if not isinstance(path, str) or not path.startswith(prefix) or not re.fullmatch(r"[-A-Za-z0-9_./=+]+", path):
        raise AdapterError("蛮啾清单路径不属于已验证的官方 CDN 目录")
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise AdapterError("蛮啾 CDN 路径无效")
    return f"{CDN}/{path}"


def _fetch_live_config(timeout: int, salt: str) -> bytes:
    timestamp = str(time.time_ns() // 1_000_000)
    sign_payload = f"{timestamp}{_PACKAGECONFIG_QUERY}{_APP_ID}{_CHANNEL}{salt}"
    sign = hashlib.md5(sign_payload.encode("utf-8"), usedforsecurity=False).hexdigest()
    trace_id = secrets.token_hex(16)
    device_id = secrets.token_hex(16)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "identity",
        "User-Agent": f"AzurPromiliaLauncher/{_LAUNCHER_VERSION}",
        "grp-app-id": _APP_ID,
        "grp-platform": "Launcher",
        "grp-channel-code": _CHANNEL,
        "grp-sub-channel-code": _SUB_CHANNEL,
        "sdk-version": _LAUNCHER_VERSION,
        "channel-sdk-version": _LAUNCHER_VERSION,
        "grp-launcher-version-code": _LAUNCHER_VERSION,
        "lang": "zh-Hans",
        "device-id": device_id,
        "grp-trace-id": trace_id,
        "grp-client-info": json.dumps(
            {
                "device_model": "Launcher",
                "device_os": "Linux",
                "app_version": _LAUNCHER_VERSION,
                "grp_trace_id": trace_id,
                "spec_device_info": {},
            },
            separators=(",", ":"),
        ),
        "timestamp": timestamp,
        "sign": sign,
    }
    url = f"{PACKAGECONFIG_URL}?{_PACKAGECONFIG_QUERY}"
    try:
        with _opener().open(Request(url, headers=headers), timeout=timeout) as response:
            raw = response.read(_CATALOG_LIMIT + 1)
    except (OSError, URLError) as error:
        raise AdapterError("无法请求蛮啾官方 PC packageconfig 接口") from error
    if len(raw) > _CATALOG_LIMIT:
        raise AdapterError("packageconfig 文件过大")
    return raw


def _parse_config(raw: bytes) -> tuple[dict, dict[int, tuple[str, int, str]]]:
    if len(raw) > _CATALOG_LIMIT:
        raise AdapterError("packageconfig 文件过大")
    try:
        text = raw.decode("utf-8-sig")
        # A plaintext capture may contain the preceding request. Use only its response body.
        response = re.search(r"(?m)^HTTP/\d(?:\.\d)? 200[^\n]*\n", text)
        if response:
            text = re.split(r"\r?\n\r?\n", text[response.end():], maxsplit=1)[1]
        data = json.loads(text)
        if type(data["code"]) is not int or data["code"] != 0 or data["data"]["downloadMode"] != 2:
            raise ValueError
        released = data["data"]["released"]
        version, name, size = (released[k] for k in ("versionCode", "versionName", "packageSize"))
        if not _VERSION.fullmatch(version) or not name.strip() or type(size) is not int or size <= 0:
            raise ValueError
        domains = released["domainList"]
        if not isinstance(domains, list) or not any(isinstance(s, str) and s.rstrip("/") == CDN for s in domains):
            raise ValueError
        modes = {}
        for entry in released["gamePackageList"]:
            kind, url, size, md5 = (entry[k] for k in ("packageType", "downloadUrl", "fileSize", "fileMd5"))
            if type(kind) is not int or kind not in (1, 2) or kind in modes:
                raise ValueError
            if type(size) is not int or not 0 < size <= _MANIFEST_LIMIT or not _MD5.fullmatch(md5):
                raise ValueError
            modes[kind] = (_official_url(url, _CHUNK if kind == 1 else _ITEMS), size, md5.lower())
        if set(modes) != {1, 2}:
            raise ValueError
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise AdapterError("需要成功的蛮啾 packageconfig 响应（released 文件和分片清单）") from error
    return released, modes


def _read_config(path: Path) -> tuple[dict, dict[int, tuple[str, int, str]]]:
    with path.open("rb") as stream:
        raw = stream.read(_CATALOG_LIMIT + 1)
    return _parse_config(raw)


def _cipher_env() -> tuple[bytes | None, bytes | None]:
    key = os.environ.get(KEY_ENV, "").encode("utf-8")
    iv = os.environ.get(IV_ENV, "").encode("utf-8")
    if not key and not iv:
        return None, None
    if len(key) != 24 or len(iv) != 16:
        raise AdapterError(f"请在运行环境设置 {KEY_ENV}（24 字节）和 {IV_ENV}（16 字节）")
    return key, iv


def _manifest_bytes(
    spec: tuple[str, int, str], timeout: int, key: bytes | None, iv: bytes | None,
) -> bytes:
    url, size, md5 = spec
    try:
        with _opener().open(Request(url, headers={"Accept-Encoding": "identity"}), timeout=timeout) as response:
            raw = response.read(size + 1)
    except (OSError, URLError) as error:
        raise AdapterError("无法下载蛮啾官方清单") from error
    if len(raw) != size or hashlib.md5(raw, usedforsecurity=False).hexdigest() != md5:
        raise AdapterError("官方清单的大小或 MD5 与 packageconfig 不符")
    if b"," in raw:
        return raw
    if key is None or iv is None or len(key) != 24 or len(iv) != 16:
        raise AdapterError(f"请在运行环境设置 {KEY_ENV}（24 字节）和 {IV_ENV}（16 字节）")
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    try:
        encrypted = base64.b64decode(raw.strip(), validate=True)
        return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(encrypted), AES.block_size)
    except ValueError as error:
        raise AdapterError("蛮啾清单解密失败，请核对启动器随包配置") from error


def _rows(plaintext: bytes) -> list[list[str]]:
    return [s.strip().removesuffix(",").split(",") for s in plaintext.decode("utf-8-sig").splitlines() if s.strip()]


def _destination(path: str) -> str:
    path = path.replace("\\", "/")
    if any(part in {"", ".", ".."} for part in path.split("/")) or any(
        c in '<>:"|?*' or ord(c) < 32 for c in path
    ):
        raise AdapterError("蛮啾文件清单包含不安全的安装路径")
    return path


def _source(mode: str, url: str) -> dict:
    return {"source_kind": "official_sync", "source_name": f"Manjuu PC Launcher {mode}", "source_url": url}


def _candidate(url: str) -> dict:
    return {"url": url, "provider": "manjuu", "source_kind": "official", "priority": 0}


def _segments(plaintext: bytes, source: str) -> tuple[list[dict], dict]:
    header, *rows = _rows(plaintext)
    count, merged_size, merged_md5 = header
    artifacts = []
    for i, (index, part, size, md5, remote) in enumerate(rows, 1):
        if int(index) != i - 1 or int(part) != i - 1 or int(size) <= 0 or not _MD5.fullmatch(md5):
            raise AdapterError("蛮啾安装分片记录无效")
        artifacts.append({
            "kind": "package", "component": "game", "package_type": "segment", "delivery_mode": "direct",
            "name": f"pg_chunk.{i:04d}", "part": i, "size": int(size), "checksum": {"md5": md5.lower()},
            "urls": [_candidate(_official_url(remote, _CHUNK))], "source": _source("pg_chunk", source),
        })
    if not artifacts or int(count) != len(artifacts) or not _MD5.fullmatch(merged_md5) or (
        int(merged_size) != sum(a["size"] for a in artifacts)
    ):
        raise AdapterError("蛮啾分片清单的总数或总大小不符")
    return artifacts, {"count": len(artifacts), "mergedSize": int(merged_size), "mergedMd5": merged_md5.lower()}


def _files(plaintext: bytes) -> tuple[list[dict], list[str], str]:
    header, *rows = _rows(plaintext)
    count, file_count, dir_count = map(int, header)
    resources, directories, roots, seen = [], [], set(), set()
    for i, row in enumerate(rows):
        if len(row) not in {4, 5} or int(row[0]) != i:
            raise AdapterError("蛮啾文件清单记录无效")
        _, size, md5, dest, *remote = row
        path = _destination(dest)
        if path.casefold() in seen or int(size) < 0 or not _MD5.fullmatch(md5):
            raise AdapterError("蛮啾文件清单包含重复路径或无效文件属性")
        seen.add(path.casefold())
        if not remote:
            directories.append(path)
            continue
        parsed = urlsplit(remote[0])
        rpath = unquote(parsed.path)
        suffix = "/" + path
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not rpath.endswith(suffix):
            raise AdapterError("蛮啾文件清单的 CDN 路径与安装路径不匹配")
        roots.add(_official_url(rpath[:-len(suffix)], _FILES))
        resources.append({"dest": path, "md5": md5.lower(), "size": int(size)})
    if not resources or len(roots) != 1 or (len(rows), len(resources), len(directories)) != (count, file_count, dir_count):
        raise AdapterError("蛮啾文件清单的总数或 CDN 根地址不符")
    return resources, directories, roots.pop() + "/"


def _is_regular(path: Path, directory: bool = False) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        not stat.S_ISLNK(info.st_mode)
        and not (getattr(info, "st_file_attributes", 0) & 0x400)
        and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    )


def _strip_mutable(record: dict) -> dict:
    cleaned = deepcopy(record)
    if not isinstance(cleaned, dict):
        return cleaned
    cleaned.pop("is_visible", None)
    artifacts = cleaned.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            urls = artifact.get("urls")
            if isinstance(urls, list):
                for candidate in urls:
                    if isinstance(candidate, dict):
                        candidate.pop("current", None)
    return cleaned


def _live_fast_skip(output_root: Path, release: dict, specs: dict[int, tuple[str, int, str]]) -> Path | None:
    output_root = Path(output_root)
    version = release["versionCode"]
    package_size = release["packageSize"]
    manifest_url = specs[2][0]
    with DATA_LOCK:
        if not output_root.exists() and not output_root.is_symlink():
            return None
        if not _is_regular(output_root, directory=True):
            raise AdapterError("文件清单输出目录不安全")
        with data_file_lock(output_root):
            pc_dir = output_root
            for part in ("manjuu", "azurpromilia", "pc"):
                pc_dir = pc_dir / part
                if not pc_dir.exists() and not pc_dir.is_symlink():
                    return None
                if not _is_regular(pc_dir, directory=True):
                    raise AdapterError("文件清单输出目录不安全")
            for sub in (pc_dir / "manifests", pc_dir / "manifests" / version):
                if not sub.exists() and not sub.is_symlink():
                    return None
                if not _is_regular(sub, directory=True):
                    raise AdapterError("文件清单输出目录不安全")
            target = pc_dir / f"{version}.json"
            sidecar = pc_dir / "manifests" / version / "pg_item_v2.json"
            index_file = pc_dir / "index.json"
            if not (_is_regular(target) and _is_regular(sidecar) and _is_regular(index_file)):
                return None
            try:
                raw_target = target.read_bytes()
                if len(raw_target) > _DOCUMENT_LIMIT:
                    return None
                existing = json.loads(raw_target)
                validate_v2_record(existing)
                raw_sidecar = sidecar.read_bytes()
                if len(raw_sidecar) > _DOCUMENT_LIMIT:
                    return None
                doc = json.loads(raw_sidecar)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, SchemaValidationError):
                return None
            if (
                existing.get("vendor"),
                existing.get("game_id"),
                existing.get("domain_id"),
                existing.get("platform"),
                existing.get("channel"),
                existing.get("version"),
            ) != ("manjuu", "azurpromilia", "azurpromilia-pc", "windows", "official", version):
                return None
            has_manifest = any(
                isinstance(artifact, dict)
                and artifact.get("delivery_mode") == "file_manifest"
                and artifact.get("size") == package_size
                and isinstance(artifact.get("urls"), list)
                and bool(artifact["urls"])
                and isinstance(artifact["urls"][0], dict)
                and artifact["urls"][0].get("url") == manifest_url
                for artifact in existing.get("artifacts", [])
            )
            if not has_manifest:
                return None
            if (
                not isinstance(doc, dict)
                or doc.get("version") != version
                or not isinstance(doc.get("config"), dict)
                or doc["config"].get("packageSize") != package_size
            ):
                return None
            return target


def _publish(record: dict, document: dict, output_root: Path) -> Path:
    content = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode()
    if len(content) > _DOCUMENT_LIMIT:
        raise AdapterError("整理后的清单超出 GMI 文件清单读取上限")
    output_root = Path(output_root)
    with DATA_LOCK:
        if (output_root.exists() or output_root.is_symlink()) and not _is_regular(output_root, directory=True):
            raise AdapterError("文件清单输出目录不安全")
        output_root.mkdir(parents=True, exist_ok=True)
        if not _is_regular(output_root, directory=True):
            raise AdapterError("文件清单输出目录不安全")
        with data_file_lock(output_root):
            created = None
            try:
                with record_index_transaction(record, output_root) as target:
                    if target.exists():
                        try:
                            existing = json.loads(target.read_bytes())
                        except (UnicodeDecodeError, json.JSONDecodeError) as error:
                            raise AdapterError("同版本记录已存在且内容不同，未覆盖") from error
                        if _strip_mutable(existing) != _strip_mutable(record):
                            raise AdapterError("同版本记录已存在且内容不同，未覆盖")
                    folder = target.parent
                    for component in ("manifests", record["version"]):
                        folder /= component
                        if (folder.exists() or folder.is_symlink()) and not _is_regular(folder, directory=True):
                            raise AdapterError("文件清单输出目录不安全")
                        folder.mkdir(exist_ok=True)
                        if not _is_regular(folder, directory=True):
                            raise AdapterError("文件清单输出目录不安全")
                    sidecar = folder / "pg_item_v2.json"
                    if sidecar.exists() or sidecar.is_symlink():
                        if not _is_regular(sidecar) or sidecar.read_bytes() != content:
                            raise AdapterError("同版本文件清单已存在且不同或不安全，未覆盖")
                    else:
                        fd, name = tempfile.mkstemp(prefix=sidecar.name + ".", dir=folder)
                        try:
                            with os.fdopen(fd, "wb") as stream:
                                stream.write(content)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.replace(name, sidecar)
                            created = sidecar
                        finally:
                            Path(name).unlink(missing_ok=True)
                    if not target.exists():
                        write_v2_record(record, output_root)
                    return target
            except BaseException:
                if created is not None:
                    created.unlink(missing_ok=True)
                raise


def discover(
    source: str | Path = "azurpromilia",
    output_root: Path = Path("data"),
    timeout: int = 30,
) -> Path:
    if type(timeout) is not int or timeout <= 0:
        raise AdapterError("timeout 必须是正整数")
    if isinstance(source, str):
        if source != "azurpromilia":
            raise AdapterError(f"蓝色星原 PC 适配器不支持：{source}")
        salt = os.environ.get(SALT_ENV, "").strip()
        if not salt:
            raise AdapterError(f"请在运行环境设置 {SALT_ENV}")
        key, iv = _cipher_env()
        release, specs = _parse_config(_fetch_live_config(timeout, salt))
        skipped = _live_fast_skip(output_root, release, specs)
        if skipped is not None:
            return skipped
    elif isinstance(source, Path):
        key, iv = _cipher_env()
        release, specs = _read_config(source)
    else:
        raise AdapterError("source 必须是游戏 ID 字符串或本地 packageconfig 路径")
    chunk_data, files_data = (_manifest_bytes(specs[i], timeout, key, iv) for i in (1, 2))
    try:
        artifacts, chunk_info = _segments(chunk_data, specs[1][0])
        files, directories, base = _files(files_data)
    except ValueError as error:
        raise AdapterError("蛮啾清单格式与已验证的启动器格式不一致") from error
    version, size = release["versionCode"], sum(f["size"] for f in files)
    if size != release["packageSize"]:
        raise AdapterError("文件总大小与官方 packageconfig 不符")
    record = {
        "schema_version": 2, "vendor": "manjuu", "game_id": "azurpromilia", "domain_id": "azurpromilia-pc",
        "platform": "windows", "channel": "official", "version": version, "version_code": version,
        "file_time": None, "artifacts": artifacts, "references": [], "provenance": _source("packageconfig", PACKAGECONFIG_URL),
    }
    artifacts.append({
        "kind": "package", "component": "game", "package_type": "full", "delivery_mode": "file_manifest",
        "name": f"AzurPromilia-{version}-pg_item_v2", "size": size, "decompressed_size": size,
        "manifest": {"path": f"manifests/{version}/pg_item_v2.json", "base_urls": [_candidate(base)]},
        "urls": [_candidate(specs[2][0])], "source": _source("pg_item_v2", specs[2][0]),
    })
    for artifact in artifacts:
        artifact["artifact_id"] = artifact_id(artifact, record)
    try:
        validate_v2_record(record)
    except SchemaValidationError as error:
        raise AdapterError(f"生成的 schema v2 记录无效：{error}") from error
    document = {
        "schema_version": 1, "vendor": "manjuu", "game_id": "azurpromilia", "platform": "windows", "version": version,
        "resource": files, "deleteFiles": [],
        "config": {
            "versionCode": version, "versionName": release["versionName"], "packageSize": size, "downloadMode": 2,
            "pg_chunk": chunk_info,
            "pg_item_v2": {"recordCount": len(files) + len(directories), "fileCount": len(files),
                           "directoryCount": len(directories), "directories": directories},
            "manifestChecksums": [
                {"mode": mode, "plaintextSha256": hashlib.sha256(blob).hexdigest(), "plaintextBytes": len(blob)}
                for mode, blob in (("pg_chunk", chunk_data), ("pg_item_v2", files_data))
            ],
        },
        "provenance": _source("pg_item_v2", specs[2][0]),
    }
    return _publish(record, document, output_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="蓝色星原：旅谣 国服 PC 官方清单在线发现与本地抓包导入",
        epilog=(
            f"在线请求需要设置 {SALT_ENV}；若官方清单启用加密，还需设置 {KEY_ENV} 和 {IV_ENV}。"
        ),
    )
    parser.add_argument(
        "--packageconfig", type=Path, default=None,
        help="可选：官方 JSON 响应或包含该响应的本地 HTTP 文本抓包；省略时直接请求官方接口",
    )
    parser.add_argument("--output-root", type=Path, default=Path("data"), help="GMI 数据根目录")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    source: str | Path = "azurpromilia" if args.packageconfig is None else args.packageconfig
    try:
        print(discover(source, args.output_root, args.timeout).resolve())
        return 0
    except (AdapterError, OSError, ValueError) as error:
        return print_error(error)


if __name__ == "__main__":
    raise SystemExit(main())
