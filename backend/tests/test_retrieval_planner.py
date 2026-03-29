import os
import sys
import unittest
from unittest.mock import AsyncMock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

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
            ["knowledge", "knowhow", "skill"],
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
            user_query="供应商资质和风险怎么审",
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
            user_query="单一来源风险和资质需要怎么审",
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


if __name__ == "__main__":
    unittest.main()
