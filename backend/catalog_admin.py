"""File-backed catalog configuration for admin-managed games and domains."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.storage_locks import DATA_LOCK, data_file_lock


CATALOG_CONFIG_NAME = "catalog.admin.json"
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
VENDORS = ("mihoyo", "hypergryph", "kuro", "perfectworld")
DOMAIN_KINDS = frozenset({"apk", "packages", "patches", "chunks", "files", "resources", "mixed"})
CAPABILITIES = frozenset({"apk", "packages", "patches", "chunks", "files", "resources", "archive", "compare"})


class CatalogConfigError(ValueError):
    """Catalog admin config is invalid or cannot be persisted."""


def _config_path(root: Path) -> Path:
    return Path(root) / CATALOG_CONFIG_NAME


def _safe_component(value: Any, field: str) -> str:
    if not isinstance(value, str) or SAFE_COMPONENT.fullmatch(value) is None:
        raise CatalogConfigError(f"{field} 必须是安全的非空路径组件")
    return value


def _safe_root(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        info = os.lstat(root)
    except OSError as error:
        raise CatalogConfigError("数据目录不可用") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CatalogConfigError("数据目录不安全")


def _ordinary_file(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _normalize_platform(value: Any, *, game: bool) -> str:
    text = str(value or ("multi" if game else "windows")).strip().lower()
    if text in {"pc", "windows", "win"}:
        return "windows"
    if text == "android":
        return "android"
    if game and text == "multi":
        return "multi"
    raise CatalogConfigError("platform 无效")


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise CatalogConfigError("布尔字段无效")
    return value


def _normalize_sort_order(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogConfigError("sort_order 无效")
    return value


def _normalize_vendor(value: Any, root: Path, game_id: str) -> str:
    if value is not None:
        vendor = _safe_component(value, "vendor")
        if vendor not in VENDORS:
            raise CatalogConfigError("vendor 无效")
        return vendor
    for vendor in VENDORS:
        if (Path(root) / vendor / game_id).exists():
            return vendor
    return VENDORS[0]


def _normalize_capabilities(value: Any, kind: str) -> list[str]:
    if value is None:
        defaults = {
            "apk": ["apk", "archive"],
            "chunks": ["chunks", "files", "archive", "compare"],
            "files": ["files", "archive", "compare"],
            "patches": ["patches", "archive"],
            "resources": ["resources"],
        }
        return defaults.get(kind, ["packages", "archive", "compare"])
    if not isinstance(value, list):
        raise CatalogConfigError("capabilities 必须是数组")
    result: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise CatalogConfigError("capabilities 无效")
        item = raw.strip().lower()
        if item not in CAPABILITIES:
            raise CatalogConfigError("capabilities 无效")
        if item not in result:
            result.append(item)
    return result


def normalize_game(root: Path, payload: Mapping[str, Any], *, default_order: int = 0) -> dict[str, Any]:
    game_id = _safe_component(payload.get("id"), "id")
    return {
        "id": game_id,
        "name": str(payload.get("name") or game_id).strip(),
        "sub_name": str(payload.get("sub_name") or "").strip(),
        "platform": _normalize_platform(payload.get("platform"), game=True),
        "icon_source": str(payload.get("icon_source") or f"builtin:{game_id}").strip(),
        "is_enabled": _normalize_bool(payload.get("is_enabled"), True),
        "sort_order": _normalize_sort_order(payload.get("sort_order"), default_order),
        "vendor": _normalize_vendor(payload.get("vendor"), Path(root), game_id),
    }


def normalize_domain(root: Path, payload: Mapping[str, Any], *, default_order: int = 0) -> dict[str, Any]:
    domain_id = _safe_component(payload.get("id"), "id")
    game_id = _safe_component(payload.get("game_id"), "game_id")
    kind = str(payload.get("kind") or "packages").strip().lower()
    if kind not in DOMAIN_KINDS:
        raise CatalogConfigError("kind 无效")
    platform = _normalize_platform(payload.get("platform"), game=False)
    if platform == "android" and domain_id != f"{game_id}-android":
        raise CatalogConfigError("Android 数据模块只能使用默认域 ID")
    return {
        "id": domain_id,
        "game_id": game_id,
        "kind": kind,
        "platform": platform,
        "capabilities": _normalize_capabilities(payload.get("capabilities"), kind),
        "adapter": str(payload.get("adapter") or ("android" if platform == "android" else "generic")).strip(),
        "is_enabled": _normalize_bool(payload.get("is_enabled"), True),
        "sort_order": _normalize_sort_order(payload.get("sort_order"), default_order),
        "vendor": _normalize_vendor(payload.get("vendor"), Path(root), game_id),
    }


def empty_config() -> dict[str, dict[str, dict[str, Any]]]:
    return {"games": {}, "domains": {}}


def load_config(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    path = _config_path(Path(root))
    if not path.exists():
        return empty_config()
    if not _ordinary_file(path):
        raise CatalogConfigError("catalog 配置文件不安全")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogConfigError("catalog 配置文件损坏") from error
    if not isinstance(value, dict):
        raise CatalogConfigError("catalog 配置必须是对象")
    raw_games = value.get("games", {})
    raw_domains = value.get("domains", {})
    if not isinstance(raw_games, dict) or not isinstance(raw_domains, dict):
        raise CatalogConfigError("catalog 配置结构无效")
    result = empty_config()
    for game_id, raw in raw_games.items():
        if not isinstance(raw, Mapping):
            raise CatalogConfigError("game 配置无效")
        normalized = normalize_game(root, {**raw, "id": game_id})
        result["games"][normalized["id"]] = normalized
    for domain_id, raw in raw_domains.items():
        if not isinstance(raw, Mapping):
            raise CatalogConfigError("domain 配置无效")
        normalized = normalize_domain(root, {**raw, "id": domain_id})
        result["domains"][normalized["id"]] = normalized
    return result


def save_config(root: Path, config: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> None:
    root = Path(root)
    _safe_root(root)
    normalized = empty_config()
    for game_id, raw in config.get("games", {}).items():
        normalized["games"][game_id] = normalize_game(root, {**raw, "id": game_id})
    for domain_id, raw in config.get("domains", {}).items():
        normalized["domains"][domain_id] = normalize_domain(root, {**raw, "id": domain_id})
    path = _config_path(root)
    raw = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    with DATA_LOCK:
        with data_file_lock(root):
            descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=root)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


def configured_games(root: Path) -> dict[str, dict[str, Any]]:
    return load_config(root)["games"]


def configured_domains(root: Path) -> dict[str, dict[str, Any]]:
    return load_config(root)["domains"]


def game_catalog(root: Path, static_catalog: Sequence[tuple[str, str, str]]) -> list[dict[str, Any]]:
    config = load_config(root)
    games: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, (game_id, name, sub_name) in enumerate(static_catalog):
        base = {
            "id": game_id,
            "name": name,
            "sub_name": sub_name,
            "platform": "multi",
            "icon_source": f"builtin:{game_id}",
            "is_enabled": True,
            "sort_order": order,
            "vendor": _normalize_vendor(None, Path(root), game_id),
        }
        base.update(config["games"].get(game_id, {}))
        games.append(base)
        seen.add(game_id)
    extras = [game for game in config["games"].values() if game["id"] not in seen]
    games.extend(sorted(extras, key=lambda item: (item.get("sort_order", 0), item["id"])))
    return games


def game_ids(root: Path, static_catalog: Sequence[tuple[str, str, str]]) -> tuple[str, ...]:
    return tuple(game["id"] for game in game_catalog(root, static_catalog))


def configured_nondefault_pc_domains(root: Path, vendor: str, game_id: str) -> tuple[str, ...]:
    result = []
    for domain in configured_domains(root).values():
        if (
            domain["vendor"] == vendor
            and domain["game_id"] == game_id
            and domain["platform"] == "windows"
            and domain["id"] != f"{game_id}-pc"
        ):
            result.append(domain["id"])
    return tuple(sorted(result))


def is_configured_nondefault_pc_domain(root: Path, vendor: str, game_id: str, domain_id: str) -> bool:
    return domain_id in configured_nondefault_pc_domains(root, vendor, game_id)


def domain_directory(root: Path, domain: Mapping[str, Any]) -> Path:
    disk = "android" if domain["platform"] == "android" else "pc"
    base = Path(root) / domain["vendor"] / domain["game_id"] / disk
    default_id = f"{domain['game_id']}-{'android' if disk == 'android' else 'pc'}"
    if domain["id"] == default_id:
        return base
    return base / "domains" / domain["id"]


def ensure_domain_directory(root: Path, domain: Mapping[str, Any]) -> Path:
    root = Path(root)
    _safe_root(root)
    target = domain_directory(root, domain)
    with DATA_LOCK:
        with data_file_lock(root):
            current = root
            for part in target.relative_to(root).parts:
                current = current / part
                try:
                    info = os.lstat(current)
                except FileNotFoundError:
                    current.mkdir()
                    info = os.lstat(current)
                except OSError as error:
                    raise CatalogConfigError("模块目录不可用") from error
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    raise CatalogConfigError("模块目录不安全")
    return target


def remove_empty_domain_directory(root: Path, domain: Mapping[str, Any]) -> None:
    root = Path(root)
    target = domain_directory(root, domain)
    with DATA_LOCK:
        with data_file_lock(root):
            try:
                info = os.lstat(target)
            except FileNotFoundError:
                return
            except OSError as error:
                raise CatalogConfigError("模块目录不可用") from error
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise CatalogConfigError("模块目录不安全")
            try:
                if any(target.iterdir()):
                    raise CatalogConfigError("模块目录不是空目录")
                current = target
                while current != root:
                    current.rmdir()
                    parent = current.parent
                    if any(parent.iterdir()):
                        break
                    current = parent
            except OSError as error:
                raise CatalogConfigError("模块目录无法删除") from error


__all__ = [
    "CatalogConfigError",
    "configured_domains",
    "configured_games",
    "configured_nondefault_pc_domains",
    "domain_directory",
    "ensure_domain_directory",
    "game_catalog",
    "game_ids",
    "is_configured_nondefault_pc_domain",
    "load_config",
    "normalize_domain",
    "normalize_game",
    "remove_empty_domain_directory",
    "save_config",
]
