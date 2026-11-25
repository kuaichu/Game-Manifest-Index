"""Admin catalog projection and game/domain CRUD orchestration."""

from __future__ import annotations

import copy
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Mapping

from backend import catalog_admin
from backend.catalog_admin import CatalogConfigError
from backend.catalog_registry import GAME_CATALOG, GAME_IDS, VENDORS
from backend.domain_registry import nondefault_pc_domains
from backend.fs_safety import disk_platform, domain_directory, is_safe_component
from backend.indexes import version_key
from backend.inventory_loader import DomainData, fail
from backend.public_projection import domain_projection
from backend.storage_locks import DATA_LOCK, data_file_lock


def _exists_or_link(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _catalog_error(error: CatalogConfigError) -> None:
    fail(422, "validation_error", str(error))


def _reject_nondefault_android_domain(payload: Mapping[str, Any]) -> None:
    platform = payload.get("platform")
    game_id = payload.get("game_id")
    domain_id = payload.get("id")
    if (
        isinstance(platform, str)
        and platform.strip().lower() == "android"
        and domain_id != f"{game_id}-android"
    ):
        fail(409, "domain_platform_unsupported", "Android 数据模块只能使用默认域 ID")


def _admin_game_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(item[key]) for key in (
        "id", "name", "sub_name", "platform", "icon_source",
        "version_count", "latest_version", "is_enabled", "sort_order",
    ) if key in item}


def _admin_domain_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: copy.deepcopy(item[key]) for key in (
        "id", "game_id", "kind", "platform", "capabilities",
        "capability_contract", "adapter", "version_count", "latest_version",
        "source_current_version", "catalog_version_count", "is_enabled", "sort_order",
    ) if key in item}
    result.setdefault("capability_contract", {})
    return result


def catalog_projection(root: Path) -> dict[str, Any]:
    try:
        config = catalog_admin.load_config(root)
        configured_domains = catalog_admin.configured_domains(root, config=config)
        games = catalog_admin.game_catalog(root, GAME_CATALOG, config=config)
    except CatalogConfigError as error:
        _catalog_error(error)
    for game in games:
        game["version_count"] = 0
        game["latest_version"] = None
    game_by_id = {game["id"]: game for game in games}
    game_platforms: dict[str, set[str]] = {game["id"]: set() for game in games}
    domains: list[dict[str, Any]] = []
    game_ids = [game["id"] for game in games]
    for game_order, game_id in enumerate(game_ids):
        domain_ids = [
            f"{game_id}-{'android' if platform == 'android' else 'pc'}"
            for _, platform in (("android", "android"), ("pc", "windows"))
            if any(
                _exists_or_link(domain_directory(root, vendor, game_id, platform))
                for vendor in VENDORS
            )
        ]
        for vendor in VENDORS:
            configured = catalog_admin.configured_nondefault_pc_domains(
                root, vendor, game_id, config=config,
            )
            for domain_id in (*nondefault_pc_domains(vendor, game_id), *configured):
                directory = domain_directory(root, vendor, game_id, "windows", domain_id)
                if _exists_or_link(directory) or domain_id in configured_domains:
                    domain_ids.append(domain_id)
        for domain_id in configured_domains:
            if configured_domains[domain_id]["game_id"] == game_id and domain_id not in domain_ids:
                domain_ids.append(domain_id)
        seen_domains: set[str] = set()
        for domain_order, domain_id in enumerate(domain_ids):
            if domain_id in seen_domains:
                continue
            seen_domains.add(domain_id)
            vendor, _, scanned_platform, directory, records = scan_domain(
                root, domain_id, config=config,
            )
            platform = records[0]["platform"] if records else scanned_platform
            disk = disk_platform(platform)
            domain = DomainData(vendor, game_id, disk, platform, domain_id, directory, tuple(records))
            if records:
                projection = domain_projection(domain, game_order * 10 + domain_order)
            else:
                projection = {
                    "id": domain_id,
                    "game_id": game_id,
                    "kind": "apk" if platform == "android" else "packages",
                    "platform": platform,
                    "capabilities": [],
                    "capability_contract": {},
                    "adapter": "android" if platform == "android" else "generic",
                    "version_count": 0,
                    "latest_version": None,
                    "source_current_version": None,
                    "catalog_version_count": 0,
                    "is_enabled": True,
                    "sort_order": game_order * 10 + domain_order,
                }
            projection.update({
                key: copy.deepcopy(value)
                for key, value in configured_domains.get(domain_id, {}).items()
                if key not in {"vendor"}
            })
            domains.append(projection)
            game = game_by_id[game_id]
            game["version_count"] += len(records)
            game_platforms[game_id].add(platform)
            versions = [record["version"] for record in records]
            if game["latest_version"] is not None:
                versions.append(game["latest_version"])
            game["latest_version"] = max(versions, key=version_key) if versions else None
    for game in games:
        platforms = game_platforms[game["id"]]
        if len(platforms) == 1 and game.get("platform") == "multi":
            game["platform"] = next(iter(platforms))
    games.sort(key=lambda item: (item.get("sort_order", 0), item["id"]))
    domains.sort(key=lambda item: (item.get("sort_order", 0), item["id"]))
    return {"games": [_admin_game_projection(game) for game in games], "domains": [_admin_domain_projection(domain) for domain in domains]}


