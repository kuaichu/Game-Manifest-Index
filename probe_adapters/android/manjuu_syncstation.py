"""Probe policy for official Manjuu Azur Promilia Android APK URLs."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

NAME = "manjuu_syncstation"
URL_TIME = True
HOSTS = {"syncstation.manjuu.com", "l2-syncstation.manjuu.com"}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return False
    if "?" in url or "#" in url:
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
    ):
        return False
    if any(segment in {".", ".."} for segment in unquote(parsed.path).split("/")):
        return False
    low_path = parsed.path.lower()
    return low_path.startswith("/azurpromilia/android/") and low_path.endswith(".apk")


def availability(status: int, filename: str, prefix: bytes, **_: object) -> bool | None:
    if status in {404, 410}:
        return False
    if status not in {200, 206}:
        return None
    low_prefix = prefix.lower()
    if b"<html" in low_prefix or b"<!doctype" in low_prefix:
        return False
    if filename.lower().endswith(".apk") and prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return True
    return None
