import os
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
