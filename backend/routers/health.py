"""
Health and runtime diagnostics endpoints.

Legacy `/api/health` stays compatible, while `/api/health/live`,
`/api/health/ready`, and `/api/health/runtime` provide Phase 2 production
deployment signals.
"""

from __future__ import annotations

import os
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from services.runtime_controls import (
    attachment_parse_controller,
    conversation_generation_registry,
    llm_concurrency_controller,
    runtime_limits,
)
from services.observability import get_application_runtime_snapshot, runtime_metrics_ttl_ms
from services.runtime_paths import APP_HOME, DATA_DIR, DB_PATH, PROJECT_ROOT, VECTORS_DIR
from services.storage import storage

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serve_frontend_enabled() -> bool:
    return os.getenv("MEETING_ASSISTANT_SERVE_FRONTEND", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_frontend_dist() -> Path:
    configured = os.getenv("MEETING_ASSISTANT_FRONTEND_DIST", "").strip()
    if not configured:
        return (PROJECT_ROOT / "dist").resolve()
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def _path_check(path: Path) -> dict[str, object]:
    exists = path.exists()
    is_dir = path.is_dir() if exists else False
    writable = os.access(path, os.W_OK) if exists else False
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "writable": writable,
    }


async def _storage_check() -> dict[str, object]:
    initialized = storage._db is not None  # noqa: SLF001 - intentional runtime diagnostics
    if not initialized:
        return {
            "ok": False,
            "initialized": False,
            "detail": "storage_not_initialized",
        }

    try:
        row = await storage._fetchone("SELECT 1 AS ok")  # noqa: SLF001 - lightweight readiness query
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "initialized": True,
            "detail": str(exc),
        }

    return {
        "ok": bool(row and row.get("ok") == 1),
        "initialized": True,
        "db_path": str(DB_PATH),
    }


@router.get("/health")
async def health_check() -> dict[str, object]:
    """Legacy health endpoint kept for backward compatibility."""
    return {
        "status": "ok",
        "service": "meeting-assistant-backend",
        "timestamp": _utc_now(),
        "checks": {
            "live": "/api/health/live",
            "ready": "/api/health/ready",
            "runtime": "/api/health/runtime",
        },
    }


@router.get("/health/live")
async def live_check() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "meeting-assistant-backend",
        "timestamp": _utc_now(),
    }


@router.get("/health/ready")
async def ready_check() -> dict[str, object]:
    frontend_dist = _resolve_frontend_dist()
    storage_check = await _storage_check()
    app_home_check = _path_check(APP_HOME)
    data_dir_check = _path_check(DATA_DIR)
    log_dir = Path(os.getenv("MEETING_ASSISTANT_LOG_DIR", str(APP_HOME / "logs"))).expanduser()
    if not log_dir.is_absolute():
        log_dir = (PROJECT_ROOT / log_dir).resolve()
    else:
        log_dir = log_dir.resolve()
    log_dir_check = _path_check(log_dir)
    frontend_check = {
        "enabled": _serve_frontend_enabled(),
        "dist_path": str(frontend_dist),
        "index_exists": (frontend_dist / "index.html").exists(),
    }

    checks = {
        "storage": storage_check,
        "app_home": app_home_check,
        "data_dir": data_dir_check,
        "log_dir": log_dir_check,
        "frontend": frontend_check,
    }

    ready = (
        storage_check["ok"]
        and app_home_check["exists"]
        and app_home_check["is_dir"]
        and app_home_check["writable"]
        and data_dir_check["exists"]
        and data_dir_check["is_dir"]
        and data_dir_check["writable"]
        and log_dir_check["exists"]
        and log_dir_check["is_dir"]
        and log_dir_check["writable"]
        and (not frontend_check["enabled"] or frontend_check["index_exists"])
    )

    payload = {
        "status": "ready" if ready else "not_ready",
        "service": "meeting-assistant-backend",
        "timestamp": _utc_now(),
        "checks": checks,
    }
    if not ready:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/health/runtime")
async def runtime_check() -> dict[str, object]:
    frontend_dist = _resolve_frontend_dist()
    log_dir = Path(os.getenv("MEETING_ASSISTANT_LOG_DIR", str(APP_HOME / "logs"))).expanduser()
    if not log_dir.is_absolute():
        log_dir = (PROJECT_ROOT / log_dir).resolve()
    else:
        log_dir = log_dir.resolve()

    llm_snapshot = (
        await llm_concurrency_controller.snapshot_async()
        if hasattr(llm_concurrency_controller, "snapshot_async")
        else llm_concurrency_controller.snapshot()
    )
    conversation_snapshot = (
        await conversation_generation_registry.snapshot_async()
        if hasattr(conversation_generation_registry, "snapshot_async")
        else conversation_generation_registry.snapshot()
    )
    attachment_snapshot = (
        await attachment_parse_controller.snapshot_async()
        if hasattr(attachment_parse_controller, "snapshot_async")
        else attachment_parse_controller.snapshot()
    )

    return {
        "status": "ok",
        "service": "meeting-assistant-backend",
        "timestamp": _utc_now(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "deployment": {
            "host": os.getenv("MEETING_ASSISTANT_HOST", "0.0.0.0"),
            "port": os.getenv("MEETING_ASSISTANT_PORT", "5173"),
            "serve_frontend": _serve_frontend_enabled(),
            "frontend_dist": str(frontend_dist),
            "log_dir": str(log_dir),
        },
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "app_home": str(APP_HOME),
            "data_dir": str(DATA_DIR),
            "db_path": str(DB_PATH),
            "vectors_dir": str(VECTORS_DIR),
        },
        "runtime_limits": asdict(runtime_limits),
        "runtime_usage": {
            "llm": llm_snapshot,
            "conversation_generation": conversation_snapshot,
            "attachment_parse": attachment_snapshot,
            "application": await get_application_runtime_snapshot(storage_service=storage),
        },
        "runtime_metrics_ttl_ms": runtime_metrics_ttl_ms(),
    }