_ORIGINAL_CATALOG_PROJECTION = catalog_projection


def catalog_config(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    try:
        return catalog_admin.load_config(root)
    except CatalogConfigError as error:
        _catalog_error(error)


_catalog_config = catalog_config
_ORIGINAL_CATALOG_CONFIG = catalog_config


def _active_catalog_config(root: Path) -> dict[str, dict[str, dict[str, Any]]]:
    admin_mod = sys.modules.get("backend.version_admin")
    override = getattr(admin_mod, "_catalog_config", None) if admin_mod is not None else None
    if callable(override) and override is not _ORIGINAL_CATALOG_CONFIG:
        return override(root)
    if _catalog_config is not _ORIGINAL_CATALOG_CONFIG:
        return _catalog_config(root)
    return catalog_config(root)


def _active_catalog_projection(root: Path) -> dict[str, Any]:
    admin_mod = sys.modules.get("backend.version_admin")
    override = getattr(admin_mod, "catalog_projection", None) if admin_mod is not None else None
    if callable(override) and override is not _ORIGINAL_CATALOG_PROJECTION:
        return override(root)
    return catalog_projection(root)


def _catalog_index(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = _active_catalog_projection(root)
    return (
        {item["id"]: item for item in catalog["games"]},
        {item["id"]: item for item in catalog["domains"]},
    )


def _catalog_mutation(function):
    @wraps(function)
    def mutate(root: Path, *args, **kwargs):
        with DATA_LOCK, data_file_lock(root):
            return function(root, *args, **kwargs)
    return mutate


@_catalog_mutation
def create_game(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    config = _active_catalog_config(root)
    games, _ = _catalog_index(root)
    try:
        game = catalog_admin.normalize_game(root, payload, default_order=len(games) * 10)
    except CatalogConfigError as error:
        _catalog_error(error)
    if game["id"] in games:
        fail(409, "game_exists", "游戏已存在")
    config["games"][game["id"]] = game
    catalog_admin.save_config(root, config)
    return _admin_game_projection({**game, "version_count": 0, "latest_version": None})


@_catalog_mutation
def update_game(root: Path, game_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not is_safe_component(game_id):
        fail(404, "game_not_found", "游戏不存在")
    config = _active_catalog_config(root)
    games, _ = _catalog_index(root)
    current = games.get(game_id)
    if current is None:
        fail(404, "game_not_found", "游戏不存在")
    if payload.get("id", game_id) != game_id:
        fail(422, "validation_error", "游戏 ID 不可修改")
    try:
        updated = catalog_admin.normalize_game(
            root, {**current, **payload, "id": game_id}, default_order=current.get("sort_order", 0),
        )
    except CatalogConfigError as error:
        _catalog_error(error)
    stored = config["games"].get(game_id)
    stored_platform = (
        stored.get("platform")
        if isinstance(stored, Mapping)
        else ("multi" if game_id in GAME_IDS else current.get("platform"))
    )
    if current.get("version_count", 0) and updated["platform"] != stored_platform:
        fail(409, "catalog_not_empty", "已有版本的游戏不能变更平台")
    config["games"][game_id] = updated
    catalog_admin.save_config(root, config)
    projected_games = _active_catalog_projection(root)["games"]
    return next(item for item in projected_games if item["id"] == game_id)


@_catalog_mutation
def delete_game(root: Path, game_id: str) -> None:
    if not is_safe_component(game_id):
        fail(404, "game_not_found", "游戏不存在")
    config = _active_catalog_config(root)
    games, domains = _catalog_index(root)
    if game_id not in games:
        fail(404, "game_not_found", "游戏不存在")
    if game_id in GAME_IDS or game_id not in config["games"]:
        fail(409, "catalog_not_empty", "静态游戏不能删除，可改为停用")
    if any(domain["game_id"] == game_id for domain in domains.values()):
        fail(409, "catalog_not_empty", "游戏下存在数据模块，不能删除")
    del config["games"][game_id]
    catalog_admin.save_config(root, config)


@_catalog_mutation
def create_domain(root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    config = _active_catalog_config(root)
    games, domains = _catalog_index(root)
    _reject_nondefault_android_domain(payload)
    try:
        domain = catalog_admin.normalize_domain(root, payload, default_order=len(domains) * 10)
    except CatalogConfigError as error:
        _catalog_error(error)
    if domain["id"] in domains:
        fail(409, "domain_exists", "数据模块已存在")
    if domain["game_id"] not in games:
        fail(422, "validation_error", "所属游戏不存在")
    try:
        catalog_admin.ensure_domain_directory(root, domain)
    except CatalogConfigError as error:
        _catalog_error(error)
    config["domains"][domain["id"]] = domain
    catalog_admin.save_config(root, config)
    return _admin_domain_projection({**domain, "capability_contract": {}, "version_count": 0, "latest_version": None, "source_current_version": None, "catalog_version_count": 0})


@_catalog_mutation
def update_domain(root: Path, domain_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not is_safe_component(domain_id):
        fail(404, "domain_not_found", "归档域不存在")
    config = _active_catalog_config(root)
    games, domains = _catalog_index(root)
    current = domains.get(domain_id)
    if current is None:
        fail(404, "domain_not_found", "归档域不存在")
    if payload.get("id", domain_id) != domain_id:
        fail(422, "validation_error", "模块 ID 不可修改")
    if payload.get("game_id", current["game_id"]) not in games:
        fail(422, "validation_error", "所属游戏不存在")
    _reject_nondefault_android_domain({**current, **payload, "id": domain_id})
    try:
        updated = catalog_admin.normalize_domain(
            root, {**current, **payload, "id": domain_id}, default_order=current.get("sort_order", 0),
        )
    except CatalogConfigError as error:
        _catalog_error(error)
    if (
        updated["game_id"] != current["game_id"]
        or updated["platform"] != current["platform"]
    ):
        fail(409, "catalog_domain_identity_immutable", "数据模块所属游戏和平台不可修改")
    config["domains"][domain_id] = updated
    catalog_admin.save_config(root, config)
    projected_domains = _active_catalog_projection(root)["domains"]
    return next(item for item in projected_domains if item["id"] == domain_id)


@_catalog_mutation
def delete_domain(root: Path, domain_id: str) -> None:
    if not is_safe_component(domain_id):
        fail(404, "domain_not_found", "归档域不存在")
    config = _active_catalog_config(root)
    _, domains = _catalog_index(root)
    current = domains.get(domain_id)
    if current is None:
        fail(404, "domain_not_found", "归档域不存在")
    if domain_id not in config["domains"]:
        fail(409, "catalog_not_empty", "静态数据模块不能删除，可改为停用")
    if current.get("version_count", 0):
        fail(409, "catalog_not_empty", "数据模块下存在版本，不能删除")
    try:
        catalog_admin.remove_empty_domain_directory(root, config["domains"][domain_id])
    except CatalogConfigError as error:
        _catalog_error(error)
    del config["domains"][domain_id]
    catalog_admin.save_config(root, config)


from backend.version_admin import scan_domain  # noqa: E402

__all__ = [
    "catalog_config",
    "catalog_projection",
    "create_domain",
    "create_game",
    "delete_domain",
    "delete_game",
    "update_domain",
    "update_game",
]
