"""Shared bounded-content availability rules for HoYo PC packages."""
from __future__ import annotations

import re

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
SEVEN_Z_SIGNATURE = b"7z\xbc\xaf\x27\x1c"


def availability(status: int, filename: str, prefix: bytes, *, observed_size: int | None = None,
                 expected_size: int | None = None, **_: object) -> bool | None:
    if status in {404, 410}:
        return False
    if status not in {200, 206}:
        return None
    name = filename.lower()
    split = re.search(r"\.(zip|7z)\.(\d+)$", name)
    if name.endswith(".zip") or (split and split.group(1) == "zip" and int(split.group(2)) == 1):
        return prefix.startswith(ZIP_SIGNATURES)
    if name.endswith(".7z") or (split and split.group(1) == "7z" and int(split.group(2)) == 1):
        return prefix.startswith(SEVEN_Z_SIGNATURE)
    if split and int(split.group(2)) > 1:
        return None if expected_size is None or observed_size is None else observed_size == expected_size
    return None
