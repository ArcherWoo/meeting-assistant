import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.llm_service import LLMService


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


if __name__ == "__main__":
    unittest.main()