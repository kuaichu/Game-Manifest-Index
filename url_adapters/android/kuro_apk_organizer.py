"""Kuro official Android APK collection and canonical organization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from url_adapters.android.apk_v2_organizer import build_official_apk_v2_record


class KuroApkOrganizationError(ValueError):
    """Raised when a Kuro APK observation is not a valid v2 record."""


@dataclass(frozen=True)
class KuroApkCollection:
    source_url: str
    record: Mapping[str, Any]
    source_name: str = "Kuro official Android download manifest"


def organize_kuro_apk(collection: KuroApkCollection) -> dict[str, Any]:
    """Turn one Kuro manifest observation into one strictly valid v2 record."""
    return build_official_apk_v2_record(
        collection,
        collection_cls=KuroApkCollection,
        error_cls=KuroApkOrganizationError,
        vendor="kuro",
        vendor_label="Kuro",
        allowed_game_ids={"wuwa", "pns"},
        game_id_error="只支持 Kuro Android 游戏的 APK 采集结果",
    )


__all__ = [
    "KuroApkCollection",
    "KuroApkOrganizationError",
    "organize_kuro_apk",
]
