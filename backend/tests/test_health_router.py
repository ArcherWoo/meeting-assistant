import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import health as health_router


class HealthRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_legacy_endpoint_stays_compatible(self):
        result = await health_router.health_check()
        self.assertEqual(result["status"], "ok")
        self.assertIn("ready", result["checks"])

    async def test_ready_check_returns_ready_when_dependencies_are_available(self):
        with patch.object(health_router, "_storage_check", AsyncMock(return_value={
            "ok": True,
            "initialized": True,
            "db_path": "test.db",
        })):
            with patch.object(health_router, "_serve_frontend_enabled", return_value=False):
                with patch.object(health_router, "_path_check", return_value={
                    "path": "x",
                    "exists": True,
                    "is_dir": True,
                    "writable": True,
                }):
                    result = await health_router.ready_check()

        self.assertEqual(result["status"], "ready")

    async def test_ready_check_returns_503_when_storage_is_not_ready(self):
        with patch.object(health_router, "_storage_check", AsyncMock(return_value={
            "ok": False,
            "initialized": False,
            "detail": "storage_not_initialized",
        })):
            with patch.object(health_router, "_serve_frontend_enabled", return_value=False):
                with patch.object(health_router, "_path_check", return_value={
                    "path": "x",
                    "exists": True,
                    "is_dir": True,
                    "writable": True,
                }):
                    with self.assertRaises(HTTPException) as context:
                        await health_router.ready_check()

        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail["status"], "not_ready")

    async def test_runtime_check_includes_runtime_usage_snapshot(self):
        with patch.object(health_router, "_resolve_frontend_dist", return_value=Path("dist")):
            result = await health_router.runtime_check()

        self.assertEqual(result["status"], "ok")
        self.assertIn("runtime_metrics_ttl_ms", result)
        self.assertIn("runtime_limits", result)
        self.assertIn("runtime_usage", result)
        self.assertIn("llm", result["runtime_usage"])
        self.assertIn("application", result["runtime_usage"])
