"""Range transport and metadata helpers shared only by probe adapters."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urlsplit


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
MARKER = "__GMI_PROBE_META__"


class ProbeError(RuntimeError):
    """A transport/probe failure with any response evidence that was seen."""

    def __init__(self, message: str, *, returncode: int | None = None,
                 status: int | None = None, headers: dict[str, str] | None = None,
                 final_url: str | None = None, prefix: bytes = b"",
                 body: bytes = b"") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.status = status
        self.headers = headers or {}
        self.final_url = final_url
        self.prefix = prefix
        self.body = body


class ProbeObservation:
    """Tuple-compatible successful range observation with transport evidence."""

    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        final_url: str,
        prefix: bytes,
        *,
        transport_returncode: int = 0,
        bytes_received: int = 0,
        body: bytes = b"",
    ):
        self.status = status
        self.headers = headers
        self.final_url = final_url
        self.prefix = prefix
        self.transport_returncode = transport_returncode
        self.bytes_received = bytes_received
        self.body = body[:4096]

    def __iter__(self):
        yield self.status
        yield self.headers
        yield self.final_url
        yield self.prefix


def validate_timeout(timeout: int) -> int:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ProbeError("探活 timeout 必须是正整数")
    return timeout


def probe_url(url: str, timeout: int = 10) -> ProbeObservation:
    timeout = validate_timeout(timeout)
    write_out = f"\n{MARKER}\nhttp=%{{http_code}}\nurl=%{{url_effective}}\n"
    with tempfile.TemporaryDirectory() as directory:
        body_path = os.path.join(directory, "prefix.bin")
        command = [
            "curl", "-sS", "--connect-timeout", "10", "--max-time", str(timeout),
            "-L", "--max-redirs", "8", "--max-filesize", "4096", "--range", "0-15",
            "-H", f"User-Agent: {UA}", "-H", "Accept-Encoding: identity",
            "-D", "-", "-o", body_path, "-w", write_out, url,
        ]
        try:
            # Keep a process-level guard in addition to curl's --max-time.
            # On Windows a stuck curl child can outlive curl's own timeout;
            # without this guard one worker can block the whole batch forever.
            result = subprocess.run(
                command, capture_output=True, check=False, timeout=timeout + 5,
            )
        except FileNotFoundError as exc:
            raise ProbeError("系统中没有找到 curl") from exc
        except subprocess.TimeoutExpired as exc:
            raise ProbeError(f"curl 超时（{timeout + 5} 秒）") from exc
        try:
            with open(body_path, "rb") as body:
                # A few package formats (notably 7z) need more than the
                # four bytes used by the old APK-only probe. This remains a
                # tiny range request and never downloads the package.
                body_bytes = body.read(4096)
                prefix = body_bytes[:16]
        except OSError:
            prefix = b""
            body_bytes = b""
    output = result.stdout.decode("latin-1", errors="replace")
    marker = f"\n{MARKER}\n"
    if marker not in output:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProbeError("curl 没有返回探测元数据" + (f"：{error}" if error else ""),
                         returncode=result.returncode, prefix=prefix, body=body_bytes)
    status, headers, final_url = _parse_curl_metadata(output)
    if result.returncode not in (0, 63):
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProbeError(
            f"curl 失败（{result.returncode}）：{error}",
            returncode=result.returncode, status=status or None,
            headers=headers, final_url=final_url or None, prefix=prefix, body=body_bytes,
        )
    if result.returncode == 63 and (status not in {200, 206} or len(prefix) < 16):
        raise ProbeError(
            "curl 返回 63，但未取得完整探测前缀",
            returncode=result.returncode, status=status or None,
            headers=headers, final_url=final_url or None, prefix=prefix, body=body_bytes,
        )
    if not status or not final_url:
        raise ProbeError("无法解析最终 HTTP 响应", returncode=result.returncode,
                         status=status or None, headers=headers,
                         final_url=final_url or None, prefix=prefix)
    return ProbeObservation(
        status, headers, final_url, prefix,
        transport_returncode=result.returncode,
        bytes_received=len(body_bytes),
        body=body_bytes,
    )


def classify_oss_archive_response(
    status: int, headers: dict[str, str], body: bytes,
) -> dict[str, object] | None:
    """Recognize an OSS object that exists but has not been restored."""
    if status != 403:
        return None
    evidence = {str(key).lower(): value for key, value in (headers or {}).items()}
    storage_class = str(evidence.get("x-oss-storage-class", "")).strip().lower()
    try:
        root = ET.fromstring(body)
        invalid_object_state = root.tag.rsplit("}", 1)[-1] == "Error" and any(
            child.tag.rsplit("}", 1)[-1] == "Code"
            and (child.text or "").strip() == "InvalidObjectState"
            for child in root.iter()
        )
    except (ET.ParseError, ValueError, TypeError):
        invalid_object_state = False
    if storage_class != "archive" and not invalid_object_state:
        return None
    return {
        "available": False,
        "reason": "oss_archive_not_restored",
        "confidence": "high",
        "source_kind": "official_storage_metadata",
    }


def _parse_curl_metadata(output: str) -> tuple[int, dict[str, str], str]:
    marker = f"\n{MARKER}\n"
    if marker not in output:
        return 0, {}, ""
    raw_headers, raw_meta = output.rsplit(marker, 1)
    meta = dict(line.split("=", 1) for line in raw_meta.splitlines() if "=" in line)
    status = 0
    headers: dict[str, str] = {}
    for line in raw_headers.replace("\r\n", "\n").splitlines():
        match = re.match(r"HTTP/\S+\s+(\d{3})", line)
        if match:
            status, headers = int(match.group(1)), {}
        elif status and ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    return int(meta.get("http") or status), headers, meta.get("url", "")


def probe_head(url: str, timeout: int = 10) -> tuple[int, dict[str, str], str]:
    """Run a metadata-only HEAD request for an adapter-authorized fallback."""
    timeout = validate_timeout(timeout)
    write_out = f"\n{MARKER}\nhttp=%{{http_code}}\nurl=%{{url_effective}}\n"
    command = [
        "curl", "-sS", "--connect-timeout", "10", "--max-time", str(timeout),
        "-L", "--max-redirs", "8", "-I", "-H", f"User-Agent: {UA}",
        "-H", "Accept-Encoding: identity", "-D", "-", "-o", os.devnull,
        "-w", write_out, url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise ProbeError("系统中没有找到 curl") from exc
    output = result.stdout.decode("latin-1", errors="replace")
    status, headers, final_url = _parse_curl_metadata(output)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ProbeError(f"HEAD curl 失败（{result.returncode}）：{error}",
                         returncode=result.returncode, status=status or None,
                         headers=headers, final_url=final_url or None)
    if not status or not final_url:
        raise ProbeError("HEAD 没有返回有效响应", status=status or None,
                         headers=headers, final_url=final_url or None)
    return status, headers, final_url


def content_size(status: int, headers: dict[str, str]) -> int | None:
    match = re.match(r"bytes\s+\d+-\d+/(\d+)$", headers.get("content-range", ""), re.I)
    if match:
        return int(match.group(1))
    length = headers.get("content-length", "")
    return int(length) if status == 200 and length.isdigit() else None


def url_precise_time(url: str) -> str | None:
    path = unquote(urlsplit(url).path)
    for pattern, joiner in (
        (r"(?<!\d)(\d{14})(?!\d)", lambda match: match.group(1)),
        (r"(?<!\d)(\d{8})[-_](\d{6})(?!\d)", lambda match: match.group(1) + match.group(2)),
    ):
        for match in re.finditer(pattern, path):
            try:
                value = datetime.strptime(joiner(match), "%Y%m%d%H%M%S")
            except ValueError:
                continue
            value = value.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
            return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return None


def url_date(url: str) -> str | None:
    path = unquote(urlsplit(url).path)
    for match in re.finditer(r"(?<!\d)(\d{8})(?!\d)", path):
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
        except ValueError:
            continue
    return None


def file_time(url: str, headers: dict[str, str], url_time: bool) -> str | None:
    if url_time:
        value = url_precise_time(url)
        if value:
            return value
    try:
        value = parsedate_to_datetime(headers["last-modified"]).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError):
        value = None
    if value is not None:
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    return url_date(url) if url_time else None


def content_md5(value: str | None) -> str | None:
    if not value:
        return None
    try:
        digest = base64.b64decode(value, validate=True)
    except ValueError:
        return None
    return digest.hex() if len(digest) == 16 else None
