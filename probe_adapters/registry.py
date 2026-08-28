"""Dispatch a direct URL to exactly one vendor and URL-type probe adapter."""

from __future__ import annotations

from types import ModuleType
from urllib.parse import urlsplit

from probe_adapters.android import (
    hypergryph_arknights_hycdn,
    hypergryph_endfield_hycdn,
    kuro_pns_txcdn,
    kuro_wuwa_mc_cdn,
    mihoyo_autopatch,
    mihoyo_bh2_benghuai,
    mihoyo_bh3_cdn,
    perfectworld_webops,
    shared_generic_apk,
)
from probe_adapters.common import ProbeError
from probe_adapters.pc import (
    kuro_cdn,
    mihoyo_autopatch as pc_mihoyo_autopatch,
    mihoyo_bh3_cdn as pc_mihoyo_bh3_cdn,
    perfectworld_patcher,
)


ANDROID_ADAPTERS = (
    mihoyo_autopatch,
    mihoyo_bh3_cdn,
    mihoyo_bh2_benghuai,
    hypergryph_arknights_hycdn,
    hypergryph_endfield_hycdn,
    kuro_wuwa_mc_cdn,
    kuro_pns_txcdn,
    perfectworld_webops,
)
PC_ADAPTERS = (pc_mihoyo_autopatch, pc_mihoyo_bh3_cdn, kuro_cdn, perfectworld_patcher)


def _valid_platform(platform: str | None) -> str | None:
    if platform == "pc":
        return "windows"
    if platform in {None, "android", "windows"}:
        return platform
    raise ProbeError(f"不支持的探活平台：{platform}")


def infer_platform(vendor: str | None, game_id: str | None, url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if path.endswith(".apk"):
        return "android"
    pc_matches = [adapter for adapter in PC_ADAPTERS if adapter.matches(vendor, game_id, url)]
    if len(pc_matches) == 1:
        return "windows"
    if len(pc_matches) > 1:
        raise ProbeError(f"URL 同时匹配多个 PC 探活适配器：{url}")
    raise ProbeError(f"无法安全推断探活平台：{vendor or '-'} / {game_id or '-'} / {url}")


def adapter_for(
    vendor: str | None,
    game_id: str | None,
    url: str,
    platform: str | None = None,
) -> ModuleType:
    platform = _valid_platform(platform)
    if platform is None:
        platform = infer_platform(vendor, game_id, url)
    adapters = ANDROID_ADAPTERS if platform == "android" else PC_ADAPTERS
    matches = [adapter for adapter in adapters if adapter.matches(vendor, game_id, url)]
    if len(matches) == 1:
        return matches[0]
    if platform == "android" and not matches and shared_generic_apk.matches(vendor, game_id, url):
        return shared_generic_apk
    if len(matches) > 1:
        raise ProbeError(f"URL 同时匹配多个探活适配器：{url}")
    raise ProbeError(f"没有匹配的探活适配器：{vendor or '-'} / {game_id or '-'} / {platform} / {url}")
