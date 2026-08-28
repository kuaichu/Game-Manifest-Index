from urllib.parse import urlsplit

NAME = "hypergryph_endfield_hycdn"
URL_TIME = False


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (not vendor or vendor == "hypergryph") and (not game_id or game_id == "endfield") and urlsplit(url).hostname == "beyond.hycdn.cn"
