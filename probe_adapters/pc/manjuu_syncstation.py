"""Probe adapter for official Manjuu Azur Promilia PC CDN URLs."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

NAME = "manjuu_syncstation_pc"
URL_TIME = True
HOSTS = {"syncstation.manjuu.com", "l2-syncstation.manjuu.com"}
_PREFIXES = ("/azurpromilia/pg_chunk/c000/", "/azurpromilia/pg_item_v2/c000/")


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    if not isinstance(url, str) or "?" in url or "#" in url:
        return False
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
        or parsed.query
        or parsed.fragment
        or (vendor and vendor != "manjuu")
        or (game_id and game_id != "azurpromilia")
        or parsed.hostname not in HOSTS
        or not parsed.path.startswith(_PREFIXES)
    ):
        return False
    raw_segments = parsed.path.split("/")[1:]
    decoded_segments = unquote(parsed.path).split("/")[1:]
    if len(raw_segments) < 4 or len(decoded_segments) < 4:
        return False
    if any(seg in {"", ".", ".."} for seg in (*raw_segments, *decoded_segments)):
        return False
    return not decoded_segments[-1].lower().endswith(".apk")


def availability(
    status: int,
    filename: str,
    prefix: bytes,
    *,
    observed_size: int | None = None,
    expected_size: int | None = None,
    **_: object,
) -> bool | None:
    low = prefix.lower()
    if status in {404, 410} or (status in {200, 206} and (b"<html" in low or b"<!doctype" in low)):
        return False
    if status not in {200, 206} or len(prefix) == 0:
        return None
    if (
        not isinstance(expected_size, bool)
        and isinstance(expected_size, int)
        and expected_size > 0
        and not isinstance(observed_size, bool)
        and isinstance(observed_size, int)
        and observed_size != expected_size
    ):
        return None
    return True
