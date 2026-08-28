"""Run the official Android URL discovery adapters."""

from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from backend.schema_v2 import validate_v2_record
from url_adapters.android import (
    hypergryph_launcher_latest,
    kuro_pns_manifest,
    kuro_wuwa_mc_manifest,
    mihoyo_bh2_download_page,
    mihoyo_bh3_download_porter,
    mihoyo_download_porter,
    perfectworld_webops,
)
from url_adapters.common import AdapterError


Discoverer = Callable[[str, Path, int, str | None, int | None], Path]

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
    """Return the number of registered Android discovery tasks."""
    if scope != "android":
        raise ValueError(f"不支持的数据范围：{scope}")
    if not isinstance(game_ids, list):
        raise ValueError("game_ids 必须是列表")
    return sum(game_id in DISCOVERERS for game_id in game_ids)


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


def discover_games(
    game_ids: list[str], root: Path, timeout: int, workers: int,
    progress: Callable[[dict, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    scope: str = "android",
) -> dict:
    """Discover selected games concurrently while collecting per-task errors."""
    if scope != "android":
        raise ValueError(f"不支持的数据范围：{scope}")
    _validate_inputs(game_ids, root, timeout, workers)
    is_cancelled = cancelled or (lambda: False)
    tasks = list(game_ids)
    items: list[dict] = []
    if not tasks:
        return {"scope": "android", "selected": 0, "succeeded": 0, "failed": 0,
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
        pending[pool.submit(_discover_one, game_id, root, timeout)] = game_id
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
                    item = {"game_id": game_id, "platform": "android", "ok": False,
                            "supported": game_id in DISCOVERERS, "status": "failed",
                            "version": None, "new": False, "available": None,
                            "path": None, "error": str(error)}
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
    return {"scope": "android", "selected": len(tasks),
            "succeeded": sum(item["ok"] for item in items),
            "failed": sum(not item["ok"] for item in items),
            "new_versions": sum(item["new"] for item in items),
            "cancelled": bool(is_cancelled()), "items": items}
