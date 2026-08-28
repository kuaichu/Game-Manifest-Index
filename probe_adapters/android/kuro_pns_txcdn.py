from urllib.parse import urlsplit

NAME = "kuro_pns_txcdn"
URL_TIME = True


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (
        (not vendor or vendor == "kuro")
        and (not game_id or game_id == "pns")
        and urlsplit(url).hostname in {
            "zspms-txcdn-media.kurogame.com",
            "media-cdn-zspms.kurogame.com",
        }
    )
