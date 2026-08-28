import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

NAME = "mihoyo_bh3_cdn"
URL_TIME = True
HOSTS = {"app.bh3.com", "bundle.bh3.com", "autopatchcn.bh3.com"}


def preflight(
    url: str,
    *,
    platform: str | None = None,
    vendor: str | None = None,
    game_id: str | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """The retired Android host is a known static result, not a network error."""
    path = urlsplit(url).path.lower()
    context = context or {}
    if (
        urlsplit(url).hostname == "app.bh3.com"
        and path.endswith(".apk")
        and platform in {None, "android"}
        and vendor in {None, "mihoyo"}
        and game_id in {None, "bh3"}
        and context.get("platform", "android") == "android"
        and context.get("game_id", "bh3") == "bh3"
        and context.get("kind", "apk") == "apk"
    ):
        return {
            "available": False,
            "reason": "retired_official_host",
            "confidence": "high",
            "source_kind": "adapter_policy",
        }
    return None


def allows_head_fallback(url: str, error: object) -> bool:
    host = urlsplit(url).hostname
    path = urlsplit(url).path.lower()
    return (
        host in {"bundle.bh3.com", "autopatchcn.bh3.com"}
        and path.endswith(".apk")
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
    """Classify metadata after a Range transport failure.

    HEAD proves only metadata.  It must never turn a non-readable object into
    ``available``.  BH3's old Android objects are OSS Archive objects: their
    HEAD metadata remains visible while Range returns ``InvalidObjectState``
    or resets before delivering a byte.
    """
    if not filename.lower().endswith(".apk"):
        return None
    evidence = dict(headers or {})
    error_headers = getattr(error, "headers", {}) or {}
    for key, value in error_headers.items():
        evidence.setdefault(str(key).lower(), value)
    error_body = getattr(error, "body", b"") or getattr(error, "prefix", b"")
    if isinstance(error_body, str):
        error_body = error_body.encode("latin-1", errors="ignore")
    storage_class = str(evidence.get("x-oss-storage-class", "")).strip().lower()
    try:
        root = ET.fromstring(error_body)
        local_root = root.tag.rsplit("}", 1)[-1]
        invalid_object_state = local_root == "Error" and any(
            child.tag.rsplit("}", 1)[-1] == "Code"
            and (child.text or "").strip() == "InvalidObjectState"
            for child in root.iter()
        )
    except (ET.ParseError, ValueError, TypeError):
        invalid_object_state = False
    if storage_class == "archive" or invalid_object_state:
        return {
            "available": False,
            "reason": "oss_archive_not_restored",
            "confidence": "high",
            "source_kind": "official_storage_metadata",
        }
    # A successful HEAD with matching size/content type is still only
    # metadata.  Without archive evidence it remains unknown and the service
    # reports the original probe failure.
    if status not in {200, 206}:
        return None
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
        return None
    raw_size = evidence.get("content-length", "")
    if not str(raw_size).isdigit() or int(raw_size) != expected_size:
        return None
    return None


def matches(vendor: str | None, game_id: str | None, url: str) -> bool:
    return (
        (not vendor or vendor == "mihoyo")
        and (not game_id or game_id == "bh3")
        and urlsplit(url).hostname in HOSTS
        and urlsplit(url).path.lower().endswith(".apk")
    )


def availability(
    status: int,
    filename: str,
    prefix: bytes,
    *,
    transport_returncode: int | None = None,
    bytes_received: int | None = None,
    **_: object,
) -> bool | None:
    if status in {404, 410}:
        return False
    if status not in {200, 206} or not filename.lower().endswith(".apk"):
        return None
    if type(transport_returncode) is not int or transport_returncode != 0:
        return None
    if type(bytes_received) is not int or bytes_received < 16 or len(prefix) < 16 or bytes_received < len(prefix):
        return None
    return True if prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")) else None
