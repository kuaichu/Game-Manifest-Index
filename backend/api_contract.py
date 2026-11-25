"""Read-only FastAPI contract over canonical schema-v2 data.

Canonical records are validated at the disk boundary, then projected through
explicit public mappers. Local paths, schema internals and source recipes are
never returned directly.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import StreamingResponse

from backend import catalog_admin
from backend.activity_store import ActivityStore
from backend.catalog_admin import CatalogConfigError
from backend.catalog_registry import (
    ARTIFACT_KINDS, AVAILABILITY_STATES, COMPARE_SCOPES, GAME_CATALOG, GAME_IDS,
    LOCAL_OFFICIAL_HOSTS, PACKAGE_HOSTS_BY_GAME, PLATFORMS, TREE_KINDS, VENDORS,
)
from backend.fs_safety import SAFE_COMPONENT, is_safe_component
from backend.indexes import version_key
from backend.inventory_loader import (
    MAX_INDEX_BYTES, MAX_RECORD_BYTES, ApiFault, DomainData, InventorySnapshot,
    fail, load_inventory, load_manifest_document, read_json_object, safe_manifest_target, snapshot_data_root,
)
from backend.manifest_readers import (
    HttpUpstream, ManifestBadRequest, ManifestCorrupt, ManifestError, ManifestNotFound,
    ManifestTimeout, ManifestUpstream, chunk_content, chunk_download_plan_items,
    chunk_file_detail, list_chunk_files, list_local_files, local_file_detail, local_files, strict_relative_posix,
)
from backend.mihoyo_package_files import (
    PackageFilesBadRequest, PackageFilesCacheError, PackageFilesNotFound, PackageFilesTimeout,
    PackageFilesUnsupported, PackageFilesUpstream, file_detail as mihoyo_package_file_detail,
    list_files as list_mihoyo_package_files, package_files as mihoyo_package_files,
)
from backend.probe_policy import PROBE_EVIDENCE_TTL, parse_probe_checked_at, stable_id
from backend.manifest_projection import (
    chunk_summary, compare_artifact_rows, compare_file, file_metadata,
    public_chunk_document, record_artifact_tree_entries, resolve_kuro_resource_packs,
    resolve_package_document, tree_artifact, validate_chunk_document,
)
from backend.public_projection import (
    artifact_state, domain_projection, public_artifact, public_version,
    scheduled_probe_indices, utc_now, version_summary,
)
from backend.storage_locks import DATA_LOCK


MAX_DOCUMENT_BYTES = 16 * 1024 * 1024

_version_key = version_key
_stable_id = stable_id
_probe_checked_at = parse_probe_checked_at
_utc_now = utc_now
_file_metadata = file_metadata
_public_artifact = public_artifact
_summary = version_summary
_domain_projection = domain_projection


def _safe_component(value: str, *, not_found: bool = False) -> str:
    if not is_safe_component(value):
        fail(404 if not_found else 400, "not_found" if not_found else "bad_path", "资源不存在" if not_found else "路径参数无效")
    return value


def _cursor(value: str | None) -> int:
    if value is None:
        return 0
    if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        fail(400, "bad_cursor", "cursor 无效")
    return int(value)


def _paginate(items: list[Any], limit: int, cursor: str | None) -> tuple[list[Any], str | None]:
    offset = _cursor(cursor)
    return items[offset : offset + limit], str(offset + limit) if offset + limit < len(items) else None


def _manifest_error(error: Exception) -> ApiFault:
    if isinstance(error, (ManifestBadRequest, PackageFilesBadRequest)):
        return ApiFault(400, "bad_request", str(error))
    if isinstance(error, (ManifestNotFound, PackageFilesNotFound)):
        return ApiFault(404, "file_not_found", str(error))
    if isinstance(error, (ManifestCorrupt, PackageFilesCacheError)):
        return ApiFault(500, "corrupt_manifest", str(error))
    if isinstance(error, (ManifestTimeout, PackageFilesTimeout)):
        return ApiFault(504, "upstream_timeout", str(error))
    if isinstance(error, PackageFilesUnsupported):
        return ApiFault(422, "package_format_unsupported", str(error))
    if isinstance(error, (ManifestUpstream, PackageFilesUpstream)):
        return ApiFault(502, "upstream_error", str(error))
    return ApiFault(500, "internal_error", "服务器内部错误")


class ApiContract:
    def __init__(self, data_root: Path, upstream: Any | None = None, state_root: Path | None = None) -> None:
        self.data_root = Path(data_root)
        self.upstream = upstream or HttpUpstream()
        self.state_root = (
            Path(state_root)
            if state_root is not None
            else Path(os.environ.get("GMI_STATE_ROOT") or Path(__file__).resolve().parents[1] / ".cache")
        )
        self.activity_store = ActivityStore(self.state_root)
        self._cached_snapshot: InventorySnapshot | None = None
        self._cached_inventory: dict[str, DomainData] | None = None

    def _catalog_games(self) -> list[dict[str, Any]]:
        try:
            return catalog_admin.game_catalog(self.data_root, GAME_CATALOG)
        except CatalogConfigError as error:
            raise ApiFault(500, "corrupt_catalog_config", "目录配置损坏") from error

    def _game_ids(self) -> tuple[str, ...]:
        return tuple(game["id"] for game in self._catalog_games())

    def _catalog_domains(self) -> dict[str, dict[str, Any]]:
        try:
            return catalog_admin.configured_domains(self.data_root)
        except CatalogConfigError as error:
            raise ApiFault(500, "corrupt_catalog_config", "目录配置损坏") from error

    def _read_json(self, path: Path, limit: int, code: str) -> dict[str, Any]:
        return read_json_object(path, limit, code)

    def _safe_target(self, base: Path, relative: str) -> Path:
        return safe_manifest_target(base, relative)

    def inventory(self) -> dict[str, DomainData]:
        return self._inventory()

    def _inventory(self, requested_domain: str | None = None) -> dict[str, DomainData]:
        # Writers publish canonical records and their index under this lock.
        # Keep snapshot inspection and validation in the same locked read window.
        with DATA_LOCK:
            return self._inventory_unlocked(requested_domain)

    def _inventory_unlocked(self, requested_domain: str | None = None) -> dict[str, DomainData]:
        custom_reader = "_read_json" in self.__dict__
        snapshot = None if custom_reader else snapshot_data_root(self.data_root)
        if not custom_reader and snapshot is not None and self._cached_inventory is not None and snapshot == self._cached_snapshot:
            if requested_domain is None:
                return dict(self._cached_inventory)
            hit = self._cached_inventory.get(requested_domain)
            return {requested_domain: hit} if hit is not None else {}

        if snapshot is None or snapshot != self._cached_snapshot:
            self._cached_snapshot = None
            self._cached_inventory = None

        result = load_inventory(self.data_root, requested_domain=requested_domain, read_json=self._read_json)
        if requested_domain is None and not custom_reader and snapshot is not None:
            self._cached_snapshot = snapshot
            self._cached_inventory = result
        return dict(result)

    def domain(self, domain_id: str) -> DomainData:
        _safe_component(domain_id, not_found=True)
        domain = self._inventory(domain_id).get(domain_id)
        if domain is None:
            fail(404, "domain_not_found", "归档域不存在")
        return domain

    def record(self, domain: DomainData, version: str) -> dict[str, Any]:
        _safe_component(version, not_found=True)
        for record in domain.records:
            if record["version"] == version:
                return record
        fail(404, "version_not_found", "版本不存在")

    def _load_document(self, domain: DomainData, record: dict[str, Any], relative: str) -> dict[str, Any]:
        return load_manifest_document(domain, record, relative, max_bytes=MAX_DOCUMENT_BYTES, read_json=self._read_json)

    def chunk_document(self, domain: DomainData, record: dict[str, Any]) -> dict[str, Any]:
        return validate_chunk_document(domain, record, self._load_document)

    def package_document(self, domain: DomainData, record: dict[str, Any], identity: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        return resolve_package_document(domain, record, identity, self._load_document)

    def resource_packs(self, domain: DomainData, record: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any] | None:
        return resolve_kuro_resource_packs(domain, record, selected, self._load_document)


def create_api_app(data_root: Path, upstream: Any | None = None, *, state_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Game Manifest Index API", version="0.1.0")
    app.state.contract = ApiContract(data_root, upstream, state_root)

    @app.exception_handler(ApiFault)
    async def api_fault_handler(_: Request, error: ApiFault) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": error.message, "details": error.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [{"location": ".".join(str(part) for part in item.get("loc", ())), "type": item.get("type", "invalid")} for item in error.errors()]
        is_admin = request.url.path.startswith("/api/v1/admin/")
        return JSONResponse(status_code=422 if is_admin else 400, content={"error": {"code": "validation_error" if is_admin else "bad_request", "message": "请求参数无效", "details": details}})

    @app.exception_handler(StarletteHTTPException)
    async def framework_error_handler(_: Request, error: StarletteHTTPException) -> JSONResponse:
        status = error.status_code
        return JSONResponse(status_code=status, content={"error": {"code": "not_found" if status == 404 else "http_error", "message": "资源不存在" if status == 404 else "请求失败", "details": None}})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "服务器内部错误", "details": None}})

    def service() -> ApiContract:
        return app.state.contract

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/probe/latest")
    def latest_probe() -> dict[str, str | None]:
        """Return one consistent timestamp for the latest completed live probe."""
        latest: tuple[datetime, str] | None = None
        for domain in service().inventory().values():
            for record in domain.records:
                for artifact in record.get("artifacts", []):
                    if not isinstance(artifact, dict):
                        continue
                    for candidate in artifact.get("urls", []):
                        if not isinstance(candidate, dict) or not isinstance(candidate.get("current"), dict):
                            continue
                        checked = parse_probe_checked_at(candidate["current"])
                        if checked is not None and (latest is None or checked[1] > latest[0]):
                            latest = (checked[1], checked[0])
        return {"last_checked_at": latest[1] if latest else None}

    @app.get("/api/v1/activity")
    def activity(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        enabled_games = tuple(game["id"] for game in service()._catalog_games() if game.get("is_enabled") is not False)
        visible_versions = {
            (domain.game_id, domain.domain_id, record["version"])
            for domain in service().inventory().values() if domain.game_id in enabled_games for record in domain.records
        }
        return {"items": service().activity_store.list_recent(limit, game_ids=enabled_games, visible_versions=visible_versions)}

    @app.get("/api/v1/games")
    def games() -> list[dict[str, Any]]:
        inventory = service().inventory()
        result = []
        for game in service()._catalog_games():
            if game.get("is_enabled") is False:
                continue
            game_id = game["id"]
            domains = [item for item in inventory.values() if item.game_id == game_id]
            versions = [record["version"] for domain in domains for record in domain.records]
            if domains:
                result.append({
                    "id": game_id, "name": game["name"], "sub_name": game["sub_name"],
                    "platform": "multi" if len(domains) > 1 else domains[0].platform, "icon_source": game["icon_source"],
                    "version_count": len(versions), "latest_version": max(versions, key=version_key),
                    "is_enabled": True, "sort_order": game["sort_order"],
                })
        result.sort(key=lambda item: (item.get("sort_order", 0), item["id"]))
        return result

    @app.get("/api/v1/games/{game_id}/activity")
    def game_activity(game_id: str, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        game = next((item for item in service()._catalog_games() if item["id"] == game_id and item.get("is_enabled") is not False), None)
        if game is None:
            fail(404, "game_not_found", "游戏不存在")
        visible_versions = {
            (game_id, domain.domain_id, record["version"])
            for domain in service().inventory().values() if domain.game_id == game_id for record in domain.records
        }
        return {"items": service().activity_store.list_for_game(game_id, limit, visible_versions=visible_versions)}

    @app.get("/api/v1/games/{game_id}/domains")
    def game_domains(game_id: str) -> list[dict[str, Any]]:
        game_by_id = {item["id"]: item for item in service()._catalog_games()}
        if game_id not in game_by_id or game_by_id[game_id].get("is_enabled") is False:
            fail(404, "game_not_found", "游戏不存在")
        domains = [item for item in service().inventory().values() if item.game_id == game_id]
        if not domains:
            fail(404, "game_not_found", "游戏不存在")
        domains.sort(key=lambda item: 0 if item.platform == "android" else 1)
        configured = service()._catalog_domains()
        result = []
        for index, domain in enumerate(domains):
            projection = domain_projection(domain, game_by_id[game_id].get("sort_order", 0) * 10 + index)
            projection.update({key: value for key, value in configured.get(domain.domain_id, {}).items() if key not in {"vendor"}})
            if projection.get("is_enabled") is not False:
                result.append(projection)
        result.sort(key=lambda item: (item.get("sort_order", 0), item["id"]))
        return result

    @app.get("/api/v1/domains/{domain_id}/versions")
    def versions(domain_id: str) -> dict[str, Any]:
        return {"items": [version_summary(record) for record in service().domain(domain_id).records]}

    @app.get("/api/v1/domains/{domain_id}/versions/{version}")
    def version_detail(domain_id: str, version: str) -> dict[str, Any]:
        domain = service().domain(domain_id)
        return public_version(service().record(domain, version))

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/artifacts")
    def artifacts(
        domain_id: str, version: str, limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
        q: str | None = None, availability_state: str | None = None, kind: str | None = None,
    ) -> dict[str, Any]:
        _cursor(cursor)
        if kind is not None and kind not in ARTIFACT_KINDS:
            fail(400, "bad_kind", "kind 无效")
        if availability_state is not None and availability_state not in AVAILABILITY_STATES:
            fail(400, "bad_availability", "availability_state 无效")
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        indices = scheduled_probe_indices(record)
        items = [public_artifact(record, item, index, indices) for index, item in enumerate(record["artifacts"])]
        if kind:
            items = [item for item in items if item["kind"] == kind]
        if availability_state:
            items = [item for item in items if artifact_state(item) == availability_state]
        if q:
            needle = q.casefold()
            items = [item for item in items if needle in json.dumps(item, ensure_ascii=False).casefold()]
        items.sort(key=lambda item: (item["kind"], item["name"].casefold(), item["part"], item["id"]))
        page, next_cursor = _paginate(items, limit, cursor)
        return {"items": page, "next_cursor": next_cursor, "total": len(items)}

    def file_compare_rows(domain: DomainData, before_record: dict[str, Any], after_record: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            try:
                _, before_document, before_base_urls = service().package_document(domain, before_record, "game")
                _, after_document, after_base_urls = service().package_document(domain, after_record, "game")
                before = {item["path"]: compare_file(item) for item in local_files(before_document, before_base_urls)}
                after = {item["path"]: compare_file(item) for item in local_files(after_document, after_base_urls)}
            except ApiFault as error:
                if error.status != 404 or domain.vendor != "mihoyo" or domain.platform != "windows":
                    raise
                before = {
                    item["path"]: compare_file(item)
                    for item in mihoyo_package_files(service().state_root, before_record, before_record["game_id"], before_record["version"], "game", service().upstream)
                }
                after = {
                    item["path"]: compare_file(item)
                    for item in mihoyo_package_files(service().state_root, after_record, after_record["game_id"], after_record["version"], "game", service().upstream)
                }
        except ManifestError as error:
            raise _manifest_error(error) from error
        rows = []
        for path in sorted(set(before) | set(after), key=lambda value: (value.casefold(), value)):
            old, new = before.get(path), after.get(path)
            row_change = "added" if old is None else "removed" if new is None else "changed" if old != new else None
            if row_change:
                rows.append({"change": row_change, "identity": {"path": path}, "before": old, "after": new})
        return rows

    @app.get("/api/v1/domains/{domain_id}/compare")
    def compare(
        domain_id: str, from_version: str, to_version: str, change: str = "all", kind: str | None = None,
        compare_scope: str = "artifacts", limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        _cursor(cursor)
        if change not in {"all", "added", "removed", "changed"}:
            fail(400, "bad_change", "change 无效")
        if compare_scope not in COMPARE_SCOPES:
            fail(400, "bad_compare_scope", "compare_scope 无效")
        if kind is not None and kind not in ARTIFACT_KINDS and not (compare_scope == "files" and kind == "file"):
            fail(400, "bad_kind", "kind 无效")
        domain = service().domain(domain_id)
        before_record = service().record(domain, from_version)
        after_record = service().record(domain, to_version)
        if compare_scope == "files":
            if kind is not None and kind != "file":
                fail(400, "bad_kind", "文件级对比只支持 kind=file")
            rows = file_compare_rows(domain, before_record, after_record)
        else:
            rows = compare_artifact_rows(before_record, after_record, kind)
        summary = {name: sum(row["change"] == name for row in rows) for name in ("added", "removed", "changed")}
        summary["size_delta"] = sum((row["after"] or {}).get("size", 0) - (row["before"] or {}).get("size", 0) for row in rows)
        filtered = rows if change == "all" else [row for row in rows if row["change"] == change]
        page, next_cursor = _paginate(filtered, limit, cursor)
        return {"from_version": from_version, "to_version": to_version, "compare_scope": compare_scope, "summary": summary, "items": page, "next_cursor": next_cursor}

    @app.get("/api/v1/domains/{domain_id}/leads")
    def leads(domain_id: str) -> dict[str, list[Any]]:
        service().domain(domain_id)
        return {"items": []}

    @app.get("/api/v1/domains/{domain_id}/chunk-manifests")
    def chunk_collection(domain_id: str) -> dict[str, Any]:
        domain = service().domain(domain_id)
        items = [
            chunk_summary(domain_id, service().chunk_document(domain, record), record)
            for record in domain.records
            if any(isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in record.get("references", []))
        ]
        if not items:
            fail(404, "manifest_not_found", "Chunk Manifest 不存在")
        return {"items": items}

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests")
    def chunk_manifest_detail(domain_id: str, version: str) -> dict[str, Any]:
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        return public_chunk_document(domain_id, service().chunk_document(domain, record))

    def selected_source(domain_id: str, version: str, source: str, identity: str) -> tuple[str, DomainData, dict[str, Any], Any]:
        if source not in {"auto", "chunk", "package"}:
            fail(400, "bad_source", "source 无效")
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        has_chunk = any(isinstance(ref, dict) and ref.get("kind") == "chunk_manifest" for ref in record.get("references", []))
        if source == "chunk":
            return "chunk", domain, record, service().chunk_document(domain, record)
        if source == "auto" and has_chunk:
            document = service().chunk_document(domain, record)
            matching = [
                item for item in document.get("manifests", [])
                if isinstance(item, dict) and (
                    item.get("matching_field") == identity
                    or item.get("manifest_id") == identity
                    or (isinstance(item.get("manifest"), dict) and item["manifest"].get("id") == identity)
                )
            ]
            if len(matching) == 1:
                return "chunk", domain, record, document
        if domain.vendor == "mihoyo" and domain.platform == "windows" and any(
            isinstance(item, dict) and item.get("kind") == "package" and item.get("component") == "game"
            and item.get("package_type") in {"full", "segment"} and item.get("delivery_mode") == "archive"
            for item in record.get("artifacts", [])
        ):
            return "mihoyo_package", domain, record, None
        return "package", domain, record, service().package_document(domain, record, identity)

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/files")
    def version_files(
        domain_id: str, version: str, source: str = "auto", identity: str = "game", path: str = "",
        q: str | None = None, limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            strict_relative_posix(path, allow_empty=True)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        _cursor(cursor)
        selected, _domain, record, payload = selected_source(domain_id, version, source, identity)
        try:
            if selected == "chunk":
                return {"source": "chunk", **list_chunk_files(payload, identity, service().upstream, path, q, limit, cursor)}
            if selected == "mihoyo_package":
                result = list_mihoyo_package_files(service().state_root, record, record["game_id"], record["version"], identity, path, q, limit, cursor, service().upstream)
                return {**result, **file_metadata(record, delivery="archive", upstream=service().upstream)}
            artifact, document, base_urls = payload
            return {
                "source": "package", "fetch_mode": "checked_in_manifest", "identity": str(stable_id(artifact["artifact_id"])),
                **list_local_files(document, base_urls, path, q, limit, cursor),
                **file_metadata(record, artifact=artifact, document=document, upstream=service().upstream),
            }
        except ManifestError as error:
            raise _manifest_error(error) from error

    def resolve_version_file(domain_id: str, version: str, path: str, source: str, identity: str) -> tuple[dict[str, Any], DomainData]:
        try:
            strict_relative_posix(path)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        selected, domain, record, payload = selected_source(domain_id, version, source, identity)
        try:
            if selected == "chunk":
                return {"source": "chunk", **chunk_file_detail(payload, identity, service().upstream, path)}, domain
            if selected == "mihoyo_package":
                return mihoyo_package_file_detail(service().state_root, record, record["game_id"], record["version"], identity, path, service().upstream), domain
            artifact, document, base_urls = payload
            return {"source": "package", "fetch_mode": "checked_in_manifest", "identity": str(stable_id(artifact["artifact_id"])), **local_file_detail(document, base_urls, path)}, domain
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/file")
    def version_file(domain_id: str, version: str, path: str, source: str = "auto", identity: str = "game") -> dict[str, Any]:
        detail, _domain = resolve_version_file(domain_id, version, path, source, identity)
        return detail

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/file-content")
    async def version_file_content(domain_id: str, version: str, path: str, source: str = "package", identity: str = "game") -> Response:
        if source != "package":
            fail(400, "bad_source", "完整文件下载仅支持 package 来源")
        detail, domain = await run_in_threadpool(resolve_version_file, domain_id, version, path, source, identity)
        allowed_hosts = PACKAGE_HOSTS_BY_GAME.get(domain.game_id, frozenset()) if domain.vendor == "mihoyo" else LOCAL_OFFICIAL_HOSTS.get(domain.vendor, frozenset())
        url = detail.get("download_url")
        if not isinstance(url, str) or not allowed_hosts:
            fail(404, "file_not_found", "文件没有可下载的官方直链")
        try:
            upstream_response, client = await service().upstream.open_file(url, allowed_hosts=allowed_hosts, expected_size=detail["size"])
        except ManifestError as error:
            raise _manifest_error(error) from error

        async def body():
            received = 0
            async for block in upstream_response.aiter_raw(64 * 1024):
                received += len(block)
                if received > detail["size"]:
                    raise ManifestUpstream("官方文件长度不匹配")
                yield block
            if received != detail["size"]:
                raise ManifestUpstream("官方文件响应不完整")

        class FileResponse(StreamingResponse):
            async def __call__(self, scope, receive, send):
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    import anyio
                    with anyio.CancelScope(shield=True):
                        try:
                            await upstream_response.aclose()
                        finally:
                            await client.aclose()

        headers = {"Content-Length": str(detail["size"]), "Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return FileResponse(body(), status_code=200, headers=headers, media_type="application/octet-stream")

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests/{identity}/files")
    def chunk_files_route(
        domain_id: str, version: str, identity: str, path: str = "", q: str | None = None,
        limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            strict_relative_posix(path, allow_empty=True)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        _cursor(cursor)
        domain = service().domain(domain_id)
        document = service().chunk_document(domain, service().record(domain, version))
        try:
            return {"source": "chunk", **list_chunk_files(document, identity, service().upstream, path, q, limit, cursor)}
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests/{identity}/download-plan")
    def chunk_download_plan_route(
        domain_id: str, version: str, identity: str,
        limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
    ) -> dict[str, Any]:
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        _cursor(cursor)
        domain = service().domain(domain_id)
        document = service().chunk_document(domain, service().record(domain, version))
        try:
            public_identity, page, total, total_size, next_cursor = chunk_download_plan_items(document, identity, service().upstream, limit=limit, cursor=cursor)
            return {"identity": public_identity, "items": page, "total": total, "next_cursor": next_cursor, "total_size": total_size}
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-manifests/{identity}/file")
    def chunk_file_route(domain_id: str, version: str, identity: str, path: str) -> dict[str, Any]:
        try:
            strict_relative_posix(path)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "path 无效") from error
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        domain = service().domain(domain_id)
        document = service().chunk_document(domain, service().record(domain, version))
        try:
            return {"source": "chunk", **chunk_file_detail(document, identity, service().upstream, path)}
        except ManifestError as error:
            raise _manifest_error(error) from error

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/artifact-tree")
    def artifact_tree(
        domain_id: str, version: str, kind: str = "file", prefix: str = "", limit: int = Query(100, ge=1, le=500),
        cursor: str | None = None, availability_state: str | None = None, q: str | None = None, identity: str = "game",
    ) -> dict[str, Any]:
        _cursor(cursor)
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        if kind not in TREE_KINDS:
            fail(400, "bad_kind", "kind 无效")
        if availability_state is not None and availability_state not in AVAILABILITY_STATES:
            fail(400, "bad_availability", "availability_state 无效")
        try:
            prefix = strict_relative_posix(prefix, allow_empty=True)
        except ManifestBadRequest as error:
            raise ApiFault(400, "bad_path", "prefix 无效") from error
        domain = service().domain(domain_id)
        record = service().record(domain, version)
        if kind == "file":
            if availability_state not in (None, "unknown"):
                return {"prefix": prefix, "folders": [], "items": [], "next_cursor": None}
            try:
                artifact, document, base_urls = service().package_document(domain, record, identity)
                page = list_local_files(document, base_urls, prefix, q, limit, cursor)
                manifest_total_size = sum(item["size"] for item in local_files(document))
            except ApiFault as error:
                if error.status == 404:
                    return {"prefix": prefix, "folders": [], "items": [], "next_cursor": None}
                raise
            except ManifestError as error:
                raise _manifest_error(error) from error
            folders = [
                {"name": item["name"], "path": item["path"], "artifact_count": item.get("file_count", 0), "total_size": item.get("size", 0)}
                for item in page["items"] if item.get("type") == "directory"
            ]
            items = [tree_artifact(artifact["artifact_id"], item) for item in page["items"] if item.get("type") == "file"]
            response = {
                "prefix": prefix, "folders": folders, "items": items, "next_cursor": page["next_cursor"],
                "base_url": base_urls[0] if base_urls else None, "base_urls": base_urls, "manifest_total_size": manifest_total_size,
                **file_metadata(record, artifact=artifact, document=document, upstream=service().upstream),
            }
            packs = service().resource_packs(domain, record, artifact)
            if packs is not None:
                response["resource_packs"] = packs
            return response
        entries = record_artifact_tree_entries(record, kind=kind, prefix=prefix, availability_state=availability_state, q=q)
        page, next_cursor = _paginate(entries, limit, cursor)
        return {
            "prefix": prefix,
            "folders": [item for item in page if "artifact_count" in item] if kind == "resource" else [],
            "items": [item for item in page if "artifact_count" not in item] if kind == "resource" else page,
            "next_cursor": next_cursor,
        }

    @app.get("/api/v1/domains/{domain_id}/versions/{version}/chunk-content")
    def chunk_content_route(domain_id: str, version: str, identity: str, name: str) -> Response:
        if SAFE_COMPONENT.fullmatch(identity) is None:
            fail(400, "bad_identity", "identity 无效")
        if re.fullmatch(r"[^/\\\x00-\x20\x7f]+", name) is None:
            fail(400, "bad_name", "chunk name 无效")
        domain = service().domain(domain_id)
        document = service().chunk_document(domain, service().record(domain, version))
        try:
            body, headers = chunk_content(document, identity, name, service().upstream)
        except ManifestError as error:
            raise _manifest_error(error) from error
        output_headers = {"Content-Length": str(len(body))}
        for key in ("content-type", "etag"):
            if isinstance(headers.get(key), str):
                output_headers[key.title()] = headers[key]
        return Response(body, status_code=200, headers=output_headers, media_type=None)

    return app


__all__ = [
    "ARTIFACT_KINDS", "AVAILABILITY_STATES", "ApiContract", "ApiFault", "COMPARE_SCOPES",
    "DomainData", "GAME_CATALOG", "GAME_IDS", "LOCAL_OFFICIAL_HOSTS", "MAX_DOCUMENT_BYTES",
    "MAX_INDEX_BYTES", "MAX_RECORD_BYTES", "PLATFORMS", "PROBE_EVIDENCE_TTL", "TREE_KINDS",
    "VENDORS", "create_api_app", "domain_projection", "fail", "version_summary",
]
