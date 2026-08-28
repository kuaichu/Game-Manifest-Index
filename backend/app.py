"""ASGI entry point for the read-only public API."""

from __future__ import annotations

import os
from pathlib import Path

from backend.api_contract import create_api_app


ROOT = Path(__file__).resolve().parents[1]


def create_app(data_root: Path | None = None, upstream=None):
    """Create an isolated app; tests can inject a temporary canonical root."""
    configured = data_root if data_root is not None else Path(os.environ.get("GMI_DATA_ROOT", ROOT / "data"))
    return create_api_app(Path(configured), upstream)


app = create_app()


__all__ = ["app", "create_app"]
