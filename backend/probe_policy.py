"""Shared live-probe evidence freshness policy and deterministic public IDs."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any


# Live-probe evidence for URLs in the scheduled rotation counts as verified
# for 20 hours after checked_at, then stays visible as stale. Terminal or
# otherwise excluded URLs retain their concrete state without a stale timer.
PROBE_EVIDENCE_TTL = timedelta(hours=20)
PROBE_CHECKED_AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def parse_probe_checked_at(current: Mapping[str, Any]) -> tuple[str, datetime] | None:
    """Parse ``current['checked_at']`` when written as a UTC ISO-8601 probe timestamp."""
    value = current.get("checked_at")
    if not isinstance(value, str) or PROBE_CHECKED_AT_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.utcoffset() != timedelta(0):
        return None
    return value, parsed


def stable_id(*parts: object) -> int:
    """Return a deterministic 48-bit integer ID from ``parts``."""
    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:12], 16)


def stable_url_id(artifact_id: str, url_index: int, url: str) -> int:
    """Return the deterministic public URL candidate ID for an artifact URL."""
    return stable_id(artifact_id, url_index, url)


__all__ = [
    "PROBE_CHECKED_AT_RE",
    "PROBE_EVIDENCE_TTL",
    "parse_probe_checked_at",
    "stable_id",
    "stable_url_id",
]
