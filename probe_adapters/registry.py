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
def infer_platform(vendor: str | None, game_id: str | None, url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    if path.endswith(".apk"):
        return "android"
    raise ProbeError(f"无法安全推断探活平台：{vendor or '-'} / {game_id or '-'} / {url}")


def adapter_for(
    vendor: str | None,
    game_id: str | None,
    url: str,
    platform: str | None = None,
) -> ModuleType:
    if platform is None:
        platform = infer_platform(vendor, game_id, url)
    if platform not in {None, "android"}:
        raise ProbeError(f"不支持的探活平台：{platform}")
    matches = [adapter for adapter in ANDROID_ADAPTERS if adapter.matches(vendor, game_id, url)]
    if len(matches) == 1:
        return matches[0]
    if not matches and shared_generic_apk.matches(vendor, game_id, url):
        return shared_generic_apk
    if len(matches) > 1:
        raise ProbeError(f"URL 同时匹配多个探活适配器：{url}")
    raise ProbeError(f"没有匹配的探活适配器：{vendor or '-'} / {game_id or '-'} / {platform or 'android'} / {url}")
