"""HoYo PC package probe adapter for Genshin, Star Rail and Zenless."""
import re
from urllib.parse import urlsplit
from probe_adapters.pc.mihoyo_package_common import availability

NAME = "mihoyo_autopatch"
URL_TIME = True
GAME_HOSTS = {"hk4e": "autopatchcn.yuanshen.com", "hkrpg": "autopatchcn.bhsr.com", "nap": "autopatchcn.juequling.com"}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
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
    if vendor and vendor != "mihoyo":
        return False
    host = p.hostname
    if game_id is not None and host != GAME_HOSTS.get(game_id):
        return False
    if game_id is None and host not in GAME_HOSTS.values():
        return False
    return bool(p.path.lower().endswith((".zip", ".7z", ".bin")) or re.search(r"\.(?:zip|7z)\.\d+$", p.path.lower()))
