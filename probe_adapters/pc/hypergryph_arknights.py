"""Probe adapter for official Arknights Windows package segments."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from probe_adapters.pc.mihoyo_package_common import availability


NAME = "hypergryph_arknights_pc"
URL_TIME = False

_PACKAGE_PATH = re.compile(
    r"/[A-Za-z0-9]+/\d+\.\d+/update/1/1/Windows/[A-Za-z0-9._-]+/packs/"
    r"production_[A-Za-z0-9._-]+\.zip\.\d{3}"
)


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and (not vendor or vendor == "hypergryph")
        and (not game_id or game_id == "arknights")
        and parsed.hostname == "ak.hycdn.cn"
        and _PACKAGE_PATH.fullmatch(parsed.path) is not None
    )
