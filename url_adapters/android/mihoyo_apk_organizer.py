"""MiHoYo Android APK collection to canonical schema v2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from url_adapters.android.apk_v2_organizer import build_official_apk_v2_record


class MihoyoApkOrganizationError(ValueError):
    """Raised when a collection cannot be represented as one v2 APK record."""


@dataclass(frozen=True)
class MihoyoApkCollection:
    """The official entry URL plus the probe-owned observation."""

    source_url: str
    record: Mapping[str, Any]
    source_name: str = "MiHoYo official Android download_porter"


def organize_apk(collection: MihoyoApkCollection) -> dict[str, Any]:
    """Build and strictly validate one official MiHoYo Android APK record."""
    return build_official_apk_v2_record(
        collection,
        collection_cls=MihoyoApkCollection,
        error_cls=MihoyoApkOrganizationError,
        vendor="mihoyo",
        vendor_label="MiHoYo",
        channel_error="只支持 channel=official 的米哈游 APK 采集结果",
    )


__all__ = [
    "MihoyoApkCollection",
    "MihoyoApkOrganizationError",
    "organize_apk",
]
