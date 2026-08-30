"""Protected FastAPI routes for V5 sync/probe operation contracts."""

from __future__ import annotations

import hmac
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.admin_operations import OperationManager
from backend.admin_probe import AdminProbeDataError, probe_direct, probe_public_url, probe_records, selected_records, valid_probe_url
from backend.admin_state import AdminStateStore
from backend.api_contract import ApiContract, fail
from backend import version_admin
from probe_adapters.service import apply_result as default_apply
from probe_adapters.service import probe as default_probe
from url_adapters.service import DISCOVERERS, PC_DISCOVERERS


TOKEN_MIN_LENGTH = 13
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncSchedule(StrictModel):
    enabled: bool
    times: list[str]


class ProbeSchedule(StrictModel):
    enabled: bool
    interval_hours: int
    mode: Literal["normal", "full"]


class ProbeOne(StrictModel):
    url: str
    timeout: int = 10
    artifact_url_id: int | None = None


class ProbeMany(StrictModel):
    urls: list[str]
    timeout: int = 10
    artifact_url_ids: list[int] | None = None


class OperationPayload(StrictModel):
    actions: list[Literal["discover", "probe"]] = ["discover", "probe"]
    game_ids: list[str] | None = None
    all_games: bool = True
    timeout: int = 10
    workers: int = 8
    scope: Literal["all", "android", "pc"] = "all"


class AdminStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AdminUrlPayload(AdminStrictModel):
    url: str
    priority: int = 0
    source_kind: str
    provider: str | None = None


class AdminArtifactPayload(AdminStrictModel):
    kind: str
    name: str
    part: int = 1
    size: int = 0
    checksum_type: str | None = None
    checksum_value: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    urls: list[AdminUrlPayload]
    component: str | None = None
    package_type: str | None = None
    delivery_mode: str | None = None
    language: str | None = None
    route_from: str | None = None
    route_to: str | None = None
    decompressed_size: int | None = None
    manifest: dict[str, Any] | None = None
    source: dict[str, Any] | None = None


class AdminVersionPayload(AdminStrictModel):
    version: str
    client_version: str | None = None
    file_path: str | None = None
    observed_at: str | None = None
    file_created_at_override: str | None = None
    version_code: int | None = None
    channel: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[AdminArtifactPayload]
    unpacked_size: int | None = None
    files_checksum_type: str | None = None
    files_checksum_value: str | None = None
    source_note: str | None = None


class AdminEditablePayload(AdminStrictModel):
    channel: str | None = None
    version_code: int | None = None
    client_version: str | None = None
    observed_at: str | None = None
    file_created_at_override: str | None = None
    file_path: str | None = None
    unpacked_size: int | None = None
    files_checksum_type: str | None = None
    files_checksum_value: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[AdminArtifactPayload] | None = None
    source_note: str | None = None


class AdminVisibilityPayload(AdminStrictModel):
    is_visible: bool


def _valid_token(token: str | None) -> bool:
    return isinstance(token, str) and len(token.strip()) >= TOKEN_MIN_LENGTH and not any(char.isspace() for char in token)


