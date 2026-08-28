"""HoYo PC package probe adapter for Honkai Impact 3rd."""
import re
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from probe_adapters.pc.mihoyo_package_common import availability

NAME = "mihoyo_bh3_cdn"
URL_TIME = True
HOSTS = {"app.bh3.com", "bundle.bh3.com", "autopatchcn.bh3.com"}


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        return False
    if (
        p.scheme != "https"
        or port not in (None, 443)
        or p.username is not None
        or p.password is not None
        or p.query
        or p.fragment
    ):
        return False
    path = p.path.lower()
    supported_path = path.endswith((".zip", ".7z", ".bin")) or re.search(
        r"\.(?:zip|7z)\.\d+$", path,
    )
    return (
        (not vendor or vendor == "mihoyo")
        and (not game_id or game_id == "bh3")
        and p.hostname in HOSTS
        and bool(supported_path)
    )


def allows_head_fallback(url: str, error: object) -> bool:
    path = urlsplit(url).path.lower()
    return (
        urlsplit(url).hostname in {"bundle.bh3.com", "autopatchcn.bh3.com"}
        and bool(path.endswith((".zip", ".7z", ".bin")) or re.search(r"\.(?:zip|7z)\.\d+$", path))
        and getattr(error, "returncode", None) in {18, 56, 92}
    )


def classify_head_fallback(
    status: int,
    filename: str,
    headers: dict[str, str],
    *,
    expected_size: int | None = None,
    error: object | None = None,
) -> dict[str, object] | None:
    del status, filename, expected_size
    evidence = dict(headers or {})
    for key, value in (getattr(error, "headers", {}) or {}).items():
        evidence.setdefault(str(key).lower(), value)
    error_body = getattr(error, "body", b"") or getattr(error, "prefix", b"")
    if isinstance(error_body, str):
        error_body = error_body.encode("latin-1", errors="ignore")
    try:
        root = ET.fromstring(error_body)
        invalid_object_state = root.tag.rsplit("}", 1)[-1] == "Error" and any(
            child.tag.rsplit("}", 1)[-1] == "Code"
            and (child.text or "").strip() == "InvalidObjectState"
            for child in root.iter()
        )
    except (ET.ParseError, ValueError, TypeError):
        invalid_object_state = False
    if str(evidence.get("x-oss-storage-class", "")).strip().lower() == "archive" or invalid_object_state:
        return {
            "available": False,
            "reason": "oss_archive_not_restored",
            "confidence": "high",
            "source_kind": "official_storage_metadata",
        }
    return None


def file_time_candidate(
    status: int,
    headers: dict[str, str],
    *,
    context: dict[str, object],
    available: bool | None,
) -> str | None:
    if (
        status not in {200, 206}
        or available is not True
        or context.get("kind") != "package"
        or context.get("component") != "game"
        or context.get("package_type") != "full"
        or context.get("part") != 1
    ):
        return None
    try:
        value = parsedate_to_datetime(headers["last-modified"])
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
