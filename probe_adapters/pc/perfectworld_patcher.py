"""Probe policy for official Perfect World PC discovery URLs."""
from url_adapters.pc.perfectworld_patcher import PROFILES, manifest_profile_for_url

NAME = "perfectworld_patcher"
URL_TIME = False


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    if vendor and vendor != "perfectworld" or game_id and game_id not in PROFILES:
        return False
    return manifest_profile_for_url(url, game_id) is not None


def availability(status: int, filename: str, prefix: bytes, **_: object) -> bool | None:
    if status in {404, 410}:
        return False
    if status not in {200, 206}:
        return None
    low = filename.lower()
    if low == "config.xml":
        return False if b"<html" in prefix.lower() or b"<!doctype" in prefix.lower() else True
    if low == "reslist.bin.zip" and prefix.startswith(b"PK"):
        return True
    return False if b"<html" in prefix.lower() or b"<!doctype" in prefix.lower() else None
