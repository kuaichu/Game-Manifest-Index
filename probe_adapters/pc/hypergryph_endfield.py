"""Probe adapter for historical Endfield Windows archives and resources."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from probe_adapters.pc.mihoyo_package_common import availability as archive_availability


NAME = "hypergryph_endfield_pc"
URL_TIME = False

_BEYOND_ARCHIVE = r"[A-Za-z0-9._-]*Beyond_Release_[A-Za-z0-9._-]+\.zip\.\d{3}"
_TOKEN_PATCH_ARCHIVE = r"[A-Za-z0-9.]+(?:_[A-Za-z0-9]+){5,}\.zip\.\d{3}"
_OFFICIAL_ARCHIVE_PATH = re.compile(
    r"/[A-Za-z0-9]+/\d+\.\d+/update/1/1/Windows/[A-Za-z0-9._-]+/"
    r"(?:packs/" + _BEYOND_ARCHIVE
    + r"|patches(?:/[A-Za-z0-9._-]+){1,3}/(?:"
    + _BEYOND_ARCHIVE + "|" + _TOKEN_PATCH_ARCHIVE + r"))"
)
_OFFICIAL_RESOURCE_PATH = re.compile(
    r"/[A-Za-z0-9]+/\d+\.\d+/resource/Windows/(?:initial|main)/[A-Za-z0-9._-]+/"
    r"files/VFS/[0-9A-F]{8}/(?:[0-9A-F]{8}\.blc|[0-9A-F]{32}\.chk)"
)
_MIRROR_PATH = re.compile(
    r"/AetherArchive/beyond-hg-archive/releases/download/[A-Za-z0-9._-]+/(?:"
    + _BEYOND_ARCHIVE + "|" + _TOKEN_PATCH_ARCHIVE + r")"
)


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (vendor and vendor != "hypergryph")
        or (game_id and game_id != "endfield")
    ):
        return False
    if parsed.hostname == "beyond.hycdn.cn":
        return bool(
            _OFFICIAL_ARCHIVE_PATH.fullmatch(parsed.path)
            or _OFFICIAL_RESOURCE_PATH.fullmatch(parsed.path)
        )
    return parsed.hostname == "github.com" and _MIRROR_PATH.fullmatch(parsed.path) is not None


def availability(
    status: int,
    filename: str,
    prefix: bytes,
    *,
    observed_size: int | None = None,
    expected_size: int | None = None,
    **kwargs: object,
) -> bool | None:
    if filename.lower().endswith((".chk", ".blc")):
        if status in {404, 410}:
            return False
        if status not in {200, 206}:
            return None
        if observed_size is None or expected_size is None:
            return None
        return True if observed_size == expected_size else None
    return archive_availability(
        status,
        filename,
        prefix,
        observed_size=observed_size,
        expected_size=expected_size,
        **kwargs,
    )
