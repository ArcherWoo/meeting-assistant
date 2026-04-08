from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _str_env(name: str, default: str) -> str:
    raw = os.getenv(name, "").strip()
    return raw or default


@dataclass(frozen=True)
class RuntimeLimitConfig:
    coordination_backend: str
    llm_global_concurrency: int
    llm_stream_concurrency: int
    llm_lightweight_concurrency: int
    llm_per_user_concurrency: int
    llm_slot_acquire_timeout_ms: int
    llm_lease_ttl_ms: int
    llm_http_max_connections: int
    llm_http_max_keepalive_connections: int
    llm_http_keepalive_expiry_sec: int
    conversation_lock_ttl_ms: int
    attachment_parse_concurrency: int
    attachment_ingest_concurrency: int
    attachment_fast_acquire_timeout_ms: int
    attachment_ingest_acquire_timeout_ms: int
    attachment_lease_ttl_ms: int


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
        coordination_backend=_str_env("MEETING_ASSISTANT_RUNTIME_COORDINATION", "memory").lower(),
        llm_global_concurrency=llm_global,
        llm_stream_concurrency=llm_stream,
        llm_lightweight_concurrency=llm_lightweight,
        llm_per_user_concurrency=_int_env("MEETING_ASSISTANT_LLM_PER_USER_CONCURRENCY", 3),
        llm_slot_acquire_timeout_ms=_int_env("MEETING_ASSISTANT_LLM_SLOT_ACQUIRE_TIMEOUT_MS", 1500),
        llm_lease_ttl_ms=_int_env("MEETING_ASSISTANT_LLM_LEASE_TTL_MS", 600000),
        llm_http_max_connections=_int_env("MEETING_ASSISTANT_LLM_HTTP_MAX_CONNECTIONS", 40),
        llm_http_max_keepalive_connections=_int_env("MEETING_ASSISTANT_LLM_HTTP_MAX_KEEPALIVE_CONNECTIONS", 20),
        llm_http_keepalive_expiry_sec=_int_env("MEETING_ASSISTANT_LLM_HTTP_KEEPALIVE_EXPIRY_SEC", 45),
        conversation_lock_ttl_ms=_int_env("MEETING_ASSISTANT_CONVERSATION_LOCK_TTL_MS", 1800000),
        attachment_parse_concurrency=attachment_total,
        attachment_ingest_concurrency=attachment_ingest,
        attachment_fast_acquire_timeout_ms=_int_env("MEETING_ASSISTANT_ATTACHMENT_FAST_TIMEOUT_MS", 8000),
        attachment_ingest_acquire_timeout_ms=_int_env("MEETING_ASSISTANT_ATTACHMENT_INGEST_TIMEOUT_MS", 20000),
        attachment_lease_ttl_ms=_int_env("MEETING_ASSISTANT_ATTACHMENT_LEASE_TTL_MS", 900000),
    )


class ServiceBusyError(RuntimeError):
    """Base exception for bounded runtime resources."""


class LLMConcurrencyBusyError(ServiceBusyError):
    """Raised when LLM slots are exhausted."""


class ConversationBusyError(ServiceBusyError):
    """Raised when the same conversation is already generating."""


class AttachmentParseBusyError(ServiceBusyError):
    """Raised when attachment parsing slots are exhausted."""


class _StorageBackedControllerMixin:
    def __init__(self, *, storage_service=None, backend: str = "memory") -> None:
        self._backend = backend
        self._storage_service = storage_service

    @property
    def _uses_storage(self) -> bool:
        return self._backend == "sqlite"

    def _storage(self):
        if self._storage_service is not None:
            return self._storage_service
        from services.storage import storage

        return storage


