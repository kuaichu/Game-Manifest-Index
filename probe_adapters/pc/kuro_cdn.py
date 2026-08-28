"""Probe adapter for official Wuthering Waves PC CDN URLs."""
from pathlib import PurePosixPath
from urllib.parse import urlsplit

NAME = "kuro_cdn"
URL_TIME = True
HOSTS = {
    "pcdownload-aliyun.aki-game.com",
    "pcdownload-huoshan.aki-game.com",
    "pcdownload-qcloud.aki-game.com",
    "prod-cn-alicdn-gamestarter.kurogame.com",
}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return False
    filename = PurePosixPath(p.path).name.lower()
    return (
        p.scheme == "https"
        and port in (None, 443)
        and p.username is None
        and p.password is None
        and not p.query
        and not p.fragment
        and (not vendor or vendor == "kuro")
        and (not game_id or game_id == "wuwa")
        and p.hostname in HOSTS
        and filename in {"indexfile.json", "resource.json"}
    )


def availability(status: int, filename: str, prefix: bytes, **_: object) -> bool | None:
    return True if status in {200, 206} else False if status in {404, 410} else None
