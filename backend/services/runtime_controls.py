from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


@dataclass(frozen=True)
class RuntimeLimitConfig:
    llm_global_concurrency: int
    llm_stream_concurrency: int
    llm_lightweight_concurrency: int
    llm_per_user_concurrency: int
    llm_slot_acquire_timeout_ms: int
    llm_http_max_connections: int
    llm_http_max_keepalive_connections: int
    llm_http_keepalive_expiry_sec: int
    attachment_parse_concurrency: int
    attachment_ingest_concurrency: int
    attachment_fast_acquire_timeout_ms: int
    attachment_ingest_acquire_timeout_ms: int


def load_runtime_limits() -> RuntimeLimitConfig:
    llm_global = _int_env("MEETING_ASSISTANT_LLM_GLOBAL_CONCURRENCY", 12)
    llm_stream = min(
        llm_global,
        _int_env("MEETING_ASSISTANT_LLM_STREAM_CONCURRENCY", 6),
    )
    llm_lightweight = min(
        llm_global,
        _int_env("MEETING_ASSISTANT_LLM_LIGHTWEIGHT_CONCURRENCY", 8),
    )
    attachment_total = _int_env("MEETING_ASSISTANT_ATTACHMENT_PARSE_CONCURRENCY", 4)
    attachment_ingest = min(
        attachment_total,
        _int_env("MEETING_ASSISTANT_ATTACHMENT_INGEST_CONCURRENCY", 2),
    )
    return RuntimeLimitConfig(
        llm_global_concurrency=llm_global,
        llm_stream_concurrency=llm_stream,
        llm_lightweight_concurrency=llm_lightweight,
        llm_per_user_concurrency=_int_env("MEETING_ASSISTANT_LLM_PER_USER_CONCURRENCY", 3),
        llm_slot_acquire_timeout_ms=_int_env("MEETING_ASSISTANT_LLM_SLOT_ACQUIRE_TIMEOUT_MS", 1500),
        llm_http_max_connections=_int_env("MEETING_ASSISTANT_LLM_HTTP_MAX_CONNECTIONS", 40),
        llm_http_max_keepalive_connections=_int_env("MEETING_ASSISTANT_LLM_HTTP_MAX_KEEPALIVE_CONNECTIONS", 20),
        llm_http_keepalive_expiry_sec=_int_env("MEETING_ASSISTANT_LLM_HTTP_KEEPALIVE_EXPIRY_SEC", 45),
        attachment_parse_concurrency=attachment_total,
        attachment_ingest_concurrency=attachment_ingest,
        attachment_fast_acquire_timeout_ms=_int_env("MEETING_ASSISTANT_ATTACHMENT_FAST_TIMEOUT_MS", 8000),
        attachment_ingest_acquire_timeout_ms=_int_env("MEETING_ASSISTANT_ATTACHMENT_INGEST_TIMEOUT_MS", 20000),
    )


class ServiceBusyError(RuntimeError):
    """Base exception for bounded runtime resources."""


class LLMConcurrencyBusyError(ServiceBusyError):
    """Raised when LLM slots are exhausted."""


class ConversationBusyError(ServiceBusyError):
    """Raised when the same conversation is already generating."""


class AttachmentParseBusyError(ServiceBusyError):
    """Raised when attachment parsing slots are exhausted."""


