from urllib.parse import urlsplit

NAME = "perfectworld_webops"
URL_TIME = True
GAMES = {"p5x", "nte", "tof"}
HOSTS = {"p5xapk.wmupd.com", "yhapk.wmupd.com", "htapk.wmupd.com"}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (not vendor or vendor == "perfectworld") and (not game_id or game_id in GAMES) and urlsplit(url).hostname in HOSTS
