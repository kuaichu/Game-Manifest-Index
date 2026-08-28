"""Read version metadata from a remote APK without downloading the APK."""

from __future__ import annotations

import re
from zipfile import BadZipFile

from url_adapters.common import AdapterError


ANDROID_NS = "http://schemas.android.com/apk/res/android"
MAX_MANIFEST_SIZE = 2 * 1024 * 1024
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def remote_apk_version(
    url: str,
    timeout: int,
    *,
    expected_package: str | None = None,
) -> tuple[str, int | None]:
    try:
        from pyaxmlparser.axmlprinter import AXMLPrinter
        from remotezip import RemoteZip, RemoteZipError
    except ImportError as error:
        raise AdapterError(
            "远程 APK 清单解析依赖未安装，请安装 backend/requirements.txt"
        ) from error

    try:
        with RemoteZip(
            url,
            initial_buffer_size=65536,
            headers={"User-Agent": UA},
            timeout=timeout,
        ) as archive:
            info = archive.getinfo("AndroidManifest.xml")
            if info.file_size > MAX_MANIFEST_SIZE:
                raise AdapterError("AndroidManifest.xml 超过 2 MiB 限制")
            manifest = archive.read("AndroidManifest.xml")
        root = AXMLPrinter(manifest).get_xml_obj()
    except AdapterError:
        raise
    except (BadZipFile, KeyError, OSError, RemoteZipError, ValueError) as error:
        raise AdapterError(f"读取远程 APK 清单失败：{error}") from error

    package = root.get("package") if root is not None else None
    if expected_package and package != expected_package:
        raise AdapterError(
            f"APK 包名不匹配：预期 {expected_package}，实际 {package or 'unknown'}"
        )
    version = root.get(f"{{{ANDROID_NS}}}versionName") if root is not None else None
    version_code = root.get(f"{{{ANDROID_NS}}}versionCode") if root is not None else None
    if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]*", version):
        raise AdapterError("AndroidManifest.xml 中没有可靠 versionName")
    try:
        parsed_code = int(version_code) if version_code not in (None, "") else None
    except (TypeError, ValueError) as error:
        raise AdapterError("AndroidManifest.xml 中的 versionCode 无效") from error
    return version, parsed_code
