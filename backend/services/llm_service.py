"""
LLM 服务 - OpenAI 兼容协议
支持流式 SSE 和非流式响应，兼容 OpenAI / DeepSeek / 通义千问 / Ollama 等
"""
import json
from typing import Any, AsyncGenerator
import httpx


class LLMService:
    """LLM 对话服务，通过 OpenAI 兼容协议与各类模型通信"""

    @staticmethod
    def extract_text_content(payload: Any) -> str:
        """尽量从 OpenAI 兼容响应中提取首条文本内容。"""
        if isinstance(payload, str):
            return payload.strip()

        if not isinstance(payload, dict):
            return ""

        def _flatten_content(content: Any) -> str:
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, str):
                        text = item.strip()
                        if text:
                            parts.append(text)
                    elif isinstance(item, dict):
                        text = item.get("text") or item.get("content") or item.get("value")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
                return "".join(parts).strip()
            return ""

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    text = _flatten_content(message.get("content"))
                    if text:
                        return text

                delta = first.get("delta")
                if isinstance(delta, dict):
                    text = _flatten_content(delta.get("content"))
                    if text:
                        return text

                text = _flatten_content(first.get("text"))
                if text:
                    return text

        text = _flatten_content(payload.get("output_text"))
        if text:
            return text

        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                text = _flatten_content(content)
                if text:
                    return text

        message = payload.get("message")
        if isinstance(message, dict):
            text = _flatten_content(message.get("content"))
            if text:
                return text

        return ""

    @staticmethod
    def _build_headers(api_key: str, *, include_content_type: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _extract_model_ids(payload: dict[str, Any]) -> list[str]:
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raw_models = payload.get("models")

        if not isinstance(raw_models, list):
            return []

        model_ids: list[str] = []
        for item in raw_models:
            model_id = None
            if isinstance(item, str):
                model_id = item
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name")

            if isinstance(model_id, str) and model_id and model_id not in model_ids:
                model_ids.append(model_id)

        return model_ids

    @staticmethod
    def _candidate_model_urls(api_url: str) -> list[str]:
        base_url = api_url.rstrip("/")
        candidates = [f"{base_url}/models"]

        if base_url.endswith("/v1"):
            candidates.append(f"{base_url[:-3]}/models")

        deduped: list[str] = []
        for url in candidates:
            if url not in deduped:
                deduped.append(url)
        return deduped

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        payload: dict[str, Any] | None = None
        try:
            maybe_payload = response.json()
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
        except ValueError:
            payload = None

        message = ""
        if payload:
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                message = (
                    str(error_payload.get("message") or "").strip()
                    or str(error_payload.get("detail") or "").strip()
                    or str(error_payload.get("type") or "").strip()
                )
            elif isinstance(error_payload, str):
                message = error_payload.strip()

            if not message:
                message = (
                    str(payload.get("detail") or "").strip()
                    or str(payload.get("message") or "").strip()
                )

        if not message:
            message = response.text.strip() or response.reason_phrase or f"HTTP {response.status_code}"

        return f"HTTP {response.status_code} @ {response.request.url}: {message}"

    @classmethod
    def _raise_for_status_with_detail(cls, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(cls._extract_error_message(response)) from exc

    async def list_models(self, api_url: str, api_key: str) -> list[str]:
        """获取 OpenAI 兼容接口可用模型列表"""
        # GET 请求不需要 Content-Type
        headers = self._build_headers(api_key, include_content_type=False)
        candidate_urls = self._candidate_model_urls(api_url)
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for url in candidate_urls:
                try:
                    response = await client.get(url, headers=headers)
                    self._raise_for_status_with_detail(response)
                    model_ids = self._extract_model_ids(response.json())
                    if model_ids:
                        return model_ids
                    errors.append(f"{url} 未返回任何可用模型")
                except Exception as exc:
                    errors.append(str(exc))

        error_message = "；".join(errors) if errors else "未能获取模型列表"
        raise RuntimeError(error_message)

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        api_url: str,
        api_key: str,
    ) -> AsyncGenerator[str, None]:
        """
        流式聊天 - 返回 SSE 格式数据流
        每个 chunk 格式: data: {"choices":[{"delta":{"content":"..."}}]}
        """
        url = f"{api_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(api_key)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    self._raise_for_status_with_detail(response)
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data.strip() == "[DONE]":
                                yield "data: [DONE]\n\n"
                                return
                            yield f"data: {data}\n\n"
        except Exception as exc:
            # 流中途出现异常时，通过 SSE 内嵌错误事件通知前端，
            # 避免前端把连接断开误判为正常结束（onDone）
            error_payload = json.dumps({"stream_error": str(exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"

    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        api_url: str,
        api_key: str,
    ) -> dict:
        """非流式聊天 - 返回完整响应"""
        url = f"{api_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(api_key)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            self._raise_for_status_with_detail(response)
            return response.json()

    async def test_connection(self, api_url: str, api_key: str, model: str = "") -> dict[str, Any]:
        """测试 API 连通性，并尽可能返回可用模型列表"""
        normalized_model = model.strip()

        try:
            available_models = await self.list_models(api_url=api_url, api_key=api_key)
            if not available_models:
                raise ValueError("接口已连通，但未返回任何可用模型")

            selected_model = normalized_model or available_models[0]
            return {
                "model": selected_model,
                "available_models": available_models,
                "selected_model_available": selected_model in available_models,
                "fallback": False,
            }
        except Exception as model_list_error:
            if not normalized_model:
                raise RuntimeError(
                    f"无法获取模型列表：{str(model_list_error)}。如果该服务不支持 /models，请先填写模型名再测试。"
                ) from model_list_error

            try:
                result = await self.chat(
                    messages=[{"role": "user", "content": "Hi"}],
                    model=normalized_model,
                    temperature=1.0,
                    max_tokens=5,
                    api_url=api_url,
                    api_key=api_key,
                )
            except Exception as chat_error:
                raise RuntimeError(
                    f"模型列表接口不可用：{str(model_list_error)}；并且使用模型“{normalized_model}”进行轻量调用也失败：{str(chat_error)}"
                ) from chat_error

            resolved_model = result.get("model", normalized_model)

            return {
                "model": resolved_model,
                "available_models": [resolved_model],
                "selected_model_available": True,
                "fallback": True,
            }

