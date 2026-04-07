import asyncio
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.llm_service import LLMService
from services.context_assembler import AssembledContext, ContextAssembler
from services.retrieval_planner import RetrievalPlan, RetrievalPlanAction
from services.runtime_controls import LLMConcurrencyBusyError
from routers import chat as chat_router
from routers.chat import (
    ChatTimingMetrics,
    ChatRequest,
    _build_context_metadata_payload,
    _calculate_context_budget_chars,
    _format_status_event,
    _is_content_sse_chunk,
    _stream_with_metadata,
    _strip_attachment_context,
)


class LLMServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = LLMService()

    async def asyncTearDown(self):
        await self.service.aclose()

    def test_candidate_model_urls_supports_v1_base(self):
        self.assertEqual(
            self.service._candidate_model_urls("https://api.deepseek.com/v1"),
            [
                "https://api.deepseek.com/v1/models",
                "https://api.deepseek.com/models",
            ],
        )

    def test_extract_error_message_reads_provider_payload(self):
        request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"message": "Model `gpt-4o` does not exist"}},
        )

        message = self.service._extract_error_message(response)
        self.assertIn("Model `gpt-4o` does not exist", message)
        self.assertIn("https://api.deepseek.com/v1/chat/completions", message)

    async def test_test_connection_uses_chat_fallback_when_model_is_given(self):
        with patch.object(self.service, "list_models", AsyncMock(side_effect=RuntimeError("/models 404"))):
            with patch.object(
                self.service,
                "chat",
                AsyncMock(return_value={"model": "deepseek-chat"}),
            ):
                result = await self.service.test_connection(
                    api_url="https://api.deepseek.com/v1",
                    api_key="sk-test",
                    model="deepseek-chat",
                )

        self.assertEqual(result["available_models"], ["deepseek-chat"])
        self.assertTrue(result["selected_model_available"])
        self.assertTrue(result["fallback"])

    async def test_test_connection_requires_model_when_model_list_fails(self):
        with patch.object(self.service, "list_models", AsyncMock(side_effect=RuntimeError("/models 404"))):
            with self.assertRaises(RuntimeError) as context:
                await self.service.test_connection(
                    api_url="https://api.deepseek.com/v1",
                    api_key="sk-test",
                    model="",
                )

        self.assertIn("请先填写模型名再测试", str(context.exception))

    async def test_test_connection_returns_quickly_when_probe_succeeds_before_model_list(self):
        async def slow_list_models(*args, **kwargs):
            await asyncio.sleep(1.0)
            return ["deepseek-chat", "deepseek-reasoner"]

        with patch.object(self.service, "list_models", side_effect=slow_list_models):
            with patch.object(
                self.service,
                "chat",
                AsyncMock(return_value={"model": "deepseek-chat"}),
            ):
                result = await asyncio.wait_for(
                    self.service.test_connection(
                        api_url="https://api.deepseek.com/v1",
                        api_key="sk-test",
                        model="deepseek-chat",
                    ),
                    timeout=0.25,
                )

        self.assertEqual(result["model"], "deepseek-chat")
        self.assertEqual(result["available_models"], ["deepseek-chat"])
        self.assertTrue(result["selected_model_available"])
        self.assertTrue(result["fallback"])

    def test_strip_attachment_context_keeps_only_user_query(self):
        polluted = "帮我分析采购价格\n\n---\n📎 附件“报价单.xlsx”内容（123 字符）：\n\n很长的附件正文"
        self.assertEqual(_strip_attachment_context(polluted), "帮我分析采购价格")

    def test_context_fit_to_budget_keeps_complete_items_only(self):
        ctx = AssembledContext(
            knowhow_rules=[
                {"rule_text": "规则一", "weight": 5},
                {"rule_text": "规则二-很长很长很长", "weight": 1},
            ],
            knowledge_results=[
                {"item_name": "服务器", "category": "IT", "supplier": "供应商A", "unit_price": 99},
            ],
            matched_skills=[
                {"skill_name": "采购预审", "description": "辅助预审", "score": 0.91, "confidence": "high"},
            ],
        )

        single_rule_chars = len(
            AssembledContext(knowhow_rules=ctx.knowhow_rules[:1]).to_prompt_suffix()
        )
        all_rules_chars = len(
            AssembledContext(knowhow_rules=ctx.knowhow_rules).to_prompt_suffix()
        )

        self.assertLess(single_rule_chars, all_rules_chars)

        fitted = ctx.fit_to_budget(all_rules_chars - 1)

        self.assertEqual(len(fitted.knowhow_rules), 1)
        self.assertEqual(len(fitted.knowledge_results), 0)
        self.assertEqual(len(fitted.matched_skills), 0)
        self.assertEqual(fitted.source_summary, "Know-how(1条)")
        self.assertLessEqual(len(fitted.to_prompt_suffix()), all_rules_chars - 1)

    def test_context_metadata_payload_includes_file_and_fragment_level_fields(self):
        ctx = AssembledContext(
            knowledge_results=[
                {
                    "id": "chunk-7",
                    "source_file": "采购方案.pdf",
                    "slide_index": 2,
                    "chunk_type": "table",
                    "chunk_index": 7,
                    "char_start": 120,
                    "char_end": 268,
                    "content": "A 供应商服务器报价 128000 元，含 3 年维保。",
                }
            ],
            source_summary="知识库(1条)",
        )

        payload = ctx.to_metadata_payload()
        self.assertEqual(payload["summary"], "知识库(1条)")
        self.assertEqual(len(payload["citations"]), 1)

        citation = payload["citations"][0]
        self.assertEqual(citation["label"], "采购方案.pdf")
        self.assertEqual(citation["file_name"], "采购方案.pdf")
        self.assertEqual(citation["title"], "第2页 · 表格片段")
        self.assertEqual(citation["location"], "片段 #7 · 字符 121-268")
        self.assertEqual(citation["page"], 2)
        self.assertEqual(citation["chunk_type"], "table")
        self.assertEqual(citation["chunk_index"], 7)
        self.assertEqual(citation["char_start"], 121)
        self.assertEqual(citation["char_end"], 268)
        self.assertIn("A 供应商服务器报价", citation["snippet"])

    def test_context_metadata_payload_includes_knowhow_route_details(self):
        ctx = AssembledContext(
            knowhow_rules=[
                {
                    "id": "kh-1",
                    "category": "采购预审",
                    "title": "供应商资质要求",
                    "rule_text": "供应商必须提供 ISO 9001 质量管理体系认证或相关行业资质。",
                    "weight": 4,
                    "route_strategy": "llm_route",
                    "route_confidence": "high",
                    "route_rationale": "采购风险判断",
                    "llm_judge_rationale": "供应商资质是当前问题的核心",
                }
            ],
            source_summary="Know-how(1条)",
        )

        payload = ctx.to_metadata_payload()
        citation = payload["citations"][0]

        self.assertEqual(citation["title"], "供应商资质要求")
        self.assertEqual(citation["label"], "采购预审")
        self.assertIn("分类 采购预审", citation["location"])
        self.assertIn("命中方式 LLM 意图路由", citation["location"])
        self.assertIn("原因 供应商资质是当前问题的核心", citation["location"])
        self.assertEqual(citation["route_strategy"], "llm_route")
        self.assertEqual(citation["route_confidence"], "high")
        self.assertEqual(citation["route_rationale"], "采购风险判断")
        self.assertEqual(citation["llm_judge_rationale"], "供应商资质是当前问题的核心")

    def test_context_metadata_payload_keeps_timings_without_retrieval_context(self):
        payload = _build_context_metadata_payload(
            AssembledContext(),
            timings={
                "attachment_ms": 32,
                "llm_total_ms": 1680,
                "end_to_end_ms": 1815,
            },
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["knowledge_count"], 0)
        self.assertEqual(payload["knowhow_count"], 0)
        self.assertEqual(payload["skill_count"], 0)
        self.assertEqual(payload["timings"]["attachment_ms"], 32)
        self.assertEqual(payload["timings"]["llm_total_ms"], 1680)
        self.assertEqual(payload["timings"]["end_to_end_ms"], 1815)

    async def test_stream_with_metadata_injects_events_before_done(self):
        async def raw_stream():
            yield 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
            yield 'data: [DONE]\n\n'

        ctx = AssembledContext(
            knowledge_results=[{"item_name": "服务器", "category": "IT", "source_file": "采购台账.xlsx"}],
            matched_skills=[
                {
                    "skill_id": "procurement-review",
                    "skill_name": "采购预审",
                    "description": "辅助检查采购材料",
                    "score": 0.93,
                    "confidence": "high",
                    "matched_keywords": ["采购", "预审"],
                }
            ],
            source_summary="知识库(1条) + Skill(1个)",
        )

        chunks = [
            chunk async for chunk in _stream_with_metadata(
                raw_stream(),
                ctx,
                timings=ChatTimingMetrics(
                    retrieval_ms=420,
                    llm_first_token_ms=780,
                    llm_total_ms=1560,
                ),
            )
        ]

        self.assertIn('"content":"你好"', chunks[0])
        self.assertIn('"type": "context_metadata"', chunks[1])
        self.assertIn('"citations"', chunks[1])
        self.assertIn('"source_type": "knowledge"', chunks[1])
        self.assertIn('"file_name": "采购台账.xlsx"', chunks[1])
        self.assertIn('"title": "IT - 服务器"', chunks[1])
        self.assertIn('"schema_version": 2', chunks[1])
        self.assertIn('"timings": {"retrieval_ms": 420, "llm_first_token_ms": 780, "llm_total_ms": 1560}', chunks[1])
        self.assertIn('"type": "skill_suggestion"', chunks[2])
        self.assertIn('"matched_keywords": ["采购", "预审"]', chunks[2])
        self.assertEqual(chunks[3], 'data: [DONE]\n\n')

    async def test_stream_with_metadata_keeps_skill_suggestion_when_prompt_context_is_trimmed(self):
        async def raw_stream():
            yield 'data: {"choices":[{"delta":{"content":"继续"}}]}\n\n'
            yield 'data: [DONE]\n\n'

        prompt_ctx = AssembledContext(
            knowhow_rules=[{"id": "kh-1", "rule_text": "先检查预算归口", "weight": 5}],
            source_summary="Know-how(1条)",
        )
        retrieved_ctx = AssembledContext(
            knowhow_rules=[{"id": "kh-1", "rule_text": "先检查预算归口", "weight": 5}],
            matched_skills=[
                {
                    "skill_id": "procurement-review",
                    "skill_name": "采购预审",
                    "description": "辅助检查采购材料",
                    "score": 0.93,
                    "confidence": "high",
                    "matched_keywords": ["采购", "审查"],
                }
            ],
            source_summary="Know-how(1条) + Skill(1个)",
        )

        chunks = [
            chunk async for chunk in _stream_with_metadata(
                raw_stream(),
                prompt_ctx,
                retrieved_ctx,
                retrieved_ctx.matched_skills[0],
            )
        ]

        self.assertIn('"truncated": true', chunks[1])
        self.assertIn('"retrieved_skill_count": 1', chunks[1])
        self.assertIn('"retrieved_summary": "Know-how(1条) + Skill(1个)"', chunks[1])
        self.assertIn('"type": "skill_suggestion"', chunks[2])
        self.assertIn('"matched_keywords": ["采购", "审查"]', chunks[2])
        self.assertEqual(chunks[3], 'data: [DONE]\n\n')

    def test_status_event_and_content_chunk_helpers(self):
        status_event = _format_status_event("retrieving", "正在准备上下文", "正在检索相关知识和规则")
        self.assertIn('"type": "status"', status_event)
        self.assertIn('"phase": "retrieving"', status_event)
        self.assertIn('"label": "正在准备上下文"', status_event)

        self.assertTrue(_is_content_sse_chunk('data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'))
        self.assertFalse(_is_content_sse_chunk('data: {"type":"status","phase":"queued"}\n\n'))
        self.assertFalse(_is_content_sse_chunk('data: [DONE]\n\n'))

    def test_context_budget_uses_model_window_not_output_tokens(self):
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "请分析历史采购价格"},
        ]
        small_model_request = ChatRequest(api_key="sk-test", model="gpt-4", max_tokens=4096, messages=[])
        large_model_request = ChatRequest(api_key="sk-test", model="gpt-4o", max_tokens=4096, messages=[])

        small_budget = _calculate_context_budget_chars(messages, small_model_request)
        large_budget = _calculate_context_budget_chars(messages, large_model_request)

        self.assertGreater(large_budget, small_budget)
        self.assertGreater(large_budget, 0)

    async def test_context_assembler_filters_irrelevant_knowhow_rules(self):
        assembler = ContextAssembler()
        rules = [
            {
                "id": "price-rule",
                "category": "采购预审",
                "rule_text": "价格与历史同品类均价对比，偏差应在合理范围内",
                "weight": 3,
                "hit_count": 2,
            },
            {
                "id": "supplier-rule",
                "category": "采购预审",
                "rule_text": "供应商必须提供 ISO 9001 质量管理体系认证或相关行业资质",
                "weight": 3,
                "hit_count": 8,
            },
            {
                "id": "weather-rule",
                "category": "闲聊",
                "rule_text": "今天天气晴朗适合外出活动",
                "weight": 5,
                "hit_count": 100,
            },
        ]

        with patch("services.context_assembler.knowhow_service.list_rules", AsyncMock(return_value=rules)):
            filtered = await assembler._get_knowhow_rules("这份采购材料需要重点看供应商资质和认证吗")

        self.assertEqual([rule["id"] for rule in filtered], ["supplier-rule"])

    async def test_context_assembler_records_knowhow_hits_for_retrieved_rules(self):
        assembler = ContextAssembler()
        routed_rules = [
            {
                "id": "supplier-rule",
                "category": "采购预审",
                "title": "供应商资质要求",
                "rule_text": "供应商必须提供 ISO 9001 质量管理体系认证或相关行业资质",
                "weight": 3,
                "route_strategy": "heuristic_category_match",
                "route_confidence": "high",
                "route_rationale": "资质问题",
            }
        ]
        routing_result = SimpleNamespace(
            rules=tuple(routed_rules),
            decision=SimpleNamespace(strategy="heuristic_category_match", categories=("采购预审",)),
        )

        with patch("services.context_assembler.knowhow_service.list_rules", AsyncMock(return_value=routed_rules)):
            with patch("services.context_assembler.knowhow_service.list_categories", AsyncMock(return_value=[{"name": "采购预审"}])):
                with patch("services.context_assembler.knowhow_router.retrieve_rules", AsyncMock(return_value=routing_result)):
                    with patch("services.context_assembler.knowhow_service.record_rule_hits", AsyncMock()) as record_hits:
                        filtered = await assembler._get_knowhow_rules("这份采购材料需要重点看供应商资质和认证吗")

        self.assertEqual([rule["id"] for rule in filtered], ["supplier-rule"])
        record_hits.assert_awaited_once()
        recorded_rules = record_hits.await_args.args[0]
        self.assertEqual([rule["id"] for rule in recorded_rules], ["supplier-rule"])

    async def test_context_assembler_returns_library_summary_for_knowhow_stats_question(self):
        assembler = ContextAssembler()
        summary_rule = {
            "id": "virtual-knowhow-library-summary",
            "category": "规则库概览",
            "title": "Know-how 规则库统计",
            "rule_text": "当前你可访问的 Know-how 规则共 12 条，其中启用 10 条，覆盖 4 个分类。",
            "weight": 0,
            "is_virtual": True,
            "route_strategy": "library_summary",
            "route_confidence": "high",
            "route_rationale": "规则库统计问题",
        }

        with patch("services.context_assembler.knowhow_service.list_rules", AsyncMock(return_value=[])):
            with patch("services.context_assembler.knowhow_service.list_categories", AsyncMock(return_value=[{"name": "采购预审", "rule_count": 5}])):
                with patch("services.context_assembler.knowhow_router.inspect_library_query", AsyncMock(return_value=SimpleNamespace(
                    use_summary=True,
                    focus="stats",
                    rationale="规则库统计问题",
                    confidence="high",
                ))):
                    with patch("services.context_assembler.knowhow_service.build_library_summary_rule", AsyncMock(return_value=summary_rule)) as build_summary:
                        filtered = await assembler._get_knowhow_rules("Knowhow 规则库现在有几条规则？")

        self.assertEqual([rule["id"] for rule in filtered], ["virtual-knowhow-library-summary"])
        build_summary.assert_awaited_once()

    async def test_context_assembler_sorts_knowhow_rules_by_relevance_then_weight(self):
        assembler = ContextAssembler()
        rules = [
            {
                "id": "price-rule",
                "category": "采购预审",
                "rule_text": "价格与历史同品类均价对比，偏差应在合理范围内",
                "weight": 2,
                "hit_count": 0,
            },
            {
                "id": "price-and-supplier-rule",
                "category": "采购预审",
                "rule_text": "供应商报价需要同时核查价格偏差与历史合作记录",
                "weight": 3,
                "hit_count": 5,
            },
            {
                "id": "payment-rule",
                "category": "采购预审",
                "rule_text": "付款方式与条件是否合理",
                "weight": 3,
                "hit_count": 3,
            },
        ]

        with patch("services.context_assembler.knowhow_service.list_rules", AsyncMock(return_value=rules)):
            filtered = await assembler._get_knowhow_rules("请帮我看这次供应商报价和价格是否合理")

        filtered_ids = [rule["id"] for rule in filtered]
        self.assertTrue(filtered_ids)
        self.assertEqual(filtered_ids[0], "price-and-supplier-rule")
        self.assertNotIn("payment-rule", filtered_ids)

    async def test_context_assembler_supports_any_role_once_rag_capability_is_gated_upstream(self):
        assembler = ContextAssembler()

        plan = RetrievalPlan(
            strategy="fallback",
            intent="采购价格分析",
            normalized_query="帮我看看这次报价是否合理",
            actions=[
                RetrievalPlanAction(surface="knowledge", query="报价 是否 合理", limit=1, required=True),
                RetrievalPlanAction(surface="knowhow", query="价格 偏差 检查", limit=1, required=False),
            ],
        )

        with patch.object(assembler, "_plan_retrieval", AsyncMock(return_value=plan)):
            with patch.object(assembler, "search_knowledge", AsyncMock(return_value=[{
                "id": "chunk-1",
                "content": "报价偏高，需要对比历史均价",
                "source_file": "报价单.pdf",
            }])):
                with patch.object(assembler, "get_knowhow_rules", AsyncMock(return_value=[{
                    "id": "rule-1",
                    "category": "采购预审",
                    "rule_text": "优先检查价格偏差",
                    "weight": 3,
                }])):
                    with patch.object(assembler, "match_skills", AsyncMock(return_value=[])):
                        ctx = await assembler.assemble("帮我看看这次报价是否合理", role_id="custom-rag-role")

        self.assertTrue(ctx.has_context)
        self.assertEqual(len(ctx.knowledge_results), 1)
        self.assertEqual(len(ctx.knowhow_rules), 1)
        self.assertEqual(ctx.source_summary, "知识库(1条) + Know-how(1条)")


class ChatConcurrencyGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completions_rejects_busy_conversation(self):
        request = chat_router.ChatRequest(
            messages=[chat_router.ChatMessage(role="user", content="你好")],
            api_key="sk-test",
            stream=True,
            conversation_id="conv-1",
        )
        user = {"id": "user-1", "system_role": "user"}

        with patch("routers.chat.get_runtime_llm_config", AsyncMock(return_value={
            "api_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "deepseek-chat",
            "profile_id": "",
            "profile": None,
        })):
            with patch.object(chat_router.storage, "get_conversation_owner_id", AsyncMock(return_value="user-1")):
                with patch.object(chat_router.conversation_generation_registry, "try_acquire", AsyncMock(return_value=False)):
                    with self.assertRaises(HTTPException) as context:
                        await chat_router.chat_completions(request, user=user)

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("生成中", context.exception.detail)


class ChatConcurrencyOverloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completions_returns_429_before_stream_when_llm_slots_are_exhausted(self):
        request = chat_router.ChatRequest(
            messages=[chat_router.ChatMessage(role="user", content="浣犲ソ")],
            api_key="sk-test",
            stream=True,
            conversation_id="conv-1",
        )
        user = {"id": "user-1", "system_role": "user"}

        with patch("routers.chat.get_runtime_llm_config", AsyncMock(return_value={
            "api_url": "https://example.com/v1",
            "api_key": "sk-test",
            "model": "deepseek-chat",
            "profile_id": "",
            "profile": None,
        })):
            with patch.object(chat_router.storage, "get_conversation_owner_id", AsyncMock(return_value="user-1")):
                with patch.object(chat_router.conversation_generation_registry, "try_acquire", AsyncMock(return_value=True)):
                    with patch.object(
                        chat_router.llm_concurrency_controller,
                        "acquire",
                        side_effect=LLMConcurrencyBusyError("当前模型服务繁忙，请稍后重试"),
                    ):
                        with self.assertRaises(HTTPException) as context:
                            await chat_router.chat_completions(request, user=user)

        self.assertEqual(context.exception.status_code, 429)
        self.assertIn("模型服务繁忙", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
