from __future__ import annotations

import json
import logging
import os
import socket
import time
from threading import Lock
from typing import Any
from uuid import uuid4

import aiosqlite


def new_request_id(prefix: str) -> str:
    normalized = (prefix or "req").strip().lower() or "req"
    return f"{normalized}-{uuid4().hex[:12]}"


def log_structured(
    logger: logging.Logger,
    level: str,
    event: str,
    **fields: Any,
) -> None:
    payload = {"event": event, **fields}
    message = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    log_method = getattr(logger, level, logger.info)
    log_method(message)


def runtime_metrics_ttl_ms() -> int:
    raw = os.getenv("MEETING_ASSISTANT_RUNTIME_METRICS_TTL_MS", "").strip()
    try:
        return max(5000, int(raw)) if raw else 30000
    except ValueError:
        return 30000


def runtime_instance_info() -> dict[str, str]:
    port = str(os.getenv("MEETING_ASSISTANT_PORT", "5173") or "5173")
    instance_index = str(os.getenv("MEETING_ASSISTANT_INSTANCE_INDEX", "0") or "0")
    instance_mode = str(os.getenv("MEETING_ASSISTANT_INSTANCE_MODE", "single-process") or "single-process")
    host = socket.gethostname()
    instance_id = str(
        os.getenv("MEETING_ASSISTANT_INSTANCE_ID", f"{host}:{port}:{instance_index}:{os.getpid()}")
    ).strip()
    return {
        "instance_id": instance_id,
        "instance_index": instance_index,
        "instance_mode": instance_mode,
        "host": host,
        "port": port,
        "pid": str(os.getpid()),
    }


class RuntimeMetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._last_published_at = 0.0
        self._counters: dict[str, int] = {
            "chat_started_total": 0,
            "chat_completed_total": 0,
            "chat_failed_total": 0,
            "chat_rejected_total": 0,
            "chat_stream_started_total": 0,
            "chat_non_stream_started_total": 0,
            "agent_started_total": 0,
            "agent_completed_total": 0,
            "agent_failed_total": 0,
            "agent_cancelled_total": 0,
            "llm_busy_total": 0,
            "conversation_busy_total": 0,
        }
        self._inflight: dict[str, int] = {
            "chat": 0,
            "agent": 0,
        }
        self._latency_sums: dict[str, int] = {
            "chat_llm_first_token_ms": 0,
            "chat_llm_total_ms": 0,
            "chat_end_to_end_ms": 0,
            "chat_retrieval_ms": 0,
        }
        self._latency_counts: dict[str, int] = {
            "chat_llm_first_token_ms": 0,
            "chat_llm_total_ms": 0,
            "chat_end_to_end_ms": 0,
            "chat_retrieval_ms": 0,
        }

    def record_chat_started(self, *, stream: bool) -> None:
        with self._lock:
            self._counters["chat_started_total"] += 1
            key = "chat_stream_started_total" if stream else "chat_non_stream_started_total"
            self._counters[key] += 1
            self._inflight["chat"] += 1

    def record_chat_finished(
        self,
        *,
        status: str,
        timings: dict[str, int] | None = None,
    ) -> None:
        with self._lock:
            self._inflight["chat"] = max(0, self._inflight["chat"] - 1)
            if status == "completed":
                self._counters["chat_completed_total"] += 1
            elif status != "rejected":
                self._counters["chat_failed_total"] += 1

            self._record_chat_timings_locked(timings or {})

    def record_chat_rejection(self, *, reason: str) -> None:
        with self._lock:
            self._counters["chat_rejected_total"] += 1
            if reason == "llm_busy":
                self._counters["llm_busy_total"] += 1
            elif reason == "conversation_busy":
                self._counters["conversation_busy_total"] += 1

    def record_agent_started(self) -> None:
        with self._lock:
            self._counters["agent_started_total"] += 1
            self._inflight["agent"] += 1

    def record_agent_finished(self, *, status: str) -> None:
        with self._lock:
            self._inflight["agent"] = max(0, self._inflight["agent"] - 1)
            if status == "completed":
                self._counters["agent_completed_total"] += 1
            elif status == "cancelled":
                self._counters["agent_cancelled_total"] += 1
            else:
                self._counters["agent_failed_total"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            inflight = dict(self._inflight)
            latency_sums = dict(self._latency_sums)
            latency_counts = dict(self._latency_counts)
            averages = _compute_latency_averages(latency_sums, latency_counts)
            return {
                "scope": "worker",
                "instance": runtime_instance_info(),
                "counters": counters,
                "inflight": inflight,
                "averages_ms": averages,
                "latency_sums_ms": latency_sums,
                "latency_counts": latency_counts,
            }

    def _record_chat_timings_locked(self, timings: dict[str, int]) -> None:
        for key in (
            "llm_first_token_ms",
            "llm_total_ms",
            "end_to_end_ms",
            "retrieval_ms",
        ):
            value = timings.get(key)
            if value is None:
                continue
            metric_key = f"chat_{key}"
            if metric_key not in self._latency_sums:
                continue
            self._latency_sums[metric_key] += int(value)
            self._latency_counts[metric_key] += 1

    def should_publish(self, *, min_interval_ms: int = 500) -> bool:
        now = time.monotonic()
        with self._lock:
            if (now - self._last_published_at) * 1000 < max(min_interval_ms, 0):
                return False
            self._last_published_at = now
            return True


def _compute_latency_averages(
    latency_sums: dict[str, int],
    latency_counts: dict[str, int],
) -> dict[str, float]:
    averages: dict[str, float] = {}
    for key, total in latency_sums.items():
        count = latency_counts.get(key, 0)
        averages[key] = round(total / count, 2) if count else 0.0
    return averages


async def publish_runtime_metrics(*, force: bool = False, storage_service=None) -> dict[str, Any]:
    if not force and not runtime_metrics.should_publish():
        return runtime_metrics.snapshot()

    if storage_service is None:
        from services.storage import storage as storage_service

    snapshot = runtime_metrics.snapshot()
    try:
        await storage_service.upsert_runtime_application_metrics(
            snapshot["instance"]["instance_id"],
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        )
        await storage_service.cleanup_stale_runtime_application_metrics(
            fresh_within_ms=runtime_metrics_ttl_ms()
        )
    except (RuntimeError, aiosqlite.Error):
        return snapshot
    return snapshot


async def get_application_runtime_snapshot(*, storage_service=None) -> dict[str, Any]:
    current_snapshot = await publish_runtime_metrics(force=True, storage_service=storage_service)

    if storage_service is None:
        from services.storage import storage as storage_service

    try:
        rows = await storage_service.list_runtime_application_metrics(
            fresh_within_ms=runtime_metrics_ttl_ms()
        )
    except (RuntimeError, aiosqlite.Error):
        return current_snapshot
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        raw_payload = str(row.get("payload_json") or "").strip()
        if not raw_payload:
            continue
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            snapshots.append(parsed)

    if not snapshots:
        return current_snapshot

    counters: dict[str, int] = {}
    inflight: dict[str, int] = {}
    latency_sums: dict[str, int] = {}
    latency_counts: dict[str, int] = {}
    instances: list[dict[str, Any]] = []

    for snapshot in snapshots:
        instance = snapshot.get("instance")
        if isinstance(instance, dict):
            instances.append(instance)

        for key, value in (snapshot.get("counters") or {}).items():
            counters[key] = counters.get(key, 0) + int(value or 0)

        for key, value in (snapshot.get("inflight") or {}).items():
            inflight[key] = inflight.get(key, 0) + int(value or 0)

        for key, value in (snapshot.get("latency_sums_ms") or {}).items():
            latency_sums[key] = latency_sums.get(key, 0) + int(value or 0)

        for key, value in (snapshot.get("latency_counts") or {}).items():
            latency_counts[key] = latency_counts.get(key, 0) + int(value or 0)

    return {
        "scope": "cluster",
        "instance_count": len(instances),
        "instances": instances,
        "counters": counters,
        "inflight": inflight,
        "averages_ms": _compute_latency_averages(latency_sums, latency_counts),
        "latency_sums_ms": latency_sums,
        "latency_counts": latency_counts,
    }


runtime_metrics = RuntimeMetricsRegistry()
