from urllib.parse import urlsplit

NAME = "kuro_wuwa_mc_cdn"
URL_TIME = True
HOSTS = {
    "mirrors-package-mc.aki-game.com",
    "mirrors-package-mc.kurogame.com",
    "mirrors2-package-mc.aki-game.com",
}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (not vendor or vendor == "kuro") and (not game_id or game_id == "wuwa") and urlsplit(url).hostname in HOSTS
