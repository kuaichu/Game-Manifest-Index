from urllib.parse import urlsplit

NAME = "mihoyo_autopatch"
URL_TIME = True
GAME_HOSTS = {
    "hk4e": "autopatchcn.yuanshen.com",
    "hkrpg": "autopatchcn.bhsr.com",
    "nap": "autopatchcn.juequling.com",
}



def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    host = urlsplit(url).hostname
    return (
        (not vendor or vendor == "mihoyo")
        and (host in GAME_HOSTS.values() if game_id is None else host == GAME_HOSTS.get(game_id))
        and urlsplit(url).path.lower().endswith(".apk")
    )


def availability(status: int, filename: str, prefix: bytes) -> bool | None:
    if status in {404, 410}:
        return False
    if status not in {200, 206}:
        return None
    name = filename.lower()
    if not name.endswith(".apk"):
        return None
    return prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
