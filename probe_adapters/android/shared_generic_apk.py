from urllib.parse import urlsplit

NAME = "shared_generic_apk"
URL_TIME = False


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (
        not vendor
        and not game_id
        and urlsplit(url).scheme in {"http", "https"}
        and urlsplit(url).path.lower().endswith(".apk")
    )
