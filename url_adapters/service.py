"""Run the official Android and PC URL discovery adapters."""

from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from backend.schema_v2 import validate_v2_record
from backend.version_store import v2_record_path
from url_adapters.android import (
    hypergryph_launcher_latest,
    kuro_pns_manifest,
    kuro_wuwa_mc_manifest,
    mihoyo_bh2_download_page,
    mihoyo_bh3_download_porter,
    mihoyo_download_porter,
    perfectworld_webops,
)
from url_adapters.pc import kuro_manifests, mihoyo_chunk_manifests, mihoyo_game_packages, perfectworld_patcher
from url_adapters.common import AdapterError


Discoverer = Callable[[str, Path, int, str | None, int | None], Path]
PCDiscoverer = Callable[[str, Path, int], Path]

# Keep this registry deliberately explicit: these are the twelve supported
# games and each points at the adapter's canonical schema-v2 writer.
DISCOVERERS: dict[str, Discoverer] = {
    "hk4e": mihoyo_download_porter.discover_v2,
    "hkrpg": mihoyo_download_porter.discover_v2,
    "nap": mihoyo_download_porter.discover_v2,
    "bh3": mihoyo_bh3_download_porter.discover_v2,
    "bh2": mihoyo_bh2_download_page.discover_v2,
    "arknights": hypergryph_launcher_latest.discover_v2,
    "endfield": hypergryph_launcher_latest.discover_v2,
    "wuwa": kuro_wuwa_mc_manifest.discover_v2,
    "pns": kuro_pns_manifest.discover_v2,
    "tof": perfectworld_webops.discover_v2,
    "p5x": perfectworld_webops.discover_v2,
    "nte": perfectworld_webops.discover_v2,
}

# PC registration is intentionally separate from the Android registry.  The
# two Mihoyo stages share one canonical record path, while the other vendors
# have one manifest-producing stage.
PC_DISCOVERERS: dict[str, tuple[tuple[str, PCDiscoverer], ...]] = {
    game_id: (("packages", mihoyo_game_packages.discover), ("chunks", mihoyo_chunk_manifests.discover))
    for game_id in ("hk4e", "hkrpg", "nap", "bh3")
}
PC_DISCOVERERS["wuwa"] = (("manifests", kuro_manifests.discover),)
for _game_id in ("tof", "p5x", "nte"):
    PC_DISCOVERERS[_game_id] = (("packages", perfectworld_patcher.discover),)

_PC_IDENTITIES = {
    "hk4e": ("mihoyo", "hk4e-pc"), "hkrpg": ("mihoyo", "hkrpg-pc"),
    "nap": ("mihoyo", "nap-pc"), "bh3": ("mihoyo", "bh3-pc"),
    "wuwa": ("kuro", "wuwa-pc"), "tof": ("perfectworld", "tof-pc"),
    "p5x": ("perfectworld", "p5x-pc"), "nte": ("perfectworld", "nte-pc"),
}


def _validate_inputs(game_ids: list[str], root: Path, timeout: int, workers: int) -> None:
    if not isinstance(game_ids, list) or any(not isinstance(game_id, str) or not game_id for game_id in game_ids):
        raise ValueError("game_ids 必须是非空字符串列表")
    if not isinstance(root, Path):
        raise TypeError("output_root 必须是 Path")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout 必须是正整数")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError("workers 必须是正整数")


def discovery_task_count(game_ids: list[str], scope: str = "android") -> int:
    """Return the number of registered discovery tasks (one per game)."""
    if scope not in ("android", "pc"):
        raise ValueError(f"不支持的数据范围：{scope}")
    if not isinstance(game_ids, list):
        raise ValueError("game_ids 必须是列表")
    registry = DISCOVERERS if scope == "android" else PC_DISCOVERERS
    return sum(game_id in registry for game_id in game_ids)


