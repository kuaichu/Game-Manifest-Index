"""Centralized registry of canonical vendors, games, enums, and official CDN hosts."""

from __future__ import annotations


VENDORS: tuple[str, ...] = ("mihoyo", "hypergryph", "kuro", "perfectworld", "manjuu")
PLATFORMS: tuple[tuple[str, str], ...] = (("android", "android"), ("pc", "windows"))
ARTIFACT_KINDS: frozenset[str] = frozenset({"apk", "package", "patch", "resource"})
TREE_KINDS: frozenset[str] = ARTIFACT_KINDS | {"all", "file"}
AVAILABILITY_STATES: frozenset[str] = frozenset({"available", "unavailable", "unknown"})
COMPARE_SCOPES: frozenset[str] = frozenset({"artifacts", "files"})

GAME_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("hk4e", "原神", "Genshin Impact"),
    ("hkrpg", "崩坏：星穹铁道", "Honkai: Star Rail"),
    ("nap", "绝区零", "Zenless Zone Zero"),
    ("bh3", "崩坏3", "Honkai Impact 3rd"),
    ("bh2", "崩坏学园2", "Houkai Gakuen 2"),
    ("arknights", "明日方舟", "Arknights"),
    ("endfield", "明日方舟：终末地", "Arknights: Endfield"),
    ("wuwa", "鸣潮", "Wuthering Waves"),
    ("pns", "战双帕弥什", "Punishing: Gray Raven"),
    ("nte", "异环", "Neverness to Everness"),
    ("tof", "幻塔", "Tower of Fantasy"),
    ("p5x", "女神异闻录：夜幕魅影", "Persona 5: The Phantom X"),
    ("azurpromilia", "蓝色星原：旅谣", "Azur Promilia"),
)
GAME_IDS: frozenset[str] = frozenset(item[0] for item in GAME_CATALOG)

LOCAL_OFFICIAL_HOSTS: dict[str, frozenset[str]] = {
    "kuro": frozenset(
        {
            "pcdownload-aliyun.aki-game.com",
            "pcdownload-huoshan.aki-game.com",
            "pcdownload-qcloud.aki-game.com",
        }
    ),
    "perfectworld": frozenset(
        {
            "yhcdn1.wmupd.com",
            "nsywl-client-dev1.wmupd.com",
            "htcdn1.wmupd.com",
        }
    ),
    "manjuu": frozenset({"syncstation.manjuu.com", "l2-syncstation.manjuu.com"}),
}

OFFICIAL_SOPHON_HOSTS: frozenset[str] = frozenset(
    {
        "autopatchcn.yuanshen.com",
        "autopatchcn.bhsr.com",
        "autopatchcn.juequling.com",
        "autopatchcn.bh3.com",
    }
)

OFFICIAL_PACKAGE_HOSTS: frozenset[str] = frozenset(
    {
        "autopatchcn.yuanshen.com",
        "autopatchcn.bhsr.com",
        "autopatchcn.juequling.com",
        "autopatchcn.bh3.com",
        "bundle.bh3.com",
    }
)

PACKAGE_HOSTS_BY_GAME: dict[str, frozenset[str]] = {
    "hk4e": frozenset({"autopatchcn.yuanshen.com"}),
    "hkrpg": frozenset({"autopatchcn.bhsr.com"}),
    "nap": frozenset({"autopatchcn.juequling.com"}),
    "bh3": frozenset({"autopatchcn.bh3.com", "bundle.bh3.com"}),
}


__all__ = [
    "ARTIFACT_KINDS",
    "AVAILABILITY_STATES",
    "COMPARE_SCOPES",
    "GAME_CATALOG",
    "GAME_IDS",
    "LOCAL_OFFICIAL_HOSTS",
    "OFFICIAL_PACKAGE_HOSTS",
    "OFFICIAL_SOPHON_HOSTS",
    "PACKAGE_HOSTS_BY_GAME",
    "PLATFORMS",
    "TREE_KINDS",
    "VENDORS",
]
