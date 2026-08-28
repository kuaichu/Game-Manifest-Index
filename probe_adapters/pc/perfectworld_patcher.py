"""Probe policy for official Perfect World PC discovery URLs."""
from urllib.parse import urlsplit
from url_adapters.pc.perfectworld_patcher import PROFILES, VERSION_RE

NAME = "perfectworld_patcher"
URL_TIME = False
_HOSTS = {p.host for p in PROFILES.values()}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    if vendor and vendor != "perfectworld" or game_id and game_id not in PROFILES:
        return False
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return False
    if (
        p.scheme != "https"
        or port not in (None, 443)
        or p.username is not None
        or p.password is not None
        or p.query
        or p.fragment
    ):
        return False
    for profile in PROFILES.values():
        if p.hostname != profile.host or (game_id and game_id != profile.game_id):
            continue
        config = profile.base_path + "/Version/Windows/config.xml"
        if p.path == config:
            return True
        prefix = profile.base_path + "/Version/Windows/version/"
        if p.path.startswith(prefix) and p.path.endswith("/ResList.bin.zip"):
            version = p.path[len(prefix):-len("/ResList.bin.zip")]
            return bool(VERSION_RE.fullmatch(version))
    return False


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
