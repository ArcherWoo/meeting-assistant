import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.llm_service import LLMService
from services.context_assembler import AssembledContext
from routers.chat import (
    ChatRequest,
    _calculate_context_budget_chars,
    _stream_with_metadata,
    _strip_attachment_context,
)


class LLMServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = LLMService()

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

    def test_strip_attachment_context_keeps_only_user_query(self):
        polluted = "帮我分析采购价格\n\n---\n📎 附件「报价单.xlsx」内容（123 字符）：\n\n很长的附件正文"
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

    async def test_stream_with_metadata_injects_events_before_done(self):
        async def raw_stream():
            yield 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
            yield 'data: [DONE]\n\n'

        ctx = AssembledContext(
            knowledge_results=[{"item_name": "服务器", "category": "IT"}],
            matched_skills=[
                {
                    "skill_id": "procurement-review",
                    "skill_name": "采购预审",
                    "description": "辅助检查采购材料",
                    "score": 0.93,
                    "confidence": "high",
                }
            ],
            source_summary="知识库(1条) + Skill(1个)",
        )

        chunks = [chunk async for chunk in _stream_with_metadata(raw_stream(), ctx)]

        self.assertIn('"content":"你好"', chunks[0])
        self.assertIn('"type": "context_metadata"', chunks[1])
        self.assertIn('"type": "skill_suggestion"', chunks[2])
        self.assertEqual(chunks[3], 'data: [DONE]\n\n')

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


if __name__ == "__main__":
    unittest.main()