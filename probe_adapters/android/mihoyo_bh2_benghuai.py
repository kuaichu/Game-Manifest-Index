from urllib.parse import urlsplit

NAME = "mihoyo_bh2_benghuai"
URL_TIME = False


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (not vendor or vendor == "mihoyo") and (not game_id or game_id == "bh2") and urlsplit(url).hostname == "static.benghuai.com"
