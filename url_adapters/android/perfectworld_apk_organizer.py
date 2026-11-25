"""Perfect World official Android APK collection and canonical organization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from url_adapters.android.apk_v2_organizer import build_official_apk_v2_record


class PerfectWorldApkOrganizationError(ValueError):
    """Raised when a Perfect World APK observation is not a valid v2 record."""


@dataclass(frozen=True)
class PerfectWorldApkCollection:
    source_url: str
    record: Mapping[str, Any]
    source_name: str = "Perfect World official gameDownload Android page"


def organize_perfectworld_apk(collection: PerfectWorldApkCollection) -> dict[str, Any]:
    """Turn one Perfect World gameDownload observation into one v2 record."""
    return build_official_apk_v2_record(
        collection,
        collection_cls=PerfectWorldApkCollection,
        error_cls=PerfectWorldApkOrganizationError,
        vendor="perfectworld",
        vendor_label="Perfect World",
        allowed_game_ids={"nte", "p5x", "tof"},
        game_id_error="只支持完美世界 Android 游戏的 APK 采集结果",
    )


__all__ = [
    "PerfectWorldApkCollection",
    "PerfectWorldApkOrganizationError",
    "organize_perfectworld_apk",
]
