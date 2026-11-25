"""Hypergryph official Android APK collection and canonical organization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from url_adapters.android.apk_v2_organizer import build_official_apk_v2_record


class HypergryphApkOrganizationError(ValueError):
    """Raised when a Hypergryph APK observation is not a valid v2 record."""


def _canonical_endfield_apk_url(game_id: str, value: str) -> str:
    parsed = urlsplit(value)
    if (
        game_id == "endfield"
        and parsed.hostname == "beyond.hycdn.cn"
        and "/Android/" in parsed.path
        and parsed.path.lower().endswith(".apk")
    ):
        return urlunsplit((
            "https",
            "beyond-prod.oss-cn-shanghai.aliyuncs.com",
            parsed.path,
            "",
            "",
        ))
    return value


@dataclass(frozen=True)
class HypergryphApkCollection:
    source_url: str
    record: Mapping[str, Any]
    source_name: str = "Hypergryph official Android launcher"


def organize_hypergryph_apk(collection: HypergryphApkCollection) -> dict[str, Any]:
    """Turn one Hypergryph launcher observation into one valid v2 record."""
    return build_official_apk_v2_record(
        collection,
        collection_cls=HypergryphApkCollection,
        error_cls=HypergryphApkOrganizationError,
        vendor="hypergryph",
        vendor_label="Hypergryph",
        allowed_game_ids={"arknights", "endfield"},
        game_id_error="只支持鹰角 Android 游戏的 APK 采集结果",
        canonical_url_resolver=_canonical_endfield_apk_url,
    )


__all__ = [
    "HypergryphApkCollection",
    "HypergryphApkOrganizationError",
    "organize_hypergryph_apk",
]
