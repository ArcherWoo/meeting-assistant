import os
import sys
import unittest
from unittest.mock import AsyncMock, Mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers.chat import ChatRequest, _assemble_context
from services.context_assembler import AssembledContext, ContextAssembler
from services.retrieval_planner import (
    RetrievalPlan,
    RetrievalPlanAction,
    RetrievalPlanner,
    RetrievalPlannerSettings,
)


class RetrievalPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_falls_back_when_llm_settings_are_missing(self):
        planner = RetrievalPlanner()

        plan = await planner.plan(
            user_query="请核对供应商资质和报价风险",
            enabled_surfaces={"knowledge", "knowhow", "skill"},
            settings=RetrievalPlannerSettings(),
        )

        self.assertEqual(plan.strategy, "fallback")
        self.assertEqual(
            [action.surface for action in plan.actions],
            ["knowledge", "knowhow"],
        )
        self.assertEqual(plan.normalized_query, "请核对供应商资质和报价风险")

    async def test_plan_filters_actions_not_in_enabled_surfaces(self):
        planner = RetrievalPlanner()
        planner._plan_with_llm = AsyncMock(  # type: ignore[method-assign]
            return_value=RetrievalPlan(
                strategy="llm",
                intent="procurement review",
                normalized_query="供应商资质 风险",
                actions=[
                    RetrievalPlanAction(surface="knowhow", query="供应商资质 风险", limit=4),
                    RetrievalPlanAction(surface="skill", query="采购预审", limit=2),
                ],
            )
        )

        plan = await planner.plan(
            user_query="供应商资质和风险怎么审？",
            enabled_surfaces={"knowhow"},
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="deepseek-chat",
            ),
        )

        self.assertEqual(plan.strategy, "llm")
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].surface, "knowhow")

    async def test_plan_uses_json_prompt_fallback_before_heuristic(self):
        planner = RetrievalPlanner()
        planner._plan_with_llm = AsyncMock(side_effect=RuntimeError("tool calling unsupported"))  # type: ignore[method-assign]
        planner._plan_with_json_prompt = AsyncMock(  # type: ignore[method-assign]
            return_value=RetrievalPlan(
                strategy="llm",
                intent="risk review",
                normalized_query="单一来源 风险 资质",
                actions=[
                    RetrievalPlanAction(surface="knowhow", query="单一来源 风险 资质", limit=4),
                ],
            )
        )

        plan = await planner.plan(
            user_query="单一来源风险和资质需要怎么审？",
            enabled_surfaces={"knowledge", "knowhow"},
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="deepseek-chat",
            ),
        )

        self.assertEqual(plan.strategy, "llm")
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].surface, "knowhow")

    async def test_plan_with_llm_uses_shared_llm_service(self):
        llm_service = AsyncMock()
        llm_service.chat.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"intent":"qualification review","normalized_query":"供应商资质 风险",'
                            '"actions":[{"surface":"knowhow","query":"供应商资质 风险","limit":4,"required":true,'
                            '"rationale":"需要规则判断"}],"notes":["llm"]}'
                        )
                    }
                }
            ]
        }
        llm_service.extract_text_content = Mock(return_value=(
            '{"intent":"qualification review","normalized_query":"供应商资质 风险",'
            '"actions":[{"surface":"knowhow","query":"供应商资质 风险","limit":4,"required":true,'
            '"rationale":"需要规则判断"}],"notes":["llm"]}'
        ))
        planner = RetrievalPlanner(llm_service=llm_service)

        plan = await planner._plan_with_llm(
            user_query="请看供应商资质和风险",
            allowed_surfaces=("knowledge", "knowhow"),
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="gpt-4o",
                user_id="user-1",
            ),
        )

        llm_service.chat.assert_awaited_once()
        call = llm_service.chat.await_args
        self.assertEqual(call.kwargs["user_id"], "user-1")
        self.assertEqual(call.kwargs["model"], "gpt-4o")
        self.assertEqual(plan.actions[0].surface, "knowhow")

    async def test_plan_short_circuits_to_heuristic_for_small_talk_and_short_queries(self):
        planner = RetrievalPlanner()
        planner._plan_with_llm = AsyncMock()  # type: ignore[method-assign]
        planner._plan_with_json_prompt = AsyncMock()  # type: ignore[method-assign]

        hello_plan = await planner.plan(
            user_query="你好",
            enabled_surfaces={"knowledge", "knowhow"},
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="gpt-4o",
            ),
        )
        file_plan = await planner.plan(
            user_query="请分析这份文件的内容",
            enabled_surfaces={"knowledge", "knowhow"},
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="gpt-4o",
            ),
        )

        planner._plan_with_llm.assert_not_awaited()
        planner._plan_with_json_prompt.assert_not_awaited()
        self.assertEqual(hello_plan.strategy, "fallback")
        self.assertEqual(hello_plan.actions, [])
        self.assertEqual([action.surface for action in file_plan.actions], ["knowledge"])


class ContextAssemblerPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_assembler_only_executes_surfaces_selected_by_plan(self):
        planner = AsyncMock()
        planner.plan.return_value = RetrievalPlan(
            strategy="llm",
            intent="qualification review",
            normalized_query="供应商资质 单一来源 风险",
            actions=[
                RetrievalPlanAction(
                    surface="knowhow",
                    query="供应商资质 单一来源 风险",
                    limit=4,
                    required=True,
                )
            ],
        )
        assembler = ContextAssembler(planner=planner)
        assembler.search_knowledge = AsyncMock(return_value=[])  # type: ignore[method-assign]
        assembler.get_knowhow_rules = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "id": "rule-1",
                    "category": "采购预审",
                    "rule_text": "供应商资质和单一来源风险需要重点核查",
                    "weight": 4,
                }
            ]
        )
        assembler.match_skills = AsyncMock(return_value=[])  # type: ignore[method-assign]

        ctx = await assembler.assemble(
            user_query="请重点看供应商资质和单一来源风险",
            planner_settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="deepseek-chat",
            ),
            enabled_surfaces={"knowledge", "knowhow", "skill"},
        )

        assembler.search_knowledge.assert_not_awaited()
        assembler.get_knowhow_rules.assert_awaited_once()
        assembler.match_skills.assert_not_awaited()
        self.assertEqual(len(ctx.knowhow_rules), 1)
        self.assertIsNotNone(ctx.retrieval_plan)
        assert ctx.retrieval_plan is not None
        self.assertEqual(ctx.retrieval_plan.strategy, "llm")

    def test_context_metadata_payload_includes_retrieval_plan(self):
        ctx = AssembledContext(
            retrieval_plan=RetrievalPlan(
                strategy="llm",
                intent="price review",
                normalized_query="报价 价格 偏差",
                actions=[
                    RetrievalPlanAction(
                        surface="knowledge",
                        query="报价 价格 偏差",
                        limit=5,
                    )
                ],
            )
        )

        payload = ctx.to_metadata_payload()

        self.assertIsNotNone(payload["retrieval_plan"])
        self.assertEqual(payload["retrieval_plan"]["strategy"], "llm")
        self.assertEqual(payload["retrieval_plan"]["actions"][0]["surface"], "knowledge")

    def test_fusion_reranks_required_action_results_ahead_of_simple_merge_order(self):
        assembler = ContextAssembler()
        actions = [
            RetrievalPlanAction(surface="knowledge", query="报价", limit=3, required=False),
            RetrievalPlanAction(surface="knowledge", query="资质", limit=3, required=True),
        ]
        result_sets = [
            [
                {"id": "price-1", "item_name": "报价单", "category": "价格", "raw_text": "报价说明"},
            ],
            [
                {"id": "qual-1", "item_name": "资质文件", "category": "供应商资质", "raw_text": "资质证明"},
            ],
        ]

        fused = assembler._fuse_surface_results(
            surface="knowledge",
            actions=actions,
            result_sets=result_sets,
            limit=5,
        )

        self.assertEqual([item["id"] for item in fused], ["qual-1", "price-1"])

    def test_fusion_rewards_multi_action_hits_for_knowledge(self):
        assembler = ContextAssembler()
        actions = [
            RetrievalPlanAction(surface="knowledge", query="价格", limit=3, required=False),
            RetrievalPlanAction(surface="knowledge", query="供应商资质", limit=3, required=False),
        ]
        shared = {
            "id": "shared-1",
            "item_name": "供应商资质报价表",
            "category": "供应商资质",
            "raw_text": "同时包含价格和供应商资质信息",
        }
        result_sets = [
            [
                {"id": "price-1", "item_name": "报价单", "category": "价格", "raw_text": "价格信息"},
                shared,
            ],
            [
                shared,
                {"id": "qual-1", "item_name": "资质文件", "category": "供应商资质", "raw_text": "资质信息"},
            ],
        ]

        fused = assembler._fuse_surface_results(
            surface="knowledge",
            actions=actions,
            result_sets=result_sets,
            limit=5,
        )

        self.assertEqual(fused[0]["id"], "shared-1")

    def test_fusion_keeps_relevant_knowhow_rule_above_high_hit_count_noise(self):
        assembler = ContextAssembler()
        actions = [
            RetrievalPlanAction(surface="knowhow", query="单一来源 风险", limit=3, required=True),
        ]
        result_sets = [[
            {
                "id": "rule-noise",
                "category": "通用流程",
                "rule_text": "常规审批流程要求完整留痕",
                "weight": 1,
                "hit_count": 500,
            },
            {
                "id": "rule-hit",
                "category": "采购风控",
                "rule_text": "单一来源采购需要重点核查风险与论证材料",
                "weight": 3,
                "hit_count": 2,
            },
        ]]

        fused = assembler._fuse_surface_results(
            surface="knowhow",
            actions=actions,
            result_sets=result_sets,
            limit=5,
        )

        self.assertEqual(fused[0]["id"], "rule-hit")

    async def test_context_assembler_passes_planner_settings_to_knowhow_surface(self):
        planner = AsyncMock()
        planner.plan.return_value = RetrievalPlan(
            strategy="fallback",
            normalized_query="供应商资质 风险",
            actions=[
                RetrievalPlanAction(
                    surface="knowhow",
                    query="供应商资质 风险",
                    limit=4,
                    required=True,
                )
            ],
        )
        assembler = ContextAssembler(planner=planner)
        assembler.search_knowledge = AsyncMock(return_value=[])  # type: ignore[method-assign]
        assembler.match_skills = AsyncMock(return_value=[])  # type: ignore[method-assign]
        assembler.get_knowhow_rules = AsyncMock(return_value=[])  # type: ignore[method-assign]
        planner_settings = RetrievalPlannerSettings(
            api_url="https://example.com/v1",
            api_key="sk-test",
            model="deepseek-chat",
        )

        await assembler.assemble(
            user_query="请检查供应商资质和风险",
            enabled_surfaces={"knowhow"},
            planner_settings=planner_settings,
        )

        assembler.get_knowhow_rules.assert_awaited_once_with(
            "供应商资质 风险",
            limit=4,
            user=None,
            planner_settings=planner_settings,
        )

    async def test_context_assembler_passes_planner_settings_to_knowledge_surface(self):
        planner = AsyncMock()
        planner.plan.return_value = RetrievalPlan(
            strategy="fallback",
            normalized_query="付款方式 验收",
            actions=[
                RetrievalPlanAction(
                    surface="knowledge",
                    query="付款方式 验收",
                    limit=4,
                    required=True,
                )
            ],
        )
        assembler = ContextAssembler(planner=planner)
        assembler.search_knowledge = AsyncMock(return_value=[])  # type: ignore[method-assign]
        assembler.match_skills = AsyncMock(return_value=[])  # type: ignore[method-assign]
        assembler.get_knowhow_rules = AsyncMock(return_value=[])  # type: ignore[method-assign]
        planner_settings = RetrievalPlannerSettings(
            api_url="https://example.com/v1",
            api_key="sk-test",
            model="deepseek-chat",
        )

        await assembler.assemble(
            user_query="请核对付款方式和验收条件",
            enabled_surfaces={"knowledge"},
            planner_settings=planner_settings,
        )

        assembler.search_knowledge.assert_awaited_once_with(
            "付款方式 验收",
            category=None,
            limit=4,
            planner_settings=planner_settings,
        )


class ChatContextAssemblyTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_assemble_context_passes_runtime_llm_settings_to_planner(self):
        request = ChatRequest(
            messages=[{"role": "user", "content": "请检查供应商资质"}],
            model="deepseek-chat",
            api_url="https://unused.example/v1",
            api_key="",
            role_id="copilot",
        )
        assemble_mock = AsyncMock(return_value=AssembledContext())

        from routers import chat as chat_router

        original_assemble = chat_router.context_assembler.assemble
        original_get_setting = chat_router.storage.get_setting
        original_embedding_api_url = chat_router.embedding_service._api_url
        original_embedding_api_key = chat_router.embedding_service._api_key
        original_embedding_model = chat_router.embedding_service._model
        original_embedding_dimension = chat_router.embedding_service._dimension
        try:
            chat_router.context_assembler.assemble = assemble_mock  # type: ignore[assignment]
            chat_router.storage.get_setting = AsyncMock(return_value="")  # type: ignore[assignment]
            chat_router.embedding_service._api_url = "https://embedding.example/v1"
            chat_router.embedding_service._api_key = "sk-embedding"

            await _assemble_context(
                request,
                [{"role": "user", "content": "请检查供应商资质"}],
                user={"id": "u-1"},
                runtime_api_url="https://runtime.example/v1",
                runtime_api_key="sk-runtime",
                runtime_model="gpt-4o-mini",
            )
        finally:
            chat_router.context_assembler.assemble = original_assemble  # type: ignore[assignment]
            chat_router.storage.get_setting = original_get_setting  # type: ignore[assignment]
            chat_router.embedding_service._api_url = original_embedding_api_url
            chat_router.embedding_service._api_key = original_embedding_api_key
            chat_router.embedding_service._model = original_embedding_model
            chat_router.embedding_service._dimension = original_embedding_dimension

        assemble_mock.assert_awaited_once()
        _, kwargs = assemble_mock.await_args
        planner_settings = kwargs["planner_settings"]
        self.assertEqual(planner_settings.api_url, "https://runtime.example/v1")
        self.assertEqual(planner_settings.api_key, "sk-runtime")
        self.assertEqual(planner_settings.model, "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