class LLMConcurrencyController:
    def __init__(
        self,
        *,
        global_limit: int,
        stream_limit: int,
        lightweight_limit: int,
        per_user_limit: int,
        acquire_timeout_ms: int,
    ) -> None:
        self._global = asyncio.Semaphore(global_limit)
        self._stream = asyncio.Semaphore(stream_limit)
        self._lightweight = asyncio.Semaphore(lightweight_limit)
        self._per_user_limit = per_user_limit
        self._acquire_timeout_s = max(acquire_timeout_ms, 1) / 1000.0
        self._user_counts: dict[str, int] = {}
        self._user_lock = asyncio.Lock()

    async def _reserve_user_slot(self, user_id: str | None) -> None:
        normalized = (user_id or "").strip()
        if not normalized:
            return
        async with self._user_lock:
            current = self._user_counts.get(normalized, 0)
            if current >= self._per_user_limit:
                raise LLMConcurrencyBusyError("当前账号的模型并发请求过多，请稍后再试")
            self._user_counts[normalized] = current + 1

    async def _release_user_slot(self, user_id: str | None) -> None:
        normalized = (user_id or "").strip()
        if not normalized:
            return
        async with self._user_lock:
            current = self._user_counts.get(normalized, 0)
            if current <= 1:
                self._user_counts.pop(normalized, None)
            else:
                self._user_counts[normalized] = current - 1

    async def _acquire(self, semaphore: asyncio.Semaphore, message: str) -> None:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self._acquire_timeout_s)
        except asyncio.TimeoutError as exc:
            raise LLMConcurrencyBusyError(message) from exc

    @asynccontextmanager
    async def acquire(self, *, kind: str, user_id: str | None = None):
        normalized_kind = "stream" if kind == "stream" else "lightweight"
        specific = self._stream if normalized_kind == "stream" else self._lightweight
        specific_message = (
            "当前模型流式会话较多，请稍后重试"
            if normalized_kind == "stream"
            else "当前模型轻量请求较多，请稍后重试"
        )

        await self._reserve_user_slot(user_id)
        acquired_global = False
        acquired_specific = False
        try:
            await self._acquire(self._global, "当前模型服务繁忙，请稍后重试")
            acquired_global = True
            await self._acquire(specific, specific_message)
            acquired_specific = True
            yield
        finally:
            if acquired_specific:
                specific.release()
            if acquired_global:
                self._global.release()
            await self._release_user_slot(user_id)


class ConversationGenerationRegistry:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = asyncio.Lock()

    async def try_acquire(self, conversation_id: str | None) -> bool:
        normalized = (conversation_id or "").strip()
        if not normalized:
            return True
        async with self._lock:
            if normalized in self._active:
                return False
            self._active.add(normalized)
            return True

    async def release(self, conversation_id: str | None) -> None:
        normalized = (conversation_id or "").strip()
        if not normalized:
            return
        async with self._lock:
            self._active.discard(normalized)


class AttachmentParseController:
    def __init__(
        self,
        *,
        total_limit: int,
        ingest_limit: int,
        fast_timeout_ms: int,
        ingest_timeout_ms: int,
    ) -> None:
        self._total = asyncio.Semaphore(total_limit)
        self._ingest = asyncio.Semaphore(ingest_limit)
        self._fast_timeout_s = max(fast_timeout_ms, 1) / 1000.0
        self._ingest_timeout_s = max(ingest_timeout_ms, 1) / 1000.0

    async def _acquire(self, semaphore: asyncio.Semaphore, timeout_s: float, message: str) -> None:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise AttachmentParseBusyError(message) from exc

    @asynccontextmanager
    async def acquire(self, *, mode: str):
        normalized_mode = mode.strip().lower() or "fast"
        timeout_s = self._fast_timeout_s if normalized_mode == "fast" else self._ingest_timeout_s
        acquired_total = False
        acquired_ingest = False
        try:
            await self._acquire(
                self._total,
                timeout_s,
                "当前附件解析任务较多，请稍后再试",
            )
            acquired_total = True
            if normalized_mode != "fast":
                await self._acquire(
                    self._ingest,
                    timeout_s,
                    "当前重型文档解析任务较多，请稍后再试",
                )
                acquired_ingest = True
            yield
        finally:
            if acquired_ingest:
                self._ingest.release()
            if acquired_total:
                self._total.release()


runtime_limits = load_runtime_limits()

llm_concurrency_controller = LLMConcurrencyController(
    global_limit=runtime_limits.llm_global_concurrency,
    stream_limit=runtime_limits.llm_stream_concurrency,
    lightweight_limit=runtime_limits.llm_lightweight_concurrency,
    per_user_limit=runtime_limits.llm_per_user_concurrency,
    acquire_timeout_ms=runtime_limits.llm_slot_acquire_timeout_ms,
)

conversation_generation_registry = ConversationGenerationRegistry()

attachment_parse_controller = AttachmentParseController(
    total_limit=runtime_limits.attachment_parse_concurrency,
    ingest_limit=runtime_limits.attachment_ingest_concurrency,
    fast_timeout_ms=runtime_limits.attachment_fast_acquire_timeout_ms,
    ingest_timeout_ms=runtime_limits.attachment_ingest_acquire_timeout_ms,
)
