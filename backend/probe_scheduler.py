"""Portable timer adapter and persisted, single-worker discovery/probe schedule."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable, Protocol

from apscheduler.schedulers.background import BackgroundScheduler

from backend.admin_operations import OperationManager, utc_now
from backend.admin_state import AdminStateError, AdminStateStore
from url_adapters.service import DISCOVERERS, PC_DISCOVERERS


LOGGER = logging.getLogger(__name__)
RUNTIME_FIELDS = {"schedule", "next_run_at", "last_started_at", "last_job_id", "error"}


class TimerAdapter(Protocol):
    def start(self, callback: Callable[[], None]) -> None: ...
    def stop(self) -> None: ...


class APSchedulerTimer:
    """An in-memory timer; GMI owns persisted due times, not APScheduler jobs."""

    def __init__(self, poll_seconds: float = 5) -> None:
        self.poll_seconds = poll_seconds
        self._scheduler: BackgroundScheduler | None = None

    def start(self, callback: Callable[[], None]) -> None:
        if self._scheduler is not None:
            return
        scheduler = BackgroundScheduler(timezone=timezone.utc)
        scheduler.add_job(
            callback, "interval", seconds=self.poll_seconds,
            id="gmi-probe-schedule", max_instances=1, coalesce=True,
            misfire_grace_time=None,
        )
        scheduler.start()
        self._scheduler = scheduler

    def stop(self) -> None:
        scheduler, self._scheduler = self._scheduler, None
        if scheduler is not None:
            scheduler.shutdown(wait=True)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("invalid scheduler timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("invalid scheduler timezone")
    return parsed


def _validate_runtime(value: dict) -> None:
    if set(value) != RUNTIME_FIELDS:
        raise ValueError("invalid scheduler fields")
    schedule = value["schedule"]
    if not isinstance(schedule, dict) or set(schedule) != {"enabled", "interval_hours", "mode"}:
        raise ValueError("invalid scheduler configuration")
    hours = schedule["interval_hours"]
    if (not isinstance(schedule["enabled"], bool) or type(hours) is not int
            or not 1 <= hours <= 168 or schedule["mode"] not in {"normal", "full"}):
        raise ValueError("invalid scheduler configuration")
    if schedule["enabled"] != (value["next_run_at"] is not None):
        raise ValueError("invalid scheduler deadline")
    for key in ("next_run_at", "last_started_at"):
        if value[key] is not None:
            _parse_timestamp(value[key])
    if value["last_job_id"] is not None and not isinstance(value["last_job_id"], str):
        raise ValueError("invalid scheduler job")
    if value["error"] not in {None, "scheduled_probe_start_failed"}:
        raise ValueError("invalid scheduler error")


class ProbeScheduler:
    """Consume the existing probe schedule without changing manual operations.

    One backend worker must own a state/data root. Persist a deadline before
    dispatch so a crash cannot replay an unlimited backlog of scheduled runs.
    """

    def __init__(
        self, store: AdminStateStore, operations: OperationManager, *,
        authorized: bool, timer: TimerAdapter | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.operations = operations
        self.authorized = authorized
        self.timer = timer if timer is not None else APSchedulerTimer()
        self.clock = clock
        self._lock = RLock()
        self._running = False
        self._runtime: dict | None = None
        self._error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._running or not self.authorized:
                return
            self._running = True
        self.tick()
        try:
            self.timer.start(self.tick)
        except Exception:
            with self._lock:
                self._running = False
            raise

    def stop(self) -> None:
        with self._lock:
            self._running = False
        # Do not hold the lock while joining the timer's callback thread.
        self.timer.stop()

    def status(self) -> dict:
        with self._lock:
            runtime = self._runtime or {}
            return {
                "driver": "apscheduler", "running": self._running,
                "enabled": bool(runtime.get("schedule", {}).get("enabled")),
                "next_run_at": runtime.get("next_run_at"),
                "last_started_at": runtime.get("last_started_at"),
                "last_job_id": runtime.get("last_job_id"),
                "error": self._error,
            }

    def configure(self, schedule: dict) -> dict:
        # Serialize a disable/change request with due-time dispatch.
        with self._lock:
            saved = self.store.write_schedule("probe", schedule)
            self.tick()
            return saved

    def _set_error(self, code: str) -> None:
        if self._error != code:
            LOGGER.error("Probe scheduler: %s", code)
        self._error = code

    def tick(self) -> None:
        with self._lock:
            if not self._running or not self.authorized:
                return
            try:
                self._tick()
            except (AdminStateError, OSError, ValueError, TypeError, KeyError):
                # Fail closed: unreadable schedules must never trigger a probe.
                self._set_error("scheduler_state_invalid")
            except Exception:
                self._set_error("scheduler_tick_failed")

    def _tick(self) -> None:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        schedule = self.store.schedules()["probe"]
        runtime = self.store.read("probe_scheduler")
        if runtime is not None:
            _validate_runtime(runtime)
        interval = timedelta(hours=schedule["interval_hours"])
        if runtime is None or runtime["schedule"] != schedule:
            runtime = {
                "schedule": deepcopy(schedule),
                "next_run_at": _timestamp(now + interval) if schedule["enabled"] else None,
                "last_started_at": runtime["last_started_at"] if runtime else None,
                "last_job_id": runtime["last_job_id"] if runtime else None,
                "error": None,
            }
            self.store.write("probe_scheduler", runtime)
        self._runtime = runtime
        self._error = runtime["error"]
        if not schedule["enabled"] or _parse_timestamp(runtime["next_run_at"]) > now:
            return
        try:
            latest = self.operations.latest()
        except KeyError:
            latest = None
        if latest and latest["status"] in {"running", "cancelling"}:
            return  # Keep the overdue deadline; retry once the manual job finishes.

        reserved = {**runtime, "next_run_at": _timestamp(now + interval), "error": None}
        self.store.write("probe_scheduler", reserved)
        self._runtime = reserved
        try:
            job = self.operations.start(
                ["discover", "probe"], sorted(set(DISCOVERERS) | set(PC_DISCOVERERS)),
                "all", 10, 8, scheduled_mode=schedule["mode"],
            )
        except RuntimeError:
            # A manual request may win between latest() and start().
            self.store.write("probe_scheduler", runtime)
            self._runtime = runtime
            return
        except Exception:
            self._set_error("scheduled_probe_start_failed")
            reserved["error"] = self._error
            self.store.write("probe_scheduler", reserved)
            return
        reserved.update(last_started_at=_timestamp(now), last_job_id=job["job_id"])
        self.store.write("probe_scheduler", reserved)
        self._error = None
        LOGGER.info("Scheduled probe started job_id=%s mode=%s", job["job_id"], schedule["mode"])