class LLMConcurrencyController(_StorageBackedControllerMixin):
    def __init__(
        self,
        *,
        global_limit: int,
        stream_limit: int,
        lightweight_limit: int,
        per_user_limit: int,
        acquire_timeout_ms: int,
        backend: str = "memory",
        storage_service=None,
        lease_ttl_ms: int = 600000,
    ) -> None:
        super().__init__(storage_service=storage_service, backend=backend)
        self._global_limit = global_limit
        self._stream_limit = stream_limit
        self._lightweight_limit = lightweight_limit
        self._per_user_limit = per_user_limit
        self._lease_ttl_ms = lease_ttl_ms
        self._acquire_timeout_s = max(acquire_timeout_ms, 1) / 1000.0
        self._global = asyncio.Semaphore(global_limit)
        self._stream = asyncio.Semaphore(stream_limit)
        self._lightweight = asyncio.Semaphore(lightweight_limit)
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

    async def _acquire_storage_group(self, *, kind: str, user_id: str | None = None) -> str:
        normalized_kind = "stream" if kind == "stream" else "lightweight"
        specific_message = (
            "当前模型流式会话较多，请稍后重试"
            if normalized_kind == "stream"
            else "当前模型轻量请求较多，请稍后重试"
        )

        requirements = [
            {"lease_type": "llm_global", "resource_id": "", "limit": self._global_limit},
            {
                "lease_type": "llm_stream" if normalized_kind == "stream" else "llm_lightweight",
                "resource_id": "",
                "limit": self._stream_limit if normalized_kind == "stream" else self._lightweight_limit,
            },
        ]
        normalized_user = (user_id or "").strip()
        if normalized_user:
            requirements.append(
                {
                    "lease_type": "llm_user",
                    "resource_id": normalized_user,
                    "limit": self._per_user_limit,
                }
            )

        lease_group_id = await self._storage().try_acquire_runtime_lease_group(
            requirements,
            ttl_ms=self._lease_ttl_ms,
            owner_id=normalized_user,
        )
        if lease_group_id:
            return lease_group_id

        if normalized_user:
            user_count = await self._storage().count_runtime_leases("llm_user", resource_id=normalized_user)
            if user_count >= self._per_user_limit:
                raise LLMConcurrencyBusyError("当前账号的模型并发请求过多，请稍后再试")
        specific_type = "llm_stream" if normalized_kind == "stream" else "llm_lightweight"
        specific_count = await self._storage().count_runtime_leases(specific_type)
        specific_limit = self._stream_limit if normalized_kind == "stream" else self._lightweight_limit
        if specific_count >= specific_limit:
            raise LLMConcurrencyBusyError(specific_message)
        raise LLMConcurrencyBusyError("当前模型服务繁忙，请稍后重试")

    @asynccontextmanager
    async def acquire(self, *, kind: str, user_id: str | None = None):
        if self._uses_storage:
            lease_group_id = await self._acquire_storage_group(kind=kind, user_id=user_id)
            try:
                yield
            finally:
                await self._storage().release_runtime_lease_group(lease_group_id)
            return

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

    async def snapshot_async(self) -> dict[str, object]:
        if not self._uses_storage:
            return self.snapshot()

        global_in_use = await self._storage().count_runtime_leases("llm_global")
        stream_in_use = await self._storage().count_runtime_leases("llm_stream")
        lightweight_in_use = await self._storage().count_runtime_leases("llm_lightweight")
        return {
            "backend": self._backend,
            "global_limit": self._global_limit,
            "global_in_use": global_in_use,
            "global_available": max(0, self._global_limit - global_in_use),
            "stream_limit": self._stream_limit,
            "stream_in_use": stream_in_use,
            "stream_available": max(0, self._stream_limit - stream_in_use),
            "lightweight_limit": self._lightweight_limit,
            "lightweight_in_use": lightweight_in_use,
            "lightweight_available": max(0, self._lightweight_limit - lightweight_in_use),
            "per_user_limit": self._per_user_limit,
            "active_users": len(await self._storage().list_runtime_lease_resources("llm_user")),
        }

    def snapshot(self) -> dict[str, object]:
        if self._uses_storage:
            return {
                "backend": self._backend,
                "global_limit": self._global_limit,
                "stream_limit": self._stream_limit,
                "lightweight_limit": self._lightweight_limit,
                "per_user_limit": self._per_user_limit,
                "scope": "cluster",
            }

        global_available = int(getattr(self._global, "_value", 0))
        stream_available = int(getattr(self._stream, "_value", 0))
        lightweight_available = int(getattr(self._lightweight, "_value", 0))
        return {
            "backend": self._backend,
            "global_limit": self._global_limit,
            "global_in_use": max(0, self._global_limit - global_available),
            "global_available": max(0, global_available),
            "stream_limit": self._stream_limit,
            "stream_in_use": max(0, self._stream_limit - stream_available),
            "stream_available": max(0, stream_available),
            "lightweight_limit": self._lightweight_limit,
            "lightweight_in_use": max(0, self._lightweight_limit - lightweight_available),
            "lightweight_available": max(0, lightweight_available),
            "per_user_limit": self._per_user_limit,
            "active_users": len(self._user_counts),
            "user_counts": dict(self._user_counts),
        }


