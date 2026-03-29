import os
import shutil
import sys
import types
import unittest
from pathlib import Path
import uuid

from fastapi import HTTPException


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

from routers import agent as agent_router
from services.agent_runtime.models import AgentMatchRequest
from services.skill_manager import skill_manager
from services.storage import storage


class AgentRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_db_path = storage._db_path
        self.original_skill_loaded = skill_manager._loaded
        self.original_list_skills = skill_manager.list_skills
        self.temp_dir = Path(BACKEND_ROOT) / ".tmp-test-data" / f"agent-router-{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        if storage._db is not None:
            await storage.close()

        storage._db_path = self.temp_dir / "test.db"
        await storage.initialize()

    async def asyncTearDown(self):
        skill_manager._loaded = self.original_skill_loaded
        skill_manager.list_skills = self.original_list_skills
        await storage.close()
        storage._db_path = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_match_intent_rejects_roles_not_allowed_on_agent_surface(self):
        with self.assertRaises(HTTPException) as exc_info:
            await agent_router.match_intent(
                AgentMatchRequest(query="帮我审查采购方案", role_id="copilot")
            )

        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertIn("agent", str(exc_info.exception.detail))

    async def test_match_intent_normalizes_legacy_agent_role_and_returns_role_id_without_skills(self):
        skill_manager._loaded = True
        skill_manager.list_skills = lambda: []

        response = await agent_router.match_intent(
            AgentMatchRequest(query="帮我审查采购方案", role_id="agent")
        )

        self.assertFalse(response.matched)
        self.assertEqual(response.role_id, "executor")
        self.assertEqual(response.surface, "agent")

    async def test_match_intent_respects_agent_preflight_switch(self):
        role = await storage.create_role(
            name="Tool Only Agent",
            icon="🤖",
            allowed_surfaces=["agent"],
            chat_capabilities=[],
            agent_preflight=[],
            agent_allowed_tools=["query_knowledge"],
        )
        skill_manager._loaded = True
        skill_manager.list_skills = lambda: []

        response = await agent_router.match_intent(
            AgentMatchRequest(query="帮我分析采购材料", role_id=role["id"])
        )

        self.assertFalse(response.matched)
        self.assertEqual(response.role_id, role["id"])
        self.assertIn("预匹配", response.message or "")


if __name__ == "__main__":
    unittest.main()
