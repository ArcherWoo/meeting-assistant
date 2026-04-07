"""
LLM 服务。

通过 OpenAI 兼容协议与各类模型服务通信，支持：

- 流式聊天
- 非流式聊天
- 模型列表获取
- 轻量连接探测
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, AsyncGenerator

import httpx

from services.runtime_controls import (
    LLMConcurrencyBusyError,
    llm_concurrency_controller,
    runtime_limits,
)


class LLMService:
    """统一的大模型访问服务。"""

    _LIMITS = httpx.Limits(
        max_connections=runtime_limits.llm_http_max_connections,
        max_keepalive_connections=runtime_limits.llm_http_max_keepalive_connections,
        keepalive_expiry=float(runtime_limits.llm_http_keepalive_expiry_sec),
    )

    def __init__(self) -> None:
        try:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                http2=True,
                limits=self._LIMITS,
            )
        except ImportError:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                limits=self._LIMITS,
            )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def extract_text_content(payload: Any) -> str:
        """尽量从兼容响应中提取第一段文本内容。"""
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
                text = _flatten_content(item.get("content"))
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

    @staticmethod
    def _build_timeout(*, connect: float, read: float, write: float = 10.0, pool: float = 5.0) -> httpx.Timeout:
        return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)

    @classmethod
    def _model_list_timeout(cls) -> httpx.Timeout:
        return cls._build_timeout(connect=4.0, read=6.0, write=4.0, pool=3.0)

    @classmethod
    def _chat_timeout(cls) -> httpx.Timeout:
        return cls._build_timeout(connect=8.0, read=120.0, write=20.0, pool=5.0)

    @classmethod
    def _stream_timeout(cls) -> httpx.Timeout:
        return cls._build_timeout(connect=8.0, read=180.0, write=20.0, pool=5.0)

    @classmethod
    def _probe_timeout(cls) -> httpx.Timeout:
        return cls._build_timeout(connect=5.0, read=12.0, write=8.0, pool=3.0)

    async def _fetch_model_ids(self, url: str, headers: dict[str, str]) -> list[str]:
        response = await self._client.get(
            url,
            headers=headers,
            timeout=self._model_list_timeout(),
        )
        self._raise_for_status_with_detail(response)
        model_ids = self._extract_model_ids(response.json())
        if not model_ids:
            raise RuntimeError(f"{url} 未返回任何可用模型")
        return model_ids

    async def _list_models_impl(self, api_url: str, api_key: str) -> list[str]:
        headers = self._build_headers(api_key, include_content_type=False)
        candidate_urls = self._candidate_model_urls(api_url)

        tasks = [
            asyncio.create_task(self._fetch_model_ids(url, headers))
            for url in candidate_urls
        ]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

        errors: list[str] = []
        for url, result in zip(candidate_urls, results):
            if isinstance(result, list) and result:
                return result
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                errors.append(f"{url} 未返回任何可用模型")

        raise RuntimeError("；".join(errors) if errors else "未能获取模型列表")

    async def list_models(
        self,
        api_url: str,
        api_key: str,
        *,
        user_id: str | None = None,
        request_kind: str = "lightweight",
        _skip_limits: bool = False,
    ) -> list[str]:
        if _skip_limits:
            return await self._list_models_impl(api_url=api_url, api_key=api_key)

        async with llm_concurrency_controller.acquire(kind=request_kind, user_id=user_id):
            return await self._list_models_impl(api_url=api_url, api_key=api_key)

    async def _stream_chat_impl(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        api_url: str,
        api_key: str,
    ) -> AsyncGenerator[str, None]:
        url = f"{api_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(api_key)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        async with self._client.stream(
            "POST",
            url,
            json=payload,
            headers=headers,
            timeout=self._stream_timeout(),
        ) as response:
            self._raise_for_status_with_detail(response)
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    yield f"data: {data}\n\n"

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        api_url: str,
        api_key: str,
        *,
        user_id: str | None = None,
        request_kind: str = "stream",
        _skip_limits: bool = False,
    ) -> AsyncGenerator[str, None]:
        try:
            if _skip_limits:
                async for chunk in self._stream_chat_impl(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_url=api_url,
                    api_key=api_key,
                ):
                    yield chunk
                return

            async with llm_concurrency_controller.acquire(kind=request_kind, user_id=user_id):
                async for chunk in self._stream_chat_impl(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_url=api_url,
                    api_key=api_key,
                ):
                    yield chunk
        except LLMConcurrencyBusyError:
            raise
        except Exception as exc:
            error_payload = json.dumps({"stream_error": str(exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"

    async def _chat_impl(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        api_url: str,
        api_key: str,
        *,
        timeout: httpx.Timeout | None = None,
    ) -> dict:
        url = f"{api_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(api_key)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        response = await self._client.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout or self._chat_timeout(),
        )
        self._raise_for_status_with_detail(response)
        return response.json()

    async def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        api_url: str,
        api_key: str,
        *,
        timeout: httpx.Timeout | None = None,
        user_id: str | None = None,
        request_kind: str = "lightweight",
        _skip_limits: bool = False,
    ) -> dict:
        if _skip_limits:
            return await self._chat_impl(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_url=api_url,
                api_key=api_key,
                timeout=timeout,
            )

        async with llm_concurrency_controller.acquire(kind=request_kind, user_id=user_id):
            return await self._chat_impl(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_url=api_url,
                api_key=api_key,
                timeout=timeout,
            )

    async def _probe_model(self, api_url: str, api_key: str, model: str) -> dict[str, Any]:
        return await self.chat(
            messages=[{"role": "user", "content": "Reply with: pong"}],
            model=model,
            temperature=0.0,
            max_tokens=1,
            api_url=api_url,
            api_key=api_key,
            timeout=self._probe_timeout(),
            _skip_limits=True,
        )

    async def test_connection(
        self,
        api_url: str,
        api_key: str,
        model: str = "",
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        async with llm_concurrency_controller.acquire(kind="lightweight", user_id=user_id):
            normalized_model = model.strip()

            if not normalized_model:
                try:
                    available_models = await self.list_models(
                        api_url=api_url,
                        api_key=api_key,
                        _skip_limits=True,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"无法获取模型列表：{str(exc)}。如果该服务不支持 /models，请先填写模型名再测试。"
                    ) from exc
                if not available_models:
                    raise RuntimeError("接口已连通，但未返回任何可用模型")
                return {
                    "model": available_models[0],
                    "available_models": available_models,
                    "selected_model_available": True,
                    "fallback": False,
                }

            model_task = asyncio.create_task(
                self.list_models(
                    api_url=api_url,
                    api_key=api_key,
                    _skip_limits=True,
                )
            )
            try:
                probe_result = await self._probe_model(api_url=api_url, api_key=api_key, model=normalized_model)
            except Exception as probe_error:
                available_models: list[str] = []
                model_list_error: Exception | None = None
                try:
                    available_models = await model_task
                except Exception as exc:  # pragma: no cover
                    model_list_error = exc

                if available_models:
                    if normalized_model not in available_models:
                        raise RuntimeError(
                            f"连接已建立，但填写的模型“{normalized_model}”不在服务返回的模型列表中。"
                        ) from probe_error
                    raise RuntimeError(
                        f"模型“{normalized_model}”连通性测试失败：{str(probe_error)}"
                    ) from probe_error

                if model_list_error:
                    raise RuntimeError(
                        f"使用模型“{normalized_model}”进行轻量探测失败：{str(probe_error)}；"
                        f"同时获取模型列表也失败：{str(model_list_error)}"
                    ) from probe_error

                raise RuntimeError(
                    f"使用模型“{normalized_model}”进行轻量探测失败：{str(probe_error)}"
                ) from probe_error

            resolved_model = str(probe_result.get("model") or normalized_model).strip() or normalized_model

            if model_task.done():
                try:
                    available_models = await model_task
                except Exception:
                    available_models = [resolved_model]
                    fallback = True
                else:
                    if not available_models:
                        available_models = [resolved_model]
                        fallback = True
                    else:
                        fallback = False
            else:
                model_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await model_task
                available_models = [resolved_model]
                fallback = True

            return {
                "model": resolved_model,
                "available_models": available_models,
                "selected_model_available": resolved_model in available_models or normalized_model in available_models,
                "fallback": fallback,
            }


llm_service = LLMService()
