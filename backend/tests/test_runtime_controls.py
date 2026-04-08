import os
import shutil
import sys
import asyncio
import unittest
import uuid
from pathlib import Path


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.runtime_controls import (
    AttachmentParseBusyError,
    AttachmentParseController,
    ConversationGenerationRegistry,
    LLMConcurrencyBusyError,
    LLMConcurrencyController,
)
from services.storage import StorageService, storage


class RuntimeControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_registry_blocks_same_conversation_until_release(self):
        registry = ConversationGenerationRegistry()

        self.assertTrue(await registry.try_acquire("conv-1"))
        self.assertFalse(await registry.try_acquire("conv-1"))

        await registry.release("conv-1")

        self.assertTrue(await registry.try_acquire("conv-1"))

    async def test_llm_controller_enforces_per_user_limit(self):
        controller = LLMConcurrencyController(
            global_limit=2,
            stream_limit=1,
            lightweight_limit=2,
            per_user_limit=1,
            acquire_timeout_ms=10,
        )

        async with controller.acquire(kind="lightweight", user_id="alice"):
            with self.assertRaises(LLMConcurrencyBusyError):
                async with controller.acquire(kind="lightweight", user_id="alice"):
                    self.fail("should not acquire a second slot for the same user")

        async with controller.acquire(kind="lightweight", user_id="alice"):
            pass

    async def test_attachment_controller_keeps_fast_lane_available_when_ingest_is_busy(self):
        controller = AttachmentParseController(
            total_limit=2,
            ingest_limit=1,
            fast_timeout_ms=10,
            ingest_timeout_ms=10,
        )

        async with controller.acquire(mode="ingest"):
            async with controller.acquire(mode="fast"):
                pass

            with self.assertRaises(AttachmentParseBusyError):
                async with controller.acquire(mode="ingest"):
                    self.fail("second ingest task should be blocked by ingest quota")

    async def test_runtime_snapshots_reflect_current_usage(self):
        llm_controller = LLMConcurrencyController(
            global_limit=3,
            stream_limit=2,
            lightweight_limit=2,
            per_user_limit=2,
            acquire_timeout_ms=10,
        )
        registry = ConversationGenerationRegistry()
        attachment_controller = AttachmentParseController(
            total_limit=3,
            ingest_limit=1,
            fast_timeout_ms=10,
            ingest_timeout_ms=10,
        )

        async with llm_controller.acquire(kind="stream", user_id="alice"):
            self.assertEqual(llm_controller.snapshot()["global_in_use"], 1)
            self.assertEqual(llm_controller.snapshot()["stream_in_use"], 1)
            self.assertEqual(llm_controller.snapshot()["user_counts"], {"alice": 1})

        self.assertEqual(llm_controller.snapshot()["global_in_use"], 0)

        self.assertTrue(await registry.try_acquire("conv-1"))
        self.assertEqual(registry.snapshot()["active_count"], 1)
        await registry.release("conv-1")
        self.assertEqual(registry.snapshot()["active_count"], 0)

        async with attachment_controller.acquire(mode="ingest"):
            snapshot = attachment_controller.snapshot()
            self.assertEqual(snapshot["total_in_use"], 1)
            self.assertEqual(snapshot["ingest_in_use"], 1)


class SQLiteRuntimeCoordinationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_db_path = storage._db_path
        self.temp_dir = Path(BACKEND_ROOT) / ".tmp-test-data" / f"runtime-coordination-{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        if storage._db is not None:
            await storage.close()

        storage._db_path = self.temp_dir / "test.db"
        await storage.initialize()

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_sqlite_conversation_lock_blocks_across_controller_instances(self):
        registry1 = ConversationGenerationRegistry(
            backend="sqlite",
            storage_service=storage,
            lock_ttl_ms=60000,
        )
        registry2 = ConversationGenerationRegistry(
            backend="sqlite",
            storage_service=storage,
            lock_ttl_ms=60000,
        )

        self.assertTrue(await registry1.try_acquire("conv-1"))
        self.assertFalse(await registry2.try_acquire("conv-1"))

        await registry1.release("conv-1")

        self.assertTrue(await registry2.try_acquire("conv-1"))

    async def test_sqlite_llm_limits_coordinate_across_instances(self):
        controller1 = LLMConcurrencyController(
            global_limit=2,
            stream_limit=1,
            lightweight_limit=2,
            per_user_limit=1,
            acquire_timeout_ms=10,
            backend="sqlite",
            storage_service=storage,
            lease_ttl_ms=60000,
        )
        controller2 = LLMConcurrencyController(
            global_limit=2,
            stream_limit=1,
            lightweight_limit=2,
            per_user_limit=1,
            acquire_timeout_ms=10,
            backend="sqlite",
            storage_service=storage,
            lease_ttl_ms=60000,
        )

        async with controller1.acquire(kind="stream", user_id="alice"):
            with self.assertRaises(LLMConcurrencyBusyError):
                async with controller2.acquire(kind="stream", user_id="bob"):
                    self.fail("second stream slot should be blocked across instances")

            with self.assertRaises(LLMConcurrencyBusyError):
                async with controller2.acquire(kind="lightweight", user_id="alice"):
                    self.fail("same user should not get a second slot across instances")

        async with controller2.acquire(kind="stream", user_id="bob"):
            snapshot = await controller2.snapshot_async()
            self.assertEqual(snapshot["stream_in_use"], 1)
            self.assertEqual(snapshot["global_in_use"], 1)

    async def test_sqlite_attachment_limits_coordinate_across_instances(self):
        controller1 = AttachmentParseController(
            total_limit=2,
            ingest_limit=1,
            fast_timeout_ms=10,
            ingest_timeout_ms=10,
            backend="sqlite",
            storage_service=storage,
            lease_ttl_ms=60000,
        )
        controller2 = AttachmentParseController(
            total_limit=2,
            ingest_limit=1,
            fast_timeout_ms=10,
            ingest_timeout_ms=10,
            backend="sqlite",
            storage_service=storage,
            lease_ttl_ms=60000,
        )

        async with controller1.acquire(mode="ingest"):
            async with controller2.acquire(mode="fast"):
                snapshot = await controller2.snapshot_async()
                self.assertEqual(snapshot["total_in_use"], 2)
                self.assertEqual(snapshot["ingest_in_use"], 1)

            with self.assertRaises(AttachmentParseBusyError):
                async with controller2.acquire(mode="ingest"):
                    self.fail("second ingest slot should be blocked across instances")

    async def test_sqlite_llm_acquire_is_safe_under_same_instance_concurrency(self):
        controller = LLMConcurrencyController(
            global_limit=4,
            stream_limit=4,
            lightweight_limit=4,
            per_user_limit=4,
            acquire_timeout_ms=50,
            backend="sqlite",
            storage_service=storage,
            lease_ttl_ms=60000,
        )

        async def worker(index: int) -> None:
            async with controller.acquire(kind="lightweight", user_id=f"user-{index}"):
                await asyncio.sleep(0.01)

        await asyncio.gather(*(worker(index) for index in range(4)))
        snapshot = await controller.snapshot_async()
        self.assertEqual(snapshot["global_in_use"], 0)

    async def test_storage_initialize_is_safe_under_multi_instance_startup(self):
        db_path = self.temp_dir / "cluster-startup.db"
        instances = [StorageService(db_path=db_path) for _ in range(4)]

        try:
            await asyncio.gather(*(instance.initialize() for instance in instances))

            inspector = instances[0]
            admin_row = await inspector.get_user_by_username("admin")
            self.assertIsNotNone(admin_row)

            role_rows = await inspector._fetchall(
                "SELECT id FROM roles WHERE id IN ('copilot', 'builder', 'executor')"
            )
            role_ids = {row["id"] for row in role_rows}
            self.assertEqual(role_ids, {"copilot", "builder", "executor"})

            workspace_row = await inspector._fetchone("SELECT COUNT(*) AS total FROM workspaces")
            self.assertEqual(int(workspace_row["total"]), 1)
        finally:
            await asyncio.gather(*(instance.close() for instance in instances), return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
