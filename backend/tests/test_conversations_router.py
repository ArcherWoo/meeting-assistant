import os
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import conversations as conversations_router
from services.storage import storage


class ConversationsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory()
        self.original_db_path = storage._db_path

        if storage._db is not None:
            await storage.close()

        storage._db_path = Path(self.temp_dir.name) / "test.db"
        await storage.initialize()

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        self.temp_dir.cleanup()

    async def test_chat_state_roundtrip_uses_database_conversations_and_messages(self):
        created = await conversations_router.create_conversation(
            conversations_router.ConversationCreateRequest(role_id="copilot")
        )
        conversation = created["conversation"]

        await conversations_router.create_message(
            conversation["id"],
            conversations_router.MessageCreateRequest(
                role="user",
                content="请帮我总结今天的会议",
                metadata={"context": {"summary": "测试"}},
            ),
        )

        state = await conversations_router.get_chat_state()
        self.assertEqual(len(state["conversations"]), 1)
        self.assertEqual(state["conversations"][0]["roleId"], "copilot")
        self.assertEqual(state["conversations"][0]["surface"], "chat")
        self.assertEqual(
            state["messages_by_conversation"][conversation["id"]][0]["content"],
            "请帮我总结今天的会议",
        )
        self.assertEqual(
            state["messages_by_conversation"][conversation["id"]][0]["metadata"]["context"]["summary"],
            "测试",
        )

    async def test_update_conversation_tracks_title_customization(self):
        created = await conversations_router.create_conversation(
            conversations_router.ConversationCreateRequest(role_id="copilot")
        )
        conversation = created["conversation"]

        updated = await conversations_router.update_conversation(
            conversation["id"],
            conversations_router.ConversationUpdateRequest(
                title="采购预审讨论",
                is_title_customized=True,
            ),
        )

        self.assertEqual(updated["conversation"]["title"], "采购预审讨论")
        self.assertTrue(updated["conversation"]["isTitleCustomized"])

    async def test_create_agent_surface_conversation_roundtrip(self):
        created = await conversations_router.create_conversation(
            conversations_router.ConversationCreateRequest(role_id="executor", surface="agent")
        )
        conversation = created["conversation"]

        self.assertEqual(conversation["roleId"], "executor")
        self.assertEqual(conversation["surface"], "agent")


    async def test_get_chat_state_injects_compensation_message_for_unwritten_agent_run(self):
        """completed agent_run 尚未写回 messages 表时，get_chat_state 应补出一条 assistant 消息。"""
        created = await conversations_router.create_conversation(
            conversations_router.ConversationCreateRequest(role_id="executor", surface="agent")
        )
        conversation = created["conversation"]

        # 创建一个 completed agent_run，不写回 messages 表
        from services.storage import gen_id, utc_now_iso
        run_id = gen_id()
        import json
        final_result = {
            "summary": "预审完成",
            "raw_text": "采购预审完成，共发现 2 个注意事项。",
            "used_tools": [],
            "citations": [],
            "artifacts": [],
            "next_actions": [],
        }
        await storage.create_agent_run(
            run_id=run_id,
            role_id="executor",
            query="采购会前材料预审",
            conversation_id=conversation["id"],
            status="completed",
        )
        await storage.update_agent_run(
            run_id,
            status="completed",
            final_result=final_result,
        )

        state = await conversations_router.get_chat_state()
        msgs = state["messages_by_conversation"][conversation["id"]]
        self.assertEqual(len(msgs), 1)
        comp = msgs[0]
        self.assertEqual(comp["role"], "assistant")
        self.assertTrue(comp["id"].startswith("compensated-"))
        self.assertEqual(comp["metadata"]["agentResult"]["runId"], run_id)
        self.assertIn("采购预审完成", comp["content"])

    async def test_get_chat_state_skips_compensation_when_already_written_back(self):
        """如果 messages 已包含该 runId，不应再注入补偿消息。"""
        created = await conversations_router.create_conversation(
            conversations_router.ConversationCreateRequest(role_id="executor", surface="agent")
        )
        conversation = created["conversation"]

        from services.storage import gen_id
        run_id = gen_id()
        final_result = {
            "summary": "预审完成",
            "raw_text": "采购预审完成。",
            "used_tools": [],
            "citations": [],
            "artifacts": [],
            "next_actions": [],
        }
        await storage.create_agent_run(
            run_id=run_id,
            role_id="executor",
            query="采购会前材料预审",
            conversation_id=conversation["id"],
            status="completed",
        )
        await storage.update_agent_run(run_id, status="completed", final_result=final_result)

        # 写回一条已包含 runId 的消息
        import json
        await conversations_router.create_message(
            conversation["id"],
            conversations_router.MessageCreateRequest(
                role="assistant",
                content="采购预审完成。",
                metadata={"agentResult": {"runId": run_id, "summary": "预审完成"}},
            ),
        )

        state = await conversations_router.get_chat_state()
        msgs = state["messages_by_conversation"][conversation["id"]]
        # 只有真实写回的那一条，补偿消息不应被注入
        self.assertEqual(len(msgs), 1)
        self.assertFalse(msgs[0]["id"].startswith("compensated-"))

    async def test_initialize_migrates_legacy_conversations_before_role_index_creation(self):
        await storage.close()
        storage._db_path.unlink(missing_ok=True)

        legacy_db = sqlite3.connect(storage._db_path)
        legacy_db.executescript(
            """
            CREATE TABLE workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                title TEXT DEFAULT 'New Chat',
                mode TEXT NOT NULL DEFAULT 'copilot',
                is_pinned INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        legacy_db.execute(
            "INSERT INTO workspaces (id, name) VALUES (?, ?)",
            ("ws-1", "Default Workspace"),
        )
        legacy_db.execute(
            "INSERT INTO conversations (id, workspace_id, title, mode) VALUES (?, ?, ?, ?)",
            ("conv-1", "ws-1", "Legacy Conversation", "agent"),
        )
        legacy_db.commit()
        legacy_db.close()

        await storage.initialize()

        conversation = await storage.get_conversation("conv-1")
        self.assertIsNotNone(conversation)
        self.assertEqual(conversation["roleId"], "executor")
        self.assertEqual(conversation["surface"], "agent")
        self.assertFalse(conversation["isTitleCustomized"])


if __name__ == "__main__":
    unittest.main()
