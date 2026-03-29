import os
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

if "pydantic_ai" not in sys.modules:
    fake_pydantic_ai = types.ModuleType("pydantic_ai")

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

    fake_pydantic_ai.Agent = _FakeAgent
    fake_pydantic_ai.RunContext = object
    sys.modules["pydantic_ai"] = fake_pydantic_ai

if "pydantic_ai.models.openai" not in sys.modules:
    fake_models_pkg = types.ModuleType("pydantic_ai.models")
    fake_models_openai = types.ModuleType("pydantic_ai.models.openai")

    class _FakeOpenAIChatModel:
        def __init__(self, *args, **kwargs):
            pass

    fake_models_openai.OpenAIChatModel = _FakeOpenAIChatModel
    sys.modules["pydantic_ai.models"] = fake_models_pkg
    sys.modules["pydantic_ai.models.openai"] = fake_models_openai

if "pydantic_ai.providers.openai" not in sys.modules:
    fake_providers_pkg = types.ModuleType("pydantic_ai.providers")
    fake_providers_openai = types.ModuleType("pydantic_ai.providers.openai")

    class _FakeOpenAIProvider:
        def __init__(self, *args, **kwargs):
            pass

    fake_providers_openai.OpenAIProvider = _FakeOpenAIProvider
    sys.modules["pydantic_ai.providers"] = fake_providers_pkg
    sys.modules["pydantic_ai.providers.openai"] = fake_providers_openai

from services.agent_runtime import runner as runner_module
from services.agent_runtime.models import AgentExecuteRequest, AgentRuntimeMemory, RolePolicy
from services.storage import storage


class _FakeContextAssembler:
    async def assemble(self, *args, **kwargs):
        raise AssertionError("context assembler should not be called in this test")


class _FakeAgentRunResult:
    def __init__(self):
        self.output = {
            "summary": "已完成",
            "raw_text": "完整输出",
            "used_tools": [],
            "citations": [],
            "artifacts": [],
            "next_actions": [],
        }

    def all_messages_json(self):
        return b'[{"role":"user","content":"previous"},{"role":"assistant","content":"updated"}]'


class _FakeAgentRuntime:
    def __init__(self):
        self.received_message_history = None

    async def run(self, prompt, *, deps=None, message_history=None):
        self.received_message_history = message_history
        return _FakeAgentRunResult()


class _FakeDeps:
    def __init__(self, policy, conversation_id: str, request_params=None):
        self.role_id = "executor"
        self.surface = "agent"
        self.policy = policy
        self.role = {"id": "executor"}
        self.storage = storage
        self.knowledge_service = object()
        self.knowhow_service = object()
        self.skill_manager = object()
        self.context_assembler = _FakeContextAssembler()
        self.api_url = "https://example.invalid/v1"
        self.api_key = "test-key"
        self.model = "gpt-4o"
        self.run_id = "run-new"
        self.request_params = dict(request_params or {})
        self.conversation_id = conversation_id
        self.llm_profile_id = None
        self.skill = None
        self.skill_execution_profile = None
        self.event_adapter = None
        self.memory = AgentRuntimeMemory()


class AgentRunnerMessageHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_root = Path(BACKEND_ROOT) / ".tmp-agent-runner-history-data"
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

    async def test_execute_agent_stream_reuses_and_persists_message_history(self):
        workspace_id = await storage.get_default_workspace_id()
        conversation = await storage.create_conversation(
            workspace_id,
            title="Agent Session",
            surface="agent",
            role_id="executor",
        )
        await storage.create_agent_run(
            run_id="run-prev",
            conversation_id=conversation["id"],
            role_id="executor",
            query="上一轮执行",
            params={"import_id": "imp-1"},
            message_history='[{"role":"user","content":"previous"}]',
            status="completed",
        )

        request = AgentExecuteRequest(
            role_id="executor",
            query="",
            params={"extra_note": "need retry"},
            conversation_id=conversation["id"],
            run_id="run-new",
            continue_from_run_id="run-prev",
            continue_mode="retry",
            continue_notes="请结合新增参数继续完成任务",
            api_url="https://example.invalid/v1",
            api_key="test-key",
            model="gpt-4o",
        )
        fake_agent = _FakeAgentRuntime()
        fake_policy = RolePolicy(
            role_id="executor",
            allowed=True,
            capabilities=[],
            allowed_surfaces=["agent"],
            allowed_tools=[],
            enable_rag=False,
            enable_skill_matching=False,
            instructions="test",
            display_name="执行助手",
        )
        async def _fake_build_agent_deps(_request):
            return _FakeDeps(fake_policy, conversation["id"], _request.params)

        events = []
        with patch.object(runner_module, "build_agent_deps", _fake_build_agent_deps), patch.object(
            runner_module,
            "create_runtime_agent",
            lambda deps: fake_agent,
        ):
            async for event in runner_module.execute_agent_stream(request):
                events.append(event)

        self.assertTrue(events)
        self.assertEqual(
            fake_agent.received_message_history,
            [{"role": "user", "content": "previous"}],
        )

        run = await storage.get_agent_run("run-new")
        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["continueFromRunId"], "run-prev")
        self.assertEqual(run["continueMode"], "retry")
        self.assertEqual(run["query"], "上一轮执行")
        self.assertEqual(run["params"]["import_id"], "imp-1")
        self.assertEqual(run["params"]["extra_note"], "need retry")
        self.assertEqual(run["messageHistoryCount"], 2)
        self.assertEqual(run["finalResult"]["raw_text"], "完整输出")


if __name__ == "__main__":
    unittest.main()