def create_admin_router(
    *, data_root: Path, state_root: Path, token: str | None,
    contract: ApiContract, discovery: Callable[..., dict[str, Any]],
    probe_fn: Callable[..., dict[str, Any]] = default_probe,
    apply_fn: Callable[..., dict[str, Any]] = default_apply,
    clock=None,
) -> tuple[APIRouter, OperationManager, AdminStateStore]:
    store = AdminStateStore(state_root)
    manager_kwargs = {"discovery": discovery, "probe_fn": probe_fn, "apply_fn": apply_fn}
    if clock is not None:
        manager_kwargs["clock"] = clock
    operations = OperationManager(store, data_root, **manager_kwargs)
    router = APIRouter(prefix="/api/v1/admin")
    probe_status_lock = RLock()
    manual_probe_status: dict[str, Any] = {"status": "idle", "mode": "normal", "started_at": None, "finished_at": None, "family": "all", "log": []}

    def now() -> str:
        value = clock() if clock is not None else datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def manual_start(family: str) -> None:
        with probe_status_lock:
            manual_probe_status.update({"status": "running", "started_at": now(), "finished_at": None, "family": family, "log": ["开始同步探活"]})

    def manual_finish() -> None:
        with probe_status_lock:
            manual_probe_status.update({"status": "finished", "finished_at": now()})
            manual_probe_status["log"].append("同步探活完成")

    def auth(authorization: str | None = Header(default=None)) -> None:
        if not _valid_token(token):
            fail(503, "admin_auth_not_configured", "管理员功能未配置")
        supplied = authorization[7:] if isinstance(authorization, str) and authorization.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
            fail(401, "admin_unauthorized", "管理员令牌无效")

    protected = [Depends(auth)]

    def timeout(value: int) -> int:
        if isinstance(value, bool) or not 1 <= value <= 60:
            fail(422, "invalid_timeout", "timeout 必须在 1..60 之间")
        return value

    @router.get("/sync/schedule", dependencies=protected)
    def get_sync_schedule() -> dict[str, Any]:
        return store.schedules()["sync"]

    @router.put("/sync/schedule", dependencies=protected)
    def put_sync_schedule(payload: SyncSchedule) -> dict[str, Any]:
        if any(not isinstance(item, str) or TIME_RE.fullmatch(item) is None for item in payload.times):
            fail(422, "invalid_sync_schedule", "同步时间必须是最多两条 HH:MM")
        times = sorted(set(payload.times))
        if len(times) > 2:
            fail(422, "invalid_sync_schedule", "同步时间必须是最多两条 HH:MM")
        if payload.enabled and not times:
            fail(422, "invalid_sync_schedule", "启用同步时至少需要一个时间")
        return store.write_schedule("sync", {"enabled": payload.enabled, "times": times})

    @router.get("/probe/schedule", dependencies=protected)
    def get_probe_schedule() -> dict[str, Any]:
        return store.schedules()["probe"]

    @router.put("/probe/schedule", dependencies=protected)
    def put_probe_schedule(payload: ProbeSchedule) -> dict[str, Any]:
        if isinstance(payload.interval_hours, bool) or not 1 <= payload.interval_hours <= 168:
            fail(422, "invalid_probe_schedule", "interval_hours 必须在 1..168 之间")
        return store.write_schedule("probe", payload.model_dump())

    def one(payload: ProbeOne) -> dict[str, Any]:
        if not valid_probe_url(payload.url):
            fail(422, "invalid_url", "url 无效")
        value_timeout = timeout(payload.timeout)
        if payload.artifact_url_id is None:
            return probe_direct(payload.url, value_timeout, probe_fn=probe_fn)
        try:
            return probe_public_url(data_root, payload.url, payload.artifact_url_id, value_timeout, probe_fn=probe_fn, apply_fn=apply_fn)
        except KeyError:
            fail(404, "artifact_url_not_found", "artifact_url_id 不存在")
        except LookupError:
            fail(409, "artifact_url_ambiguous", "artifact_url_id 不是唯一目标")
        except ValueError:
            fail(409, "artifact_url_mismatch", "artifact_url_id 与 URL 不匹配")
        except AdminProbeDataError:
            fail(500, "corrupt_data", "归档数据损坏")

    @router.post("/probe/url", dependencies=protected)
    def probe_url(payload: ProbeOne) -> dict[str, Any]:
        manual_start("single")
        try:
            return one(payload)
        finally:
            manual_finish()

    @router.post("/probe/urls", dependencies=protected)
    def probe_urls(payload: ProbeMany) -> dict[str, Any]:
        if not payload.urls or len(payload.urls) > 200 or len(set(payload.urls)) != len(payload.urls):
            fail(422, "invalid_urls", "urls 必须包含 1..200 个不重复 URL")
        ids = payload.artifact_url_ids
        if ids is not None and (len(ids) != len(payload.urls) or len(set(ids)) != len(ids)):
            fail(422, "invalid_artifact_url_ids", "artifact_url_ids 必须与 urls 一一对应且不重复")
        value_timeout = timeout(payload.timeout)
        manual_start("many")
        try:
            items = [one(ProbeOne(url=url, timeout=value_timeout, artifact_url_id=ids[index] if ids is not None else None)) for index, url in enumerate(payload.urls)]
            return {"items": items}
        finally:
            manual_finish()

    @router.post("/domains/{domain_id}/versions/{version}/probe", dependencies=protected)
    def probe_version(domain_id: str, version: str) -> dict[str, Any]:
        domain = contract.domain(domain_id)
        contract.record(domain, version)
        try:
            records = selected_records(data_root, [domain.game_id], "android" if domain.platform == "android" else "pc", domain_id=domain_id, version=version)
        except AdminProbeDataError:
            fail(500, "corrupt_data", "归档数据损坏")
        if not records:
            fail(404, "version_not_found", "版本不存在")
        manual_start(domain_id)
        try:
            summary = probe_records(data_root, records, 10, 1, probe_fn=probe_fn, apply_fn=apply_fn)
            return {"domain_id": domain_id, "version": version, "summary": summary}
        finally:
            manual_finish()

    def operation_targets(payload: OperationPayload) -> tuple[list[str], list[str]]:
        actions = [name for name in ("discover", "probe") if name in payload.actions]
        if not actions:
            fail(422, "invalid_actions", "actions 不能为空")
        allowed = set(DISCOVERERS if payload.scope == "android" else PC_DISCOVERERS if payload.scope == "pc" else {*DISCOVERERS, *PC_DISCOVERERS})
        if payload.all_games:
            games = sorted(allowed)
        else:
            if not payload.game_ids:
                fail(422, "empty_targets", "必须选择至少一个游戏")
            if len(set(payload.game_ids)) != len(payload.game_ids):
                fail(422, "duplicate_game_ids", "game_ids 不允许重复")
            unknown = [game for game in payload.game_ids if game not in allowed]
            if unknown:
                fail(422, "game_scope_mismatch", "游戏不属于所选平台范围", unknown)
            games = list(payload.game_ids)
        timeout(payload.timeout)
        if isinstance(payload.workers, bool) or not 1 <= payload.workers <= 16:
            fail(422, "invalid_workers", "workers 必须在 1..16 之间")
        return actions, games

    @router.post("/operations/start", dependencies=protected)
    def start_operation(payload: OperationPayload) -> dict[str, Any]:
        actions, games = operation_targets(payload)
        try:
            return operations.start(actions, games, payload.scope, payload.timeout, payload.workers)
        except RuntimeError:
            fail(409, "operation_already_running", "已有运维任务正在执行")
        except AdminProbeDataError:
            fail(500, "corrupt_data", "归档数据损坏")

    @router.get("/operations/latest", dependencies=protected)
    def latest_operation() -> dict[str, Any]:
        try:
            return operations.latest()
        except KeyError:
            fail(404, "operation_not_found", "尚无运维任务")

    @router.get("/operations/{job_id}", dependencies=protected)
    def operation_status(job_id: str, after: int | None = Query(default=None)) -> dict[str, Any]:
        if after is not None and after < 0:
            fail(422, "invalid_log_cursor", "日志游标超出范围")
        try:
            return operations.status(job_id, after)
        except KeyError:
            fail(404, "operation_not_found", "运维任务不存在")
        except ValueError:
            fail(422, "invalid_log_cursor", "日志游标超出范围")

    @router.post("/operations/{job_id}/cancel", dependencies=protected)
    def cancel_operation(job_id: str) -> dict[str, Any]:
        try:
            return operations.cancel(job_id)
        except KeyError:
            fail(404, "operation_not_found", "运维任务不存在")

    def latest_or_none() -> dict[str, Any] | None:
        try:
            return operations.latest()
        except KeyError:
            return None

    @router.get("/sync/status", dependencies=protected)
    def sync_status() -> dict[str, Any]:
        job = latest_or_none()
        if job is None:
            return {"status": "idle", "running": False, "started_at": None, "finished_at": None, "exit_code": None, "result": None}
        running = job["status"] in {"running", "cancelling"}
        ok = job["status"] == "finished" and job.get("failed", 0) == 0
        return {"status": job["status"], "running": running, "started_at": job["started_at"], "finished_at": job["finished_at"], "exit_code": None if running else 0 if ok else 1, "result": None if running else {"ok": ok, "log_tail": "\n".join(job.get("logs", [])[-50:]), "updates_text": ""}}

    @router.get("/sync-status", dependencies=protected)
    def legacy_sync_status() -> dict[str, Any]:
        job = latest_or_none()
        discover = job.get("result", {}).get("discover") if job and isinstance(job.get("result"), dict) else None
        latest_refresh = None
        if isinstance(discover, dict):
            items = [item for item in discover.get("items", []) if isinstance(item, dict)]
            failures = {
                f"{item.get('platform') or 'unknown'}:{item.get('game_id') or index}": {"status": "failed"}
                for index, item in enumerate(items)
                if not item.get("ok")
            }
            families: dict[str, dict[str, str]] = {}
            for item in items:
                platform = str(item.get("platform") or "unknown")
                current = families.setdefault(platform, {"status": "finished"})
                if not item.get("ok"):
                    current["status"] = "failed"
            ok = job["status"] == "finished" and not failures
            latest_refresh = {"status": job["status"], "started_at": job["started_at"], "completed_at": job["finished_at"], "families": families, "failures": failures, "exit_code": 0 if ok else 1}
        return {"approved_snapshots": [], "latest_snapshot": None, "latest_refresh": latest_refresh}

    @router.get("/probe/status", dependencies=protected)
    def probe_status() -> dict[str, Any]:
        job = latest_or_none()
        is_probe = bool(job and (job.get("phase") == "probe" or isinstance(job.get("result"), dict) and job["result"].get("probe") is not None))
        if not is_probe:
            with probe_status_lock:
                return dict(manual_probe_status)
        status = "running" if job["status"] in {"running", "cancelling"} else "finished"
        return {"status": status, "mode": "normal", "started_at": job["started_at"], "finished_at": job["finished_at"], "family": job.get("scope", "all"), "log": job.get("logs", [])[-150:]}

    # Version administration intentionally lives outside ApiContract: hidden
    # records must remain manageable even though the public inventory excludes them.
    @router.get("/catalog", dependencies=protected)
    def get_admin_catalog() -> dict[str, Any]:
        return version_admin.catalog_projection(Path(data_root))

    @router.get("/domains/{domain_id}/versions", dependencies=protected)
    def get_admin_versions(domain_id: str) -> dict[str, Any]:
        return {"items": version_admin.version_summaries(data_root, domain_id)}

    def import_result(
        domain_id: str, version: str, *, changed: bool, probe_error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "domain_id": domain_id,
            "version": version,
            "revisions_created": 0,
            "revisions_reused": 0,
            "capture_event_id": 0,
            "changed": changed,
            "revision_created": False,
            "revision_id": None,
            **({"probe_error": probe_error} if probe_error is not None else {}),
        }

    @router.post("/domains/{domain_id}/versions", dependencies=protected)
    def post_admin_version(domain_id: str, payload: AdminVersionPayload) -> dict[str, Any]:
        try:
            record = version_admin.create_version(
                data_root, domain_id, payload.model_dump(exclude_unset=True),
            )
        except FileExistsError:
            fail(409, "version_exists", "版本已存在")
        return import_result(
            domain_id,
            record["version"],
            changed=True,
            probe_error="未自动探活；请手动执行版本探活",
        )

    @router.get("/domains/{domain_id}/versions/{version}/editable", dependencies=protected)
    def get_editable(domain_id: str, version: str) -> dict[str, Any]:
        record = version_admin.read_record(data_root, domain_id, version)[0]
        return version_admin.editable_projection(record)

    @router.patch("/domains/{domain_id}/versions/{version}/editable", dependencies=protected)
    def patch_editable(domain_id: str, version: str, payload: AdminEditablePayload) -> dict[str, Any]:
        _, changed = version_admin.update_version(
            data_root, domain_id, version, payload.model_dump(exclude_unset=True),
        )
        return import_result(domain_id, version, changed=changed)

    @router.patch("/domains/{domain_id}/versions/{version}", dependencies=protected)
    def patch_visibility(
        domain_id: str, version: str, payload: AdminVisibilityPayload,
    ) -> dict[str, Any]:
        visible = version_admin.set_visibility(
            data_root, domain_id, version, payload.is_visible,
        )
        return {"is_visible": visible}

    @router.delete("/domains/{domain_id}/versions/{version}", dependencies=protected)
    def delete_version(domain_id: str, version: str) -> Response:
        version_admin.delete_version(data_root, domain_id, version)
        return Response(status_code=204)

    def _unsupported() -> None:
        fail(409, "catalog_mutation_unsupported", "V5 不支持修改静态 catalog")

    @router.post("/games", dependencies=protected)
    def unsupported_create_game(payload: Any = Body(...)) -> None:
        _unsupported()

    @router.patch("/games/{game_id}", dependencies=protected)
    def unsupported_update_game(game_id: str, payload: Any = Body(...)) -> None:
        _unsupported()

    @router.delete("/games/{game_id}", dependencies=protected)
    def unsupported_delete_game(game_id: str) -> None:
        _unsupported()

    @router.post("/domains", dependencies=protected)
    def unsupported_create_domain(payload: Any = Body(...)) -> None:
        _unsupported()

    @router.patch("/domains/{domain_id}", dependencies=protected)
    def unsupported_update_domain(domain_id: str, payload: Any = Body(...)) -> None:
        _unsupported()

    @router.delete("/domains/{domain_id}", dependencies=protected)
    def unsupported_delete_domain(domain_id: str) -> None:
        _unsupported()

    @router.post("/domains/{domain_id}/versions/{version}/artifacts/edit", dependencies=protected)
    def unsupported_artifact_edit(
        domain_id: str, version: str, payload: Any = Body(...),
    ) -> None:
        fail(409, "artifact_edit_unsupported", "V5 不支持独立 artifact 编辑")

    return router, operations, store


__all__ = ["TOKEN_MIN_LENGTH", "create_admin_router"]