class ConversationGenerationRegistry(_StorageBackedControllerMixin):
    def __init__(
        self,
        *,
        backend: str = "memory",
        storage_service=None,
        lock_ttl_ms: int = 1800000,
    ) -> None:
        super().__init__(storage_service=storage_service, backend=backend)
        self._lock_ttl_ms = lock_ttl_ms
        self._active: set[str] = set()
        self._lease_groups: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def try_acquire(self, conversation_id: str | None) -> bool:
        normalized = (conversation_id or "").strip()
        if not normalized:
            return True

        if self._uses_storage:
            lease_group_id = await self._storage().try_acquire_runtime_lease_group(
                [
                    {
                        "lease_type": "conversation_generation",
                        "resource_id": normalized,
                        "limit": 1,
                    }
                ],
                ttl_ms=self._lock_ttl_ms,
                owner_id=normalized,
            )
            if not lease_group_id:
                return False
            async with self._lock:
                self._lease_groups[normalized] = lease_group_id
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

        if self._uses_storage:
            async with self._lock:
                lease_group_id = self._lease_groups.pop(normalized, "")
            if lease_group_id:
                await self._storage().release_runtime_lease_group(lease_group_id)
            return

        async with self._lock:
            self._active.discard(normalized)

    async def snapshot_async(self) -> dict[str, object]:
        if not self._uses_storage:
            return self.snapshot()
        active_ids = await self._storage().list_runtime_lease_resources("conversation_generation")
        return {
            "backend": self._backend,
            "active_count": len(active_ids),
            "active_conversation_ids": active_ids,
        }

    def snapshot(self) -> dict[str, object]:
        if self._uses_storage:
            return {
                "backend": self._backend,
                "scope": "cluster",
            }
        active_ids = sorted(self._active)
        return {
            "backend": self._backend,
            "active_count": len(active_ids),
            "active_conversation_ids": active_ids,
        }


