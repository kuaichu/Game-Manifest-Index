"""SQLite persistence for meaningful, public per-game activity events."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from backend.admin_state import AdminStateError, _ensure_directory, _ordinary


EVENT_TYPES = frozenset({"version_update", "version_unavailable"})
PLATFORMS = frozenset({"android", "windows"})


class ActivityStore:
    """Append-only activity history stored below the configured state root."""

    def __init__(self, state_root: Path) -> None:
        self.path = Path(state_root).absolute() / "activity.sqlite3"
        self._lock = RLock()

    def _connect(self) -> sqlite3.Connection:
        try:
            _ensure_directory(self.path.parent)
            if (self.path.exists() or self.path.is_symlink()) and not _ordinary(self.path):
                raise AdminStateError("activity database is not an ordinary file")
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT NOT NULL,
                    domain_id TEXT NOT NULL,
                    platform TEXT NOT NULL CHECK (platform IN ('android', 'windows')),
                    version TEXT NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('version_update', 'version_unavailable')),
                    occurred_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS activity_events_game_id_id "
                "ON activity_events (game_id, id DESC)"
            )
            connection.commit()
            return connection
        except AdminStateError:
            raise
        except (OSError, sqlite3.Error) as error:
            try:
                connection.close()
            except UnboundLocalError:
                pass
            raise RuntimeError("activity database is unavailable") from error

    def append(
        self,
        *,
        game_id: str,
        domain_id: str,
        platform: str,
        version: str,
        event_type: str,
        occurred_at: str | None = None,
    ) -> int:
        if (
            not all(isinstance(value, str) and value for value in (game_id, domain_id, version))
            or platform not in PLATFORMS
            or event_type not in EVENT_TYPES
        ):
            raise ValueError("invalid activity event")
        timestamp = occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError("invalid activity timestamp")
        with self._lock:
            connection = self._connect()
            try:
                cursor = connection.execute(
                    "INSERT INTO activity_events "
                    "(game_id, domain_id, platform, version, type, occurred_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (game_id, domain_id, platform, version, event_type, timestamp),
                )
                connection.commit()
                return int(cursor.lastrowid)
            finally:
                connection.close()

    def list_for_game(
        self, game_id: str, limit: int = 20,
        *, visible_versions: set[tuple[str, str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("invalid activity limit")
        if visible_versions is not None and not visible_versions:
            return []
        if not self.path.exists() and not self.path.is_symlink():
            return []
        with self._lock:
            connection = self._connect()
            try:
                rows = connection.execute(
                    "SELECT id, game_id, domain_id, platform, version, type, occurred_at "
                    "FROM activity_events WHERE game_id = ? ORDER BY id DESC",
                    (game_id,),
                )
                result = []
                for row in rows:
                    if visible_versions is not None and (row["game_id"], row["domain_id"], row["version"]) not in visible_versions:
                        continue
                    result.append(dict(row))
                    if len(result) >= limit:
                        break
            finally:
                connection.close()
        return result

    def list_recent(
        self, limit: int = 20, *, game_ids: Iterable[str] | None = None,
        visible_versions: set[tuple[str, str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("invalid activity limit")
        selected_games = tuple(dict.fromkeys(game_ids)) if game_ids is not None else None
        if selected_games is not None and not selected_games:
            return []
        if visible_versions is not None and not visible_versions:
            return []
        if not self.path.exists() and not self.path.is_symlink():
            return []
        with self._lock:
            connection = self._connect()
            try:
                query = (
                    "SELECT id, game_id, domain_id, platform, version, type, occurred_at "
                    "FROM activity_events"
                )
                parameters: tuple[Any, ...]
                if selected_games is None:
                    query += " ORDER BY id DESC"
                    parameters = ()
                else:
                    placeholders = ", ".join("?" for _ in selected_games)
                    query += f" WHERE game_id IN ({placeholders}) ORDER BY id DESC"
                    parameters = selected_games
                rows = connection.execute(query, parameters)
                result = []
                for row in rows:
                    if visible_versions is not None and (row["game_id"], row["domain_id"], row["version"]) not in visible_versions:
                        continue
                    result.append(dict(row))
                    if len(result) >= limit:
                        break
            finally:
                connection.close()
        return result


__all__ = ["ActivityStore", "EVENT_TYPES", "PLATFORMS"]
