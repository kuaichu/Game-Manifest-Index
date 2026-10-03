"""Probe adapter for historical Endfield Windows archives and resources."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from probe_adapters.pc.mihoyo_package_common import availability as archive_availability
from probe_adapters.common import ProbeError


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
_AUTH_QUERY = re.compile(r"auth_key=[0-9]{10}-[0-9a-fA-F]{32}-[0-9]+-[0-9a-fA-F]{32}")


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    if any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return False
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
        or parsed.fragment
        or (vendor and vendor != "hypergryph")
        or (game_id and game_id != "endfield")
    ):
        return False
    if parsed.hostname == "beyond.hycdn.cn":
        if parsed.query:
            return bool(_OFFICIAL_ARCHIVE_PATH.fullmatch(parsed.path)
                        and _AUTH_QUERY.fullmatch(parsed.query))
        return bool(
            _OFFICIAL_ARCHIVE_PATH.fullmatch(parsed.path)
            or _OFFICIAL_RESOURCE_PATH.fullmatch(parsed.path)
        )
    if parsed.hostname == "beyond-prod.oss-cn-shanghai.aliyuncs.com":
        return ("?" not in url and "#" not in url
                and parsed.path.startswith("/6LL0KJuqHBVz33WK/")
                and all(segment not in {".", ".."} for segment in parsed.path.split("/"))
                and _OFFICIAL_ARCHIVE_PATH.fullmatch(parsed.path) is not None)
    return (not parsed.query and parsed.hostname == "github.com"
            and _MIRROR_PATH.fullmatch(parsed.path) is not None)


def preflight(url: str, **_: object) -> None:
    """Reject Endfield runtime files before any network transport is attempted."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.hostname == "beyond.hycdn.cn" and _OFFICIAL_RESOURCE_PATH.fullmatch(parsed.path):
        raise ProbeError("Endfield 运行时资源不参与探活")
    return None


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
        return None
    return archive_availability(
        status,
        filename,
        prefix,
        observed_size=observed_size,
        expected_size=expected_size,
        **kwargs,
    )
