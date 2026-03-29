import os
import sys
import types
import unittest
from types import SimpleNamespace


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

if "pydantic_ai" not in sys.modules:
    fake_pydantic_ai = types.ModuleType("pydantic_ai")
    fake_pydantic_ai.RunContext = object
    sys.modules["pydantic_ai"] = fake_pydantic_ai

from services.agent_runtime.models import (
    AgentRuntimeMemory,
    QueryKnowledgeInput,
    RolePolicy,
)
from services.agent_runtime.toolsets.knowledge_tools import register_knowledge_tools
from services.context_assembler import AssembledContext


class _FakeAgent:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, func):
        self.tools[func.__name__] = func
        return func


class _FakeEventAdapter:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, dict]] = []
        self.completed: list[tuple[int, str, str, dict]] = []
        self.errored: list[tuple[int, str, str]] = []

    async def on_tool_start(self, tool_name: str, *, description: str | None = None, metadata: dict | None = None) -> int:
        self.started.append((tool_name, description or "", metadata or {}))
        return len(self.started)

    async def on_tool_complete(
        self,
        step_index: int,
        tool_name: str,
        result: str,
        *,
        metadata: dict | None = None,
    ) -> None:
        self.completed.append((step_index, tool_name, result, metadata or {}))

    async def on_tool_error(
        self,
        step_index: int,
        tool_name: str,
        error: str,
        *,
        metadata: dict | None = None,
    ) -> None:
        self.errored.append((step_index, tool_name, error))


class _FakeContextAssembler:
    def __init__(self, assembled: AssembledContext) -> None:
        self.assembled = assembled

    async def assemble(self, *, user_query: str, role_id: str) -> AssembledContext:
        return self.assembled

    async def search_knowledge(self, query: str, *, limit: int = 5):
        return self.assembled.knowledge_results[:limit]


class AgentToolsetTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_knowledge_summary_only_reports_knowledge_hits(self):
        fake_agent = _FakeAgent()
        register_knowledge_tools(
            fake_agent,
            RolePolicy(
                role_id="executor",
                allowed=True,
                capabilities=["rag"],
                allowed_tools=["query_knowledge"],
                allowed_surfaces=["agent"],
                enable_rag=True,
                enable_skill_matching=False,
                instructions="test",
                display_name="Executor",
            ),
        )

        query_knowledge = fake_agent.tools["query_knowledge"]
        assembled = AssembledContext(
            knowledge_results=[],
            knowhow_rules=[{"id": "rule-1", "category": "采购预审", "rule_text": "检查供应商资质", "weight": 3}],
            matched_skills=[],
            source_summary="Know-how(1条)",
        )
        deps = SimpleNamespace(
            event_adapter=_FakeEventAdapter(),
            context_assembler=_FakeContextAssembler(assembled),
            role_id="executor",
            memory=AgentRuntimeMemory(),
        )
        ctx = SimpleNamespace(deps=deps)

        output = await query_knowledge(ctx, QueryKnowledgeInput(query="供应商资质", limit=5))

        self.assertEqual(output.summary, "命中 0 条知识库结果")
        self.assertEqual(output.items, [])
        self.assertEqual(output.citations, [])
        self.assertEqual(deps.memory.tool_calls[0].summary, "命中 0 条知识库结果")
        self.assertEqual(deps.event_adapter.completed[0][2], "命中 0 条知识库结果")


if __name__ == "__main__":
    unittest.main()