def _record_available(record: dict) -> bool | None:
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or not isinstance(artifacts[0], dict):
        return None
    urls = artifacts[0].get("urls")
    current = urls[0].get("current") if isinstance(urls, list) and urls and isinstance(urls[0], dict) else None
    state = current.get("state") if isinstance(current, dict) else None
    return state == "available" if state in ("available", "unavailable") else None


def _discover_one(game_id: str, root: Path, timeout: int) -> dict:
    if game_id not in DISCOVERERS:
        raise AdapterError(f"没有 Android 查找适配器：{game_id}")
    before = {path.stem for path in root.glob(f"*/{game_id}/android/*.json") if path.name != "index.json"}
    path = DISCOVERERS[game_id](game_id, root, timeout, None, None)
    record = json.loads(path.read_text(encoding="utf-8"))
    validate_v2_record(record)
    if record.get("platform") != "android" or record.get("game_id") != game_id:
        raise ValueError("发现记录身份与请求不一致")
    version = str(record["version"])
    return {
        "game_id": game_id, "platform": "android", "ok": True, "supported": True,
        "status": "finished", "version": version, "new": version not in before,
        "available": _record_available(record), "path": str(path), "error": None,
    }


def _discover_pc_one(game_id: str, root: Path, timeout: int) -> dict:
    """Run one PC game's registered stages serially and validate each record."""
    stages: list[dict] = []
    versions: list[str] = []
    paths: list[str] = []
    any_new = False
    registered = PC_DISCOVERERS.get(game_id)
    if registered is None:
        raise AdapterError(f"没有 PC 查找适配器：{game_id}")
    vendor, domain_id = _PC_IDENTITIES[game_id]
    before_files = {p.resolve() for p in root.rglob("*.json") if p.is_file() and not p.is_symlink()}
    prior_by_path: dict[Path, dict] = {}
    for stage_name, discoverer in registered:
        stage = {"name": stage_name, "ok": False, "status": "failed",
                 "version": None, "path": None, "new": False, "error": None}
        try:
            path = discoverer(game_id, root, timeout)
            if not isinstance(path, Path):
                raise TypeError("PC 查找适配器必须返回 Path")
            if path.is_symlink():
                raise ValueError("PC 查找适配器返回了符号链接记录路径")
            path = path.resolve()
            if not path.is_file() or path.is_symlink():
                raise ValueError("PC 查找适配器返回了不安全或不存在的记录路径")
            record = json.loads(path.read_text(encoding="utf-8"))
            validate_v2_record(record)
            expected = {
                "vendor": vendor, "game_id": game_id, "domain_id": domain_id,
                "platform": "windows", "channel": "official",
            }
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError("PC 发现记录身份与请求不一致")
            expected_path = v2_record_path(record, root)
            if path != expected_path.resolve():
                raise ValueError("PC 发现记录路径与 canonical identity 不一致")
            version = record.get("version")
            if not isinstance(version, str) or not version:
                raise ValueError("PC 发现记录缺少有效 version")
            if stage_name == "packages" and game_id in {"hk4e", "hkrpg", "nap", "bh3"}:
                if not record.get("artifacts"):
                    raise ValueError("Mihoyo packages stage 必须产生 artifacts")
            if stage_name == "chunks" and game_id in {"hk4e", "hkrpg", "nap", "bh3"}:
                refs = record.get("references")
                if not isinstance(refs, list) or not any(
                    isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in refs
                ):
                    raise ValueError("Mihoyo chunks stage 必须产生 chunk_manifest reference")
            previous = prior_by_path.get(path)
            if previous is not None:
                old_ids = {item.get("artifact_id") for item in previous.get("artifacts", [])
                           if isinstance(item, dict) and item.get("artifact_id")}
                new_ids = {item.get("artifact_id") for item in record.get("artifacts", [])
                           if isinstance(item, dict) and item.get("artifact_id")}
                if not old_ids.issubset(new_ids):
                    raise ValueError("PC 同路径后续 stage 丢失既有 artifact")
                old_refs = list(previous.get("references", []))
                new_refs = list(record.get("references", []))
                for ref in old_refs:
                    try:
                        new_refs.remove(ref)
                    except ValueError as error:
                        raise ValueError("PC 同路径后续 stage 丢失既有 reference") from error
            path_text = str(path)
            is_new = path not in before_files
            before_files.add(path)
            stage.update(ok=True, status="finished", version=version, path=path_text, new=is_new)
            versions.append(version)
            paths.append(path_text)
            any_new = any_new or is_new
            prior_by_path[path] = record
        except (AdapterError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            stage["error"] = str(error)
        stages.append(stage)
    unique_versions = list(dict.fromkeys(versions))
    unique_paths = list(dict.fromkeys(paths))
    errors = [stage["error"] for stage in stages if stage["error"]]
    all_ok = all(stage["ok"] for stage in stages)
    return {
        "game_id": game_id, "platform": "windows", "ok": all_ok, "supported": True,
        "status": "finished" if all_ok else "failed", "error": "; ".join(errors) or None, "new": any_new,
        "versions": unique_versions, "paths": unique_paths, "stages": stages,
        "version": unique_versions[0] if len(unique_versions) == 1 else None,
        "path": unique_paths[0] if len(unique_paths) == 1 else None,
    }


def discover_games(
    game_ids: list[str], root: Path, timeout: int, workers: int,
    progress: Callable[[dict, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    scope: str = "android",
) -> dict:
    """Discover selected games concurrently while collecting per-task errors."""
    if scope not in ("android", "pc"):
        raise ValueError(f"不支持的数据范围：{scope}")
    _validate_inputs(game_ids, root, timeout, workers)
    registry = DISCOVERERS if scope == "android" else PC_DISCOVERERS
    if scope == "pc" and len(set(game_ids)) != len(game_ids):
        raise ValueError("PC game_ids 不允许重复")
    is_cancelled = cancelled or (lambda: False)
    tasks = list(game_ids)
    items: list[dict] = []
    if not tasks:
        return {"scope": scope, "selected": 0, "succeeded": 0, "failed": 0,
                "new_versions": 0, "cancelled": bool(is_cancelled()), "items": []}
    pool = ThreadPoolExecutor(max_workers=min(workers, len(tasks)))
    pending: dict[Future, str] = {}
    task_iter = iter(tasks)

    def submit_next() -> bool:
        if is_cancelled():
            return False
        try:
            game_id = next(task_iter)
        except StopIteration:
            return False
        worker = _discover_one if scope == "android" else _discover_pc_one
        pending[pool.submit(worker, game_id, root, timeout)] = game_id
        return True

    for _ in range(min(workers, len(tasks))):
        submit_next()
    try:
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                game_id = pending.pop(future)
                try:
                    item = future.result()
                except (AdapterError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    if scope == "android":
                        item = {"game_id": game_id, "platform": "android", "ok": False,
                                "supported": game_id in registry, "status": "failed",
                                "version": None, "new": False, "available": None,
                                "path": None, "error": str(error)}
                    else:
                        item = {"game_id": game_id, "platform": "windows", "ok": False,
                                "supported": game_id in registry, "status": "failed",
                                "version": None, "new": False, "path": None,
                                "versions": [], "paths": [], "stages": [], "error": str(error)}
                items.append(item)
                if progress:
                    progress(item, len(items), len(tasks))
                submit_next()
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
    order = {game_id: index for index, game_id in enumerate(tasks)}
    items.sort(key=lambda item: order[item["game_id"]])
    return {"scope": scope, "selected": len(tasks),
            "succeeded": sum(item["ok"] for item in items),
            "failed": sum(not item["ok"] for item in items),
            "new_versions": (sum(item["new"] for item in items) if scope == "android"
                              else sum(len({stage["path"] for stage in item["stages"] if stage["new"]})
                                       for item in items)),
            "cancelled": bool(is_cancelled()), "items": items}
