"""ASGI entry point for the public API and protected admin operations."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from backend.admin_routes import create_admin_router
from backend.api_contract import create_api_app
from backend.probe_scheduler import ProbeScheduler, TimerAdapter
from probe_adapters.service import apply_result, probe
from url_adapters.service import discover_games


ROOT = Path(__file__).resolve().parents[1]
_UNSET = object()


def create_app(
    data_root: Path | None = None,
    upstream=None,
    *,
    state_root: Path | None = None,
    admin_token: str | None | object = _UNSET,
    discovery: Callable[..., dict[str, Any]] = discover_games,
    probe_fn: Callable[..., dict[str, Any]] = probe,
    apply_fn: Callable[..., dict[str, Any]] = apply_result,
    clock=None,
    scheduler_timer: TimerAdapter | None = None,
):
    """Create an isolated app; tests can inject all network/state boundaries."""
    configured = data_root if data_root is not None else Path(os.environ.get("GMI_DATA_ROOT", ROOT / "data"))
    state = state_root if state_root is not None else Path(os.environ.get("GMI_STATE_ROOT", ROOT / ".cache"))
    token = os.environ.get("GMI_ADMIN_TOKEN") if admin_token is _UNSET else admin_token
    app = create_api_app(Path(configured), upstream, state_root=Path(state))
    cors_origins = [item.strip() for item in os.environ.get("GMI_CORS_ORIGINS", "").split(",") if item.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Accept", "Authorization", "Cache-Control", "Content-Type", "Pragma"],
        )
    router, operations, store = create_admin_router(
        data_root=Path(configured), state_root=Path(state), token=token,
        contract=app.state.contract, discovery=discovery,
        probe_fn=probe_fn, apply_fn=apply_fn, clock=clock,
    )
    app.include_router(router)
    app.state.admin_operations = operations
    app.state.admin_store = store
    scheduler = ProbeScheduler(
        store, operations,
        authorized=isinstance(token, str) and bool(token) and not any(char.isspace() for char in token),
        timer=scheduler_timer,
        **({"clock": clock} if clock is not None else {}),
    )
    app.state.probe_scheduler = scheduler
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application) as state:
            await run_in_threadpool(scheduler.start)
            try:
                yield state
            finally:
                await run_in_threadpool(scheduler.stop)
                if not await run_in_threadpool(operations.shutdown, 30):
                    logging.getLogger(__name__).warning("Probe operation is still stopping after 30 seconds")

    app.router.lifespan_context = lifespan
    return app


app = create_app()


__all__ = ["app", "create_app"]
