import asyncio
import os
import shutil
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.agent_runtime.event_adapter import AgentEventAdapter
from services.agent_runtime.history import load_agent_run, load_latest_message_history
from services.agent_runtime.models import AgentFinalResult, RolePolicy
from services.storage import storage


class AgentHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_root = Path(BACKEND_ROOT) / ".tmp-agent-history-data"
        self.original_db_path = storage._db_path

        if storage._db is not None:
            await storage.close()

        if self.temp_root.exists():
            shutil.rmtree(self.temp_root, ignore_errors=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        storage._db_path = self.temp_root / "test.db"
        await storage.initialize()

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        shutil.rmtree(self.temp_root, ignore_errors=True)

    async def test_event_adapter_persists_agent_run_and_dynamic_steps(self):
        queue: asyncio.Queue[dict] = asyncio.Queue()
        adapter = AgentEventAdapter(
            queue=queue,
            run_id="run-1",
            role_id="executor",
            query="审查采购方案",
            policy=RolePolicy(
                role_id="executor",
                allowed=True,
                capabilities=["rag", "skills"],
                allowed_tools=["get_skill_definition", "extract_file_text"],
                enable_rag=True,
                enable_skill_matching=True,
                instructions="test",
                display_name="执行助手",
            ),
            skill_id="procurement-review",
            skill_name="采购预审",
            conversation_id=None,
            request_params={"import_id": "imp-1"},
            model="gpt-4o",
            llm_profile_id="profile-1",
        )

        await adapter.emit_execution_start()
        step_index = await adapter.on_tool_start("extract_file_text")
        await adapter.on_tool_complete(step_index, "extract_file_text", "已提取文件文本")
        await adapter.emit_complete(
            AgentFinalResult(
                summary="完成",
                raw_text="完整结果",
                used_tools=["extract_file_text"],
            )
        )

        run = await storage.get_agent_run("run-1")
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["roleId"], "executor")
        self.assertEqual(run["skillId"], "procurement-review")
        self.assertEqual(run["finalResult"]["raw_text"], "完整结果")
        self.assertEqual(run["messageHistoryCount"], 0)
        self.assertEqual(len(run["steps"]), 2)
        self.assertEqual(run["steps"][0]["step_key"], "extract_file_text")
        self.assertEqual(run["steps"][0]["status"], "completed")
        self.assertEqual(run["steps"][1]["step_key"], "finalize")
        self.assertEqual(run["steps"][1]["status"], "completed")

    async def test_load_agent_run_returns_persisted_run(self):
        await storage.create_agent_run(
            run_id="run-2",
            conversation_id=None,
            role_id="executor",
            query="生成审查结论",
            params={"file": "采购方案.pdf"},
            skill_id="procurement-review",
            skill_name="采购预审",
            model="gpt-4o",
            message_history='[{"role":"user"},{"role":"assistant"}]',
            status="running",
            started_at="2026-03-28T10:00:00+00:00",
        )
        await storage.upsert_agent_run_step(
            run_id="run-2",
            step_index=1,
            step_key="get_skill_definition",
            description="读取任务定义",
            status="completed",
            result="已读取",
        )
        await storage.update_agent_run(
            "run-2",
            status="completed",
            completed_at="2026-03-28T10:00:03+00:00",
            final_result={
                "summary": "审查完成",
                "raw_text": "完整输出",
                "used_tools": ["get_skill_definition"],
                "citations": [],
                "artifacts": [],
                "next_actions": [],
            },
        )

        run = await load_agent_run("run-2")
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run["runId"], "run-2")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["messageHistoryCount"], 2)
        self.assertEqual(run["finalResult"]["summary"], "审查完成")
        self.assertEqual(len(run["steps"]), 1)

    async def test_event_adapter_persists_cancelled_status(self):
        queue: asyncio.Queue[dict] = asyncio.Queue()
        adapter = AgentEventAdapter(
            queue=queue,
            run_id="run-cancel",
            role_id="executor",
            query="取消运行",
            policy=RolePolicy(
                role_id="executor",
                allowed=True,
                capabilities=[],
                allowed_tools=[],
                enable_rag=False,
                enable_skill_matching=False,
                instructions="test",
                display_name="执行助手",
            ),
            conversation_id=None,
            request_params={},
            model="gpt-4o",
            llm_profile_id="profile-1",
        )

        await adapter.emit_execution_start()
        await adapter.on_tool_start("query_knowledge")
        await adapter.emit_cancelled("用户已取消")

        run = await storage.get_agent_run("run-cancel")
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run["status"], "cancelled")
        self.assertEqual(run["error"], "用户已取消")
        self.assertEqual(run["steps"][0]["step_key"], "query_knowledge")
        self.assertEqual(run["steps"][0]["status"], "cancelled")
        self.assertEqual(run["steps"][1]["step_key"], "cancel")
        self.assertEqual(run["steps"][1]["status"], "completed")

    async def test_event_adapter_persists_non_tool_stage_steps(self):
        queue: asyncio.Queue[dict] = asyncio.Queue()
        adapter = AgentEventAdapter(
            queue=queue,
            run_id="run-stage",
            role_id="executor",
            query="规划检索",
            policy=RolePolicy(
                role_id="executor",
                allowed=True,
                capabilities=["rag"],
                allowed_tools=["query_knowledge"],
                enable_rag=True,
                enable_skill_matching=False,
                instructions="test",
                display_name="执行助手",
            ),
            conversation_id=None,
            request_params={},
            model="gpt-4o",
            llm_profile_id="profile-1",
        )

        await adapter.emit_execution_start()
        step_index = await adapter.on_stage_start("planner", description="规划检索策略")
        await adapter.on_stage_complete(step_index, "planner", "planner: knowhow(供应商资质)")

        run = await storage.get_agent_run("run-stage")
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run["steps"][0]["step_key"], "planner")
        self.assertEqual(run["steps"][0]["status"], "completed")
        self.assertFalse(run["steps"][0]["toolName"])

    async def test_load_latest_message_history_filters_by_conversation_and_role(self):
        workspace_id = await storage.get_default_workspace_id()
        conversation = await storage.create_conversation(
            workspace_id,
            title="Agent Session",
            surface="agent",
            role_id="executor",
        )
        await storage.create_agent_run(
            run_id="run-old",
            conversation_id=conversation["id"],
            role_id="executor",
            query="第一次执行",
            message_history='[{"role":"user","content":"first"}]',
            status="completed",
        )
        await storage.create_agent_run(
            run_id="run-other-role",
            conversation_id=conversation["id"],
            role_id="builder",
            query="其他角色",
            message_history='[{"role":"user","content":"builder"}]',
            status="completed",
        )
        await storage.create_agent_run(
            run_id="run-new",
            conversation_id=conversation["id"],
            role_id="executor",
            query="第二次执行",
            status="pending",
        )

        history = await load_latest_message_history(
            conversation["id"],
            "executor",
            exclude_run_id="run-new",
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "first")


if __name__ == "__main__":
    unittest.main()
