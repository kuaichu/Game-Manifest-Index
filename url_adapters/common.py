"""Shared endpoint reader and version JSON writer for URL import adapters."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from urllib.parse import unquote, urlsplit

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

class AdapterError(RuntimeError):
    pass


def endpoint(vendor: str, game_id: str) -> str:
    path = Path(__file__).with_name("endpoints.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        url = data[vendor][game_id]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AdapterError(f"无法读取请求 URL：{vendor}/{game_id}") from exc
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise AdapterError(f"请求 URL 无效：{vendor}/{game_id}")
    return url


def add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", help="URL 中没有版本时手工指定")
    parser.add_argument("--version-code", type=int)
    parser.add_argument("--output-root", type=Path, default=Path("data"))
    parser.add_argument("--timeout", type=int, default=30)


def curl(args: list[str], timeout: int) -> str:
    command = ["curl", "-sS", "--connect-timeout", "10", "--max-time", str(timeout), *args]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise AdapterError("系统中没有找到 curl") from exc
    output = result.stdout.decode("latin-1", errors="replace")
    error = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode:
        raise AdapterError(f"curl 失败（{result.returncode}）：{error}")
    return output


def read_small(url: str, timeout: int) -> str:
    return curl(["--fail", "--max-filesize", "1048576", url], timeout)


def version_from_url(url: str) -> str | None:
    path = unquote(urlsplit(url).path)
    matches = re.findall(r"(?<!\d)v?(\d+)[._](\d+)(?:[._](\d+))?(?!\d)", path, re.I)
    if not matches:
        return None
    return ".".join(part for part in matches[-1] if part)


def probe_record(
    vendor: str, game_id: str, url: str, *, version: str | None = None,
    version_code: int | None = None, timeout: int = 30,
    platform: str = "android",
    version_parser: Callable[[str], str | None] | None = None,
) -> dict:
    if platform not in (None, "android"):
        raise AdapterError(f"APK 适配器不支持探测平台：{platform}")
    try:
        # Probe adapters are an optional later-stage dependency.  Keep this
        # import lazy so URL organizers and pure unit tests remain importable.
        from probe_adapters.common import ProbeError
        from probe_adapters.service import probe
        result = probe(url, vendor=vendor, game_id=game_id, platform=platform, timeout=timeout)
    except ImportError as error:
        raise AdapterError("APK 探测依赖未安装") from error
    except ProbeError as error:
        raise AdapterError(str(error)) from error
    version = version or (version_parser(result["filename"]) if version_parser else None)
    version = version or version_from_url(result["url"])
    if not version:
        raise AdapterError("URL 中没有可靠版本号，请使用 --version 指定")
    return {
        "vendor": vendor, "game_id": game_id, "platform": "android",
        "channel": "official", "version": version, "version_code": version_code,
        "filename": result["filename"], "url": result["url"], "size": result["size"],
        "checksum": {"etag": result["etag"], "crc64": result["crc64"], "md5": result["md5"]},
        "file_time": result["file_time"],
        "status": {
            "http_code": result["http_code"],
            "available": result["available"],
            "last_checked_at": result["checked_at"],
        },
    }


def fetch_record(
    vendor: str, game_id: str, url: str, *, version: str | None = None,
    version_code: int | None = None, timeout: int = 30,
    platform: str = "android",
    version_parser: Callable[[str], str | None] | None = None,
) -> dict:
    record = probe_record(
        vendor, game_id, url, version=version, version_code=version_code,
        timeout=timeout, platform=platform, version_parser=version_parser,
    )
    if record["status"]["available"] is not True:
        raise AdapterError(
            f"未确认可用 APK：HTTP {record['status']['http_code']}，{record['filename'] or 'unknown'}"
        )
    return record


def print_error(error: Exception) -> int:
    print(f"探测失败：{error}", file=sys.stderr)
    return 1