class AttachmentParseController(_StorageBackedControllerMixin):
    def __init__(
        self,
        *,
        total_limit: int,
        ingest_limit: int,
        fast_timeout_ms: int,
        ingest_timeout_ms: int,
        backend: str = "memory",
        storage_service=None,
        lease_ttl_ms: int = 900000,
    ) -> None:
        super().__init__(storage_service=storage_service, backend=backend)
        self._total_limit = total_limit
        self._ingest_limit = ingest_limit
        self._lease_ttl_ms = lease_ttl_ms
        self._total = asyncio.Semaphore(total_limit)
        self._ingest = asyncio.Semaphore(ingest_limit)
        self._fast_timeout_s = max(fast_timeout_ms, 1) / 1000.0
        self._ingest_timeout_s = max(ingest_timeout_ms, 1) / 1000.0

    async def _acquire(self, semaphore: asyncio.Semaphore, timeout_s: float, message: str) -> None:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            raise AttachmentParseBusyError(message) from exc

    async def _acquire_storage_group(self, *, mode: str) -> str:
        normalized_mode = mode.strip().lower() or "fast"
        requirements = [
            {"lease_type": "attachment_total", "resource_id": "", "limit": self._total_limit},
        ]
        if normalized_mode != "fast":
            requirements.append(
                {"lease_type": "attachment_ingest", "resource_id": "", "limit": self._ingest_limit}
            )
        lease_group_id = await self._storage().try_acquire_runtime_lease_group(
            requirements,
            ttl_ms=self._lease_ttl_ms,
            owner_id=normalized_mode,
        )
        if lease_group_id:
            return lease_group_id

        total_in_use = await self._storage().count_runtime_leases("attachment_total")
        if total_in_use >= self._total_limit:
            raise AttachmentParseBusyError("当前附件解析任务较多，请稍后再试")
        ingest_in_use = await self._storage().count_runtime_leases("attachment_ingest")
        if normalized_mode != "fast" and ingest_in_use >= self._ingest_limit:
            raise AttachmentParseBusyError("当前重型文档解析任务较多，请稍后再试")
        raise AttachmentParseBusyError("当前附件解析任务较多，请稍后再试")

    @asynccontextmanager
    async def acquire(self, *, mode: str):
        if self._uses_storage:
            lease_group_id = await self._acquire_storage_group(mode=mode)
            try:
                yield
            finally:
                await self._storage().release_runtime_lease_group(lease_group_id)
            return

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

    async def snapshot_async(self) -> dict[str, object]:
        if not self._uses_storage:
            return self.snapshot()
        total_in_use = await self._storage().count_runtime_leases("attachment_total")
        ingest_in_use = await self._storage().count_runtime_leases("attachment_ingest")
        return {
            "backend": self._backend,
            "total_limit": self._total_limit,
            "total_in_use": total_in_use,
            "total_available": max(0, self._total_limit - total_in_use),
            "ingest_limit": self._ingest_limit,
            "ingest_in_use": ingest_in_use,
            "ingest_available": max(0, self._ingest_limit - ingest_in_use),
            "fast_timeout_ms": round(self._fast_timeout_s * 1000),
            "ingest_timeout_ms": round(self._ingest_timeout_s * 1000),
        }

    def snapshot(self) -> dict[str, object]:
        if self._uses_storage:
            return {
                "backend": self._backend,
                "total_limit": self._total_limit,
                "ingest_limit": self._ingest_limit,
                "scope": "cluster",
            }
        total_available = int(getattr(self._total, "_value", 0))
        ingest_available = int(getattr(self._ingest, "_value", 0))
        return {
            "backend": self._backend,
            "total_limit": self._total_limit,
            "total_in_use": max(0, self._total_limit - total_available),
            "total_available": max(0, total_available),
            "ingest_limit": self._ingest_limit,
            "ingest_in_use": max(0, self._ingest_limit - ingest_available),
            "ingest_available": max(0, ingest_available),
            "fast_timeout_ms": round(self._fast_timeout_s * 1000),
            "ingest_timeout_ms": round(self._ingest_timeout_s * 1000),
        }


runtime_limits = load_runtime_limits()

llm_concurrency_controller = LLMConcurrencyController(
    global_limit=runtime_limits.llm_global_concurrency,
    stream_limit=runtime_limits.llm_stream_concurrency,
    lightweight_limit=runtime_limits.llm_lightweight_concurrency,
    per_user_limit=runtime_limits.llm_per_user_concurrency,
    acquire_timeout_ms=runtime_limits.llm_slot_acquire_timeout_ms,
    backend=runtime_limits.coordination_backend,
    lease_ttl_ms=runtime_limits.llm_lease_ttl_ms,
)

conversation_generation_registry = ConversationGenerationRegistry(
    backend=runtime_limits.coordination_backend,
    lock_ttl_ms=runtime_limits.conversation_lock_ttl_ms,
)

attachment_parse_controller = AttachmentParseController(
    total_limit=runtime_limits.attachment_parse_concurrency,
    ingest_limit=runtime_limits.attachment_ingest_concurrency,
    fast_timeout_ms=runtime_limits.attachment_fast_acquire_timeout_ms,
    ingest_timeout_ms=runtime_limits.attachment_ingest_acquire_timeout_ms,
    backend=runtime_limits.coordination_backend,
    lease_ttl_ms=runtime_limits.attachment_lease_ttl_ms,
)
