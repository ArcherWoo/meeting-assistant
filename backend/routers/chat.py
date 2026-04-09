"""
聊天路由 - 处理 LLM 对话请求
支持流式 SSE 响应，兼容 OpenAI 协议
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from services.context_assembler import RetrievalTraceHandler
from services.llm_service import llm_service
from services.llm_profiles import get_runtime_llm_config
from services.storage import storage
from services.context_assembler import context_assembler, AssembledContext
from services.embedding_service import embedding_service
from services.access_control import can_access_role, is_admin
from services.retrieval_planner import RetrievalPlannerSettings
from services.role_config import resolve_chat_capabilities
from services.runtime_controls import (
    LLMConcurrencyBusyError,
    conversation_generation_registry,
    llm_concurrency_controller,
)
from services.observability import log_structured, new_request_id, publish_runtime_metrics, runtime_metrics

from services.system_prompt_defaults import DEFAULT_SYSTEM_PROMPTS
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()

_ATTACHMENT_SEPARATOR = "\n\n---\n📎 附件"


def _elapsed_ms(start: float, end: Optional[float] = None) -> int:
    return max(0, round(((end if end is not None else time.perf_counter()) - start) * 1000))


def _finalize_stream_timings(
    metrics: "ChatTimingMetrics",
    llm_started_at: float,
    request_started_at: float,
) -> None:
    if metrics.llm_total_ms is None:
        metrics.llm_total_ms = _elapsed_ms(llm_started_at)
    if metrics.end_to_end_ms is None:
        metrics.end_to_end_ms = _elapsed_ms(request_started_at)


@dataclass
class ChatTimingMetrics:
    attachment_ms: Optional[int] = None
    message_build_ms: Optional[int] = None
    retrieval_ms: Optional[int] = None
    planner_ms: Optional[int] = None
    knowledge_ms: Optional[int] = None
    knowhow_ms: Optional[int] = None
    skill_ms: Optional[int] = None
    llm_first_token_ms: Optional[int] = None
    llm_total_ms: Optional[int] = None
    end_to_end_ms: Optional[int] = None

    def to_payload(self) -> dict[str, int]:
        payload: dict[str, int] = {}
        for key in (
            "attachment_ms",
            "message_build_ms",
            "retrieval_ms",
            "planner_ms",
            "knowledge_ms",
            "knowhow_ms",
            "skill_ms",
            "llm_first_token_ms",
            "llm_total_ms",
            "end_to_end_ms",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


@dataclass
class RetrievalTimingTrace(RetrievalTraceHandler):
    _step_counter: int = 0
    _step_starts: dict[int, tuple[str, float]] = field(default_factory=dict)
    step_durations_ms: dict[str, int] = field(default_factory=dict)

    async def on_stage_start(
        self,
        step_key: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        self._step_counter += 1
        self._step_starts[self._step_counter] = (step_key, time.perf_counter())
        return self._step_counter

    async def on_stage_complete(
        self,
        step_index: int,
        step_key: str,
        result: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._store_duration(step_index, step_key)

    async def on_stage_error(
        self,
        step_index: int,
        step_key: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._store_duration(step_index, step_key)

    def _store_duration(self, step_index: int, step_key: str) -> None:
        _, started_at = self._step_starts.pop(step_index, (step_key, time.perf_counter()))
        self.step_durations_ms[step_key] = _elapsed_ms(started_at)

    def apply_to_metrics(self, metrics: ChatTimingMetrics) -> None:
        key_map = {
            "planner": "planner_ms",
            "retrieve_knowledge": "knowledge_ms",
            "retrieve_knowhow": "knowhow_ms",
            "retrieve_skill": "skill_ms",
        }
        for step_key, metric_name in key_map.items():
            duration = self.step_durations_ms.get(step_key)
            if duration is not None:
                setattr(metrics, metric_name, duration)


def _request_role_id(request: "ChatRequest") -> str:
    role_id = (request.role_id or getattr(request, "mode", "") or "").strip()
    return "executor" if role_id == "agent" else role_id


def _request_conversation_id(request: "ChatRequest") -> str:
    return (request.conversation_id or "").strip()


def _strip_attachment_context(content: str) -> str:
    """从兼容旧前端的 user 内容中剥离附件全文，避免污染检索 query。"""
    if not content:
        return ""
    return content.split(_ATTACHMENT_SEPARATOR, 1)[0].strip()


def _estimate_context_window(model: str) -> int:
    """按常见模型家族保守估算上下文窗口。"""
    model_name = (model or "").strip().lower()
    rules = [
        (("claude-3.7", "claude-3.5", "claude-3", "claude-sonnet-4"), 200_000),
        (("gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-1106", "gpt-4-0125", "o1", "o3", "gemini-1.5", "gemini-2"), 128_000),
        (("deepseek-chat", "deepseek-reasoner", "deepseek-r1"), 64_000),
        (("gpt-4-32k", "qwen-max", "qwen-plus"), 32_000),
        (("gpt-3.5-turbo", "qwen-turbo"), 16_000),
        (("gpt-4",), 8_192),
    ]
    for keywords, window in rules:
        if any(keyword in model_name for keyword in keywords):
            return window
    return 8_192


def _estimate_message_tokens(messages: list[dict]) -> int:
    """粗略估算当前消息已占用的输入 token。"""
    total = 0
    for message in messages:
        content = str(message.get("content", ""))
        total += max(1, int(len(content) * 0.6)) + 16
    return total


def _max_context_injection_tokens(context_window: int) -> int:
    """限制 RAG 注入上限，避免大窗口模型被无关上下文淹没。"""
    if context_window <= 8_192:
        return 1_000
    if context_window <= 32_000:
        return 2_500
    if context_window <= 128_000:
        return 4_000
    return 6_000


def _calculate_context_budget_chars(messages: list[dict], request: "ChatRequest") -> int:
    """根据模型窗口、已有消息长度和输出预留，计算上下文可用字符预算。"""
    context_window = _estimate_context_window(request.model)
    reserved_output_tokens = max(request.max_tokens, 512)
    message_tokens = _estimate_message_tokens(messages)
    safety_margin_tokens = 1_000

    available_input_tokens = context_window - reserved_output_tokens - message_tokens - safety_margin_tokens
    if available_input_tokens <= 0:
        return 0

    budget_tokens = min(available_input_tokens, _max_context_injection_tokens(context_window))
    return max(0, int(budget_tokens / 0.6))


def _fallback_auto_title(dialogue_lines: list[str]) -> str:
    """LLM 未返回有效标题时，基于对话内容生成保底标题。"""
    for line in dialogue_lines:
        if not line.startswith("用户："):
            continue

        text = line.removeprefix("用户：").strip()
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"^[,，.。:：;；!?！？、~\-]+", "", text)
        text = re.split(r"[，。！？；：\n]", text, maxsplit=1)[0].strip()
        if text:
            return text[:10]

    for line in dialogue_lines:
        text = re.sub(r"^(用户|助手)：", "", line).strip()
        text = re.sub(r"\s+", "", text)
        if text:
            return text[:10]

    return "新对话"


def _resolve_enabled_surfaces(role_id: str, role: Optional[dict] = None) -> set[str]:
    if not role_id:
        return set()

    if role:
        chat_capabilities = resolve_chat_capabilities(role)
        enabled_surfaces = set()
        if "auto_knowledge" in chat_capabilities:
            enabled_surfaces.add("knowledge")
        if "auto_knowhow" in chat_capabilities:
            enabled_surfaces.add("knowhow")
        if "auto_skill_suggestion" in chat_capabilities:
            enabled_surfaces.add("skill")
        return enabled_surfaces

    if role_id in {"copilot", "executor"}:
        return {"knowledge", "knowhow"}
    return set()


def _format_status_event(phase: str, label: str, detail: str = "") -> str:
    payload = {
        "type": "status",
        "phase": phase,
        "label": label,
        "detail": detail,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _has_retrieval_intent(request: "ChatRequest", messages: list[dict], enabled_surfaces: set[str]) -> bool:
    if not enabled_surfaces:
        return False

    rag_query = _strip_attachment_context(request.rag_query)
    if rag_query:
        return True

    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        return bool(_strip_attachment_context(str(message.get("content", ""))))
    return False


def _looks_like_attachment_analysis(messages: list[dict]) -> bool:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        return _ATTACHMENT_SEPARATOR in str(message.get("content", ""))
    return False


def _is_content_sse_chunk(chunk: str) -> bool:
    stripped = chunk.strip()
    if not stripped.startswith("data: "):
        return False

    data = stripped[6:].strip()
    if not data or data == "[DONE]":
        return False

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return False

    if not isinstance(payload, dict) or payload.get("type") or payload.get("stream_error"):
        return False

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return False

    first = choices[0]
    if not isinstance(first, dict):
        return False

    delta = first.get("delta")
    if not isinstance(delta, dict):
        return False

    return bool(delta.get("content"))


def _extract_usage_from_sse_chunk(chunk: str) -> dict[str, int] | None:
    stripped = chunk.strip()
    if not stripped.startswith("data: "):
        return None

    data = stripped[6:].strip()
    if not data or data == "[DONE]":
        return None

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    return {
        "prompt_tokens": max(0, int(usage.get("prompt_tokens") or 0)),
        "completion_tokens": max(0, int(usage.get("completion_tokens") or 0)),
        "total_tokens": max(0, int(usage.get("total_tokens") or 0)),
    }

class ChatMessage(BaseModel):
    """单条消息"""
    role: str  # system / user / assistant / tool
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    model_config = ConfigDict(populate_by_name=True)
    messages: list[ChatMessage]
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True
    api_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    llm_profile_id: str = ""
    role_id: str = ""
    mode: str = ""
    rag_query: str = ""
    attachment_prepare_ms: float = 0.0
    conversation_id: str = ""


class ConfigUpdateRequest(BaseModel):
    """LLM 配置更新请求"""
    api_url: str
    api_key: str
    model: str = ""


class AutoTitleRequest(BaseModel):
    """自动命名请求 - 传入前 N 条消息，返回 LLM 生成的标题"""
    messages: list[ChatMessage]
    api_url: str
    api_key: str
    llm_profile_id: str = ""
    model: str = "gpt-4o"


async def _build_messages(request: ChatRequest) -> list[dict]:
    """构建发送给 LLM 的消息列表（纯消息构建，不含 RAG 逻辑）"""
    messages = [m.model_dump() for m in request.messages]
    role_id = _request_role_id(request)

    has_system = any(m["role"] == "system" for m in messages)
    if has_system or not role_id:
        return messages

    custom_prompt = await storage.get_setting(f"system_prompt_{role_id}", default="")
    if custom_prompt.strip():
        base_prompt = custom_prompt.strip()
    else:
        role = await storage.get_role(role_id)
        if role and role.get("system_prompt"):
            base_prompt = role["system_prompt"]
        else:
            base_prompt = DEFAULT_SYSTEM_PROMPTS.get(role_id, "")

    if base_prompt:
        messages = [{"role": "system", "content": base_prompt}] + messages
    return messages


async def _assemble_context(
    request: ChatRequest,
    messages: list[dict],
    user: Optional[dict],
    role: Optional[dict] = None,
    runtime_api_url: str = "",
    runtime_api_key: str = "",
    runtime_model: str = "",
    trace_handler: RetrievalTraceHandler | None = None,
) -> AssembledContext:
    """独立的上下文组装步骤，仅 Chat 自动增强开启时才执行检索。"""
    role_id = _request_role_id(request)
    enabled_surfaces = _resolve_enabled_surfaces(role_id, role)
    if not enabled_surfaces:
        return AssembledContext()

    emb_url = await storage.get_setting("embedding_api_url")
    emb_key = await storage.get_setting("embedding_api_key")
    emb_model = await storage.get_setting("embedding_model") or "text-embedding-3-small"
    if emb_url and emb_key:
        embedding_service.configure(api_url=emb_url, api_key=emb_key, model=emb_model)
    elif not embedding_service.is_configured and runtime_api_url and runtime_api_key:
        embedding_service.configure(
            api_url=runtime_api_url,
            api_key=runtime_api_key,
            model="text-embedding-3-small",
        )

    user_query = ""
    for m in reversed(messages):
        if m["role"] == "user":
            user_query = m["content"]
            break

    rag_query = _strip_attachment_context(request.rag_query) or _strip_attachment_context(user_query)
    if not rag_query:
        return AssembledContext()

    try:
        return await context_assembler.assemble(
            user_query=rag_query,
            role_id=role_id,
            planner_settings=RetrievalPlannerSettings(
                api_url=runtime_api_url,
                api_key=runtime_api_key,
                model=runtime_model or request.model,
                user_id=str(user.get("id") or "") if user else "",
            ),
            enabled_surfaces=enabled_surfaces,
            user=user,
            trace_handler=trace_handler,
        )
    except Exception as e:
        logger.warning(f"[RAG] 上下文组装失败，降级为无增强回答: {e}")
        return AssembledContext()


def _build_context_metadata_payload(
    ctx: AssembledContext,
    retrieved_ctx: Optional[AssembledContext] = None,
    timings: Optional[dict[str, int]] = None,
) -> Optional[dict]:
    raw_ctx = retrieved_ctx or ctx
    if not (ctx.has_context or raw_ctx.has_context or timings):
        return None

    payload = ctx.to_metadata_payload()
    payload["schema_version"] = 2

    truncated = ctx != raw_ctx
    payload["truncated"] = truncated

    if truncated:
        retrieved_payload = raw_ctx.to_metadata_payload()
        payload["retrieved_summary"] = retrieved_payload["summary"]
        payload["retrieved_knowledge_count"] = retrieved_payload["knowledge_count"]
        payload["retrieved_knowhow_count"] = retrieved_payload["knowhow_count"]
        payload["retrieved_skill_count"] = retrieved_payload["skill_count"]
        payload["retrieved_citations"] = retrieved_payload["citations"]

    if timings:
        payload["timings"] = timings

    return payload


def _build_skill_suggestion_payload(skill: Optional[dict]) -> Optional[dict]:
    if not skill:
        return None
    return {
        "type": "skill_suggestion",
        "schema_version": 2,
        "skill_id": skill["skill_id"],
        "skill_name": skill["skill_name"],
        "description": skill["description"],
        "score": skill["score"],
        "confidence": skill["confidence"],
        "matched_keywords": skill.get("matched_keywords", []),
    }


async def _stream_with_metadata(
    raw_stream: AsyncGenerator[str, None],
    ctx: AssembledContext,
    retrieved_ctx: Optional[AssembledContext] = None,
    suggested_skill: Optional[dict] = None,
    timings: Optional[ChatTimingMetrics] = None,
    before_metadata: Optional[Callable[[], None]] = None,
) -> AsyncGenerator[str, None]:
    """包装 LLM 流式输出，在 [DONE] 之前注入 context_metadata 和 skill_suggestion 事件。"""
    async for chunk in raw_stream:
        if chunk.strip() == "data: [DONE]":
            if before_metadata:
                before_metadata()
            # 在 [DONE] 之前注入元数据
            context_payload = _build_context_metadata_payload(
                ctx,
                retrieved_ctx,
                timings.to_payload() if timings else None,
            )
            if context_payload:
                metadata = {
                    "type": "context_metadata",
                    "sources": context_payload,
                }
                yield f"data: {json.dumps(metadata, ensure_ascii=False)}\n\n"

            # 如果有匹配到的 Skill，注入推荐事件
            raw_ctx = retrieved_ctx or ctx
            top_skill = suggested_skill or (raw_ctx.matched_skills[0] if raw_ctx.matched_skills else None)
            skill_payload = _build_skill_suggestion_payload(top_skill)
            if skill_payload:
                yield f"data: {json.dumps(skill_payload, ensure_ascii=False)}\n\n"

            yield chunk
            return
        yield chunk


@router.post("/chat/completions")
async def chat_completions(request: ChatRequest, user: dict = Depends(get_current_user)):
    """
    流式聊天接口 - SSE 格式返回 LLM 响应
    兼容 OpenAI Chat Completions API 协议
    """
    request_id = new_request_id("chat")
    user_id = str(user.get("id") or "")
    llm_config = await get_runtime_llm_config(
        profile_id=request.llm_profile_id,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
    )
    if not llm_config["api_key"]:
        raise HTTPException(status_code=400, detail="未找到可用的 LLM 配置，请先由管理员完成配置")

    role_id = _request_role_id(request)
    conversation_id = _request_conversation_id(request)
    if conversation_id:
        conversation_owner_id = await storage.get_conversation_owner_id(conversation_id)
        if not conversation_owner_id:
            raise HTTPException(status_code=404, detail="对话不存在")
        if conversation_owner_id != user.get("id"):
            raise HTTPException(status_code=403, detail="无权访问该对话")
    role: Optional[dict] = None
    if role_id:
        role = await storage.get_role(role_id)
        if role and not await can_access_role(role, user):
            raise HTTPException(status_code=403, detail="无权使用该角色")
        if not role and role_id not in DEFAULT_SYSTEM_PROMPTS:
            raise HTTPException(status_code=400, detail="角色不存在")

    if request.stream:
        if conversation_id and not await conversation_generation_registry.try_acquire(conversation_id):
            runtime_metrics.record_chat_rejection(reason="conversation_busy")
            await publish_runtime_metrics()
            log_structured(
                logger,
                "warning",
                "chat.request.rejected",
                request_id=request_id,
                reason="conversation_busy",
                user_id=user_id,
                conversation_id=conversation_id,
                role_id=role_id,
                stream=True,
            )
            raise HTTPException(status_code=409, detail="当前对话已有回答在生成中，请稍候或先停止当前生成")

        try:
            stream_slot_cm = llm_concurrency_controller.acquire(
                kind="stream",
                user_id=user_id,
            )
            await stream_slot_cm.__aenter__()
        except LLMConcurrencyBusyError as exc:
            if conversation_id:
                await conversation_generation_registry.release(conversation_id)
            runtime_metrics.record_chat_rejection(reason="llm_busy")
            await publish_runtime_metrics()
            log_structured(
                logger,
                "warning",
                "chat.request.rejected",
                request_id=request_id,
                reason="llm_busy",
                user_id=user_id,
                conversation_id=conversation_id,
                role_id=role_id,
                stream=True,
            )
            raise HTTPException(status_code=429, detail=str(exc)) from exc

        runtime_metrics.record_chat_started(stream=True)
        await publish_runtime_metrics()
        log_structured(
            logger,
            "info",
            "chat.request.started",
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            role_id=role_id,
            llm_profile_id=str(llm_config.get("profile_id") or ""),
            llm_model=llm_config["model"],
            stream=True,
        )

        async def event_stream() -> AsyncGenerator[str, None]:
            status = "completed"
            error_type = ""
            llm_started_at: float | None = None
            usage_metrics: dict[str, int] | None = None
            timing_metrics = ChatTimingMetrics(
                attachment_ms=max(1, round(request.attachment_prepare_ms))
                if request.attachment_prepare_ms > 0
                else None,
            )
            try:
                request_started_at = time.perf_counter()
                message_build_started_at = time.perf_counter()
                messages = await _build_messages(request)
                timing_metrics.message_build_ms = _elapsed_ms(message_build_started_at)
                enabled_surfaces = _resolve_enabled_surfaces(role_id, role)
                should_retrieve = _has_retrieval_intent(request, messages, enabled_surfaces)
                attachment_analysis = _looks_like_attachment_analysis(messages)

                yield _format_status_event("queued", "已收到请求", "正在准备消息")

                assembled_ctx = AssembledContext()
                prompt_ctx = AssembledContext()

                if should_retrieve:
                    retrieval_trace = RetrievalTimingTrace()
                    retrieval_started_at = time.perf_counter()
                    detail = "正在检索相关知识和规则"
                    if attachment_analysis:
                        detail = "正在整理附件问题并检索相关上下文"
                    yield _format_status_event("retrieving", "正在准备上下文", detail)
                    assembled_ctx = await _assemble_context(
                        request,
                        messages,
                        user,
                        role,
                        runtime_api_url=llm_config["api_url"],
                        runtime_api_key=llm_config["api_key"],
                        runtime_model=llm_config["model"],
                        trace_handler=retrieval_trace,
                    )
                    timing_metrics.retrieval_ms = _elapsed_ms(retrieval_started_at)
                    retrieval_trace.apply_to_metrics(timing_metrics)

                    if assembled_ctx.has_context:
                        fitted_ctx = assembled_ctx.fit_to_budget(_calculate_context_budget_chars(messages, request))
                        if fitted_ctx.has_context:
                            suffix = fitted_ctx.to_prompt_suffix()
                            if messages and messages[0]["role"] == "system":
                                messages[0]["content"] += f"\n\n{suffix}"
                            else:
                                messages = [{"role": "system", "content": suffix}] + messages
                            prompt_ctx = fitted_ctx

                connect_detail = "模型开始输出后会立即显示"
                if attachment_analysis:
                    connect_detail = "附件内容较长时，首字可能仍需几秒，请稍候"
                yield _format_status_event("calling_model", "正在请求模型", connect_detail)

                llm_started_at = time.perf_counter()
                raw_stream = llm_service.stream_chat(
                    messages=messages,
                    model=llm_config["model"],
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    api_url=llm_config["api_url"],
                    api_key=llm_config["api_key"],
                    user_id=user_id,
                    _skip_limits=True,
                )
                has_emitted_streaming = False
                async for chunk in _stream_with_metadata(
                    raw_stream,
                    prompt_ctx,
                    assembled_ctx,
                    assembled_ctx.matched_skills[0] if assembled_ctx.matched_skills else None,
                    timing_metrics,
                    lambda: _finalize_stream_timings(timing_metrics, llm_started_at, request_started_at),
                ):
                    usage = _extract_usage_from_sse_chunk(chunk)
                    if usage:
                        usage_metrics = usage
                    if not has_emitted_streaming and _is_content_sse_chunk(chunk):
                        has_emitted_streaming = True
                        timing_metrics.llm_first_token_ms = _elapsed_ms(llm_started_at)
                        yield _format_status_event("streaming", "正在生成回答", "回答已开始输出")
                    yield chunk
            except LLMConcurrencyBusyError as exc:
                status = "failed"
                error_type = type(exc).__name__
                error_payload = json.dumps({"stream_error": str(exc)}, ensure_ascii=False)
                yield f"data: {error_payload}\n\n"
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error_type = type(exc).__name__
                log_structured(
                    logger,
                    "exception",
                    "chat.request.failed",
                    request_id=request_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role_id=role_id,
                    llm_profile_id=str(llm_config.get("profile_id") or ""),
                    llm_model=llm_config["model"],
                    stream=True,
                    error_type=error_type,
                    error=str(exc),
                )
                error_payload = json.dumps({"stream_error": str(exc)}, ensure_ascii=False)
                yield f"data: {error_payload}\n\n"
            finally:
                if usage_metrics:
                    await storage.record_user_token_usage(
                        user_id,
                        token_input=usage_metrics.get("prompt_tokens", 0),
                        token_output=usage_metrics.get("completion_tokens", 0),
                    )
                if llm_started_at is not None:
                    _finalize_stream_timings(timing_metrics, llm_started_at, request_started_at)
                elif timing_metrics.end_to_end_ms is None:
                    timing_metrics.end_to_end_ms = _elapsed_ms(request_started_at)
                runtime_metrics.record_chat_finished(
                    status=status,
                    timings=timing_metrics.to_payload(),
                )
                await publish_runtime_metrics(force=True)
                log_structured(
                    logger,
                    "info" if status == "completed" else "warning",
                    "chat.request.completed" if status == "completed" else "chat.request.failed",
                    request_id=request_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role_id=role_id,
                    llm_profile_id=str(llm_config.get("profile_id") or ""),
                    llm_model=llm_config["model"],
                    stream=True,
                    status=status,
                    error_type=error_type,
                    timings=timing_metrics.to_payload(),
                )
                if conversation_id:
                    await conversation_generation_registry.release(conversation_id)
                await stream_slot_cm.__aexit__(None, None, None)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Request-ID": request_id,
            },
        )
    else:
        if conversation_id and not await conversation_generation_registry.try_acquire(conversation_id):
            runtime_metrics.record_chat_rejection(reason="conversation_busy")
            await publish_runtime_metrics()
            log_structured(
                logger,
                "warning",
                "chat.request.rejected",
                request_id=request_id,
                reason="conversation_busy",
                user_id=user_id,
                conversation_id=conversation_id,
                role_id=role_id,
                stream=False,
            )
            raise HTTPException(status_code=409, detail="当前对话已有回答在生成中，请稍候或先停止当前生成")
        runtime_metrics.record_chat_started(stream=False)
        await publish_runtime_metrics()
        log_structured(
            logger,
            "info",
            "chat.request.started",
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            role_id=role_id,
            llm_profile_id=str(llm_config.get("profile_id") or ""),
            llm_model=llm_config["model"],
            stream=False,
        )
        status = "completed"
        error_type = ""
        timing_metrics = ChatTimingMetrics(
            attachment_ms=max(1, round(request.attachment_prepare_ms))
            if request.attachment_prepare_ms > 0
            else None,
        )
        try:
            request_started_at = time.perf_counter()
            message_build_started_at = time.perf_counter()
            messages = await _build_messages(request)
            timing_metrics.message_build_ms = _elapsed_ms(message_build_started_at)

            enabled_surfaces = _resolve_enabled_surfaces(role_id, role)
            should_retrieve = _has_retrieval_intent(request, messages, enabled_surfaces)

            assembled_ctx = AssembledContext()
            if should_retrieve:
                retrieval_trace = RetrievalTimingTrace()
                retrieval_started_at = time.perf_counter()
                assembled_ctx = await _assemble_context(
                    request,
                    messages,
                    user,
                    role,
                    runtime_api_url=llm_config["api_url"],
                    runtime_api_key=llm_config["api_key"],
                    runtime_model=llm_config["model"],
                    trace_handler=retrieval_trace,
                )
                timing_metrics.retrieval_ms = _elapsed_ms(retrieval_started_at)
                retrieval_trace.apply_to_metrics(timing_metrics)

            prompt_ctx = AssembledContext()

            if assembled_ctx.has_context:
                fitted_ctx = assembled_ctx.fit_to_budget(_calculate_context_budget_chars(messages, request))
                if fitted_ctx.has_context:
                    suffix = fitted_ctx.to_prompt_suffix()
                    if messages and messages[0]["role"] == "system":
                        messages[0]["content"] += f"\n\n{suffix}"
                    else:
                        messages = [{"role": "system", "content": suffix}] + messages
                    prompt_ctx = fitted_ctx

            llm_started_at = time.perf_counter()
            result = await llm_service.chat(
                messages=messages,
                model=llm_config["model"],
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                api_url=llm_config["api_url"],
                api_key=llm_config["api_key"],
                user_id=user_id,
                request_kind="stream",
            )
            usage = result.get("usage") if isinstance(result, dict) else None
            if isinstance(usage, dict):
                await storage.record_user_token_usage(
                    user_id,
                    token_input=max(0, int(usage.get("prompt_tokens") or 0)),
                    token_output=max(0, int(usage.get("completion_tokens") or 0)),
                )
            timing_metrics.llm_total_ms = _elapsed_ms(llm_started_at)
            timing_metrics.end_to_end_ms = _elapsed_ms(request_started_at)
            response = dict(result)
            response["request_id"] = request_id
            context_payload = _build_context_metadata_payload(
                prompt_ctx,
                assembled_ctx,
                timing_metrics.to_payload(),
            )
            if context_payload:
                response["context_metadata"] = context_payload
            top_skill = assembled_ctx.matched_skills[0] if assembled_ctx.matched_skills else None
            skill_payload = _build_skill_suggestion_payload(top_skill)
            if skill_payload:
                response["skill_suggestion"] = skill_payload
            return response
        except LLMConcurrencyBusyError as exc:
            status = "failed"
            error_type = type(exc).__name__
            runtime_metrics.record_chat_rejection(reason="llm_busy")
            await publish_runtime_metrics()
            log_structured(
                logger,
                "warning",
                "chat.request.rejected",
                request_id=request_id,
                reason="llm_busy",
                user_id=user_id,
                conversation_id=conversation_id,
                role_id=role_id,
                stream=False,
            )
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except Exception as exc:
            status = "failed"
            error_type = type(exc).__name__
            log_structured(
                logger,
                "exception",
                "chat.request.failed",
                request_id=request_id,
                user_id=user_id,
                conversation_id=conversation_id,
                role_id=role_id,
                llm_profile_id=str(llm_config.get("profile_id") or ""),
                llm_model=llm_config["model"],
                stream=False,
                error_type=error_type,
                error=str(exc),
            )
            raise
        finally:
            runtime_metrics.record_chat_finished(
                status=status,
                timings=timing_metrics.to_payload(),
            )
            await publish_runtime_metrics(force=True)
            log_structured(
                logger,
                "info" if status == "completed" else "warning",
                "chat.request.completed" if status == "completed" else "chat.request.failed",
                request_id=request_id,
                user_id=user_id,
                conversation_id=conversation_id,
                role_id=role_id,
                llm_profile_id=str(llm_config.get("profile_id") or ""),
                llm_model=llm_config["model"],
                stream=False,
                status=status,
                error_type=error_type,
                timings=timing_metrics.to_payload(),
            )
            if conversation_id:
                await conversation_generation_registry.release(conversation_id)


@router.post("/chat/auto-title")
async def generate_auto_title(request: AutoTitleRequest, user: dict = Depends(get_current_user)):
    """
    根据前 3 轮对话内容（最多 6 条消息），调用 LLM 生成语义化中文标题（10 字以内）
    """
    request_id = new_request_id("autotitle")
    user_id = str(user.get("id") or "")
    llm_config = await get_runtime_llm_config(
        profile_id=request.llm_profile_id,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
    )
    if not llm_config["api_key"]:
        raise HTTPException(status_code=400, detail="未找到可用的 LLM 配置，请先由管理员完成配置")

    # 仅使用前 6 条 user/assistant 消息，每条内容截取前 300 字避免 prompt 过长
    dialogue_lines = []
    for m in request.messages[:6]:
        if m.role not in ("user", "assistant"):
            continue
        label = "用户" if m.role == "user" else "助手"
        dialogue_lines.append(f"{label}：{m.content[:300]}")

    if not dialogue_lines:
        return {"title": "新对话"}

    dialogue_text = "\n".join(dialogue_lines)
    system_prompt = (
        "你是一个对话标题生成器。根据用户提供的对话内容，生成一个简短的中文标题。"
        "要求：①10字以内；②概括对话核心主题或意图；③只输出标题本身，不要引号、序号或任何解释。"
    )
    messages_for_llm = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请为以下对话生成标题：\n\n{dialogue_text}"},
    ]

    try:
        log_structured(
            logger,
            "info",
            "chat.auto_title.started",
            request_id=request_id,
            user_id=user_id,
            llm_profile_id=str(llm_config.get("profile_id") or ""),
            llm_model=llm_config["model"],
        )
        result = await llm_service.chat(
            messages=messages_for_llm,
            model=llm_config["model"],
            temperature=0.3,
            max_tokens=30,
            api_url=llm_config["api_url"],
            api_key=llm_config["api_key"],
            user_id=user_id,
        )
        title = llm_service.extract_text_content(result)
        title = re.sub(r'^["“”‘’\s]+|["“”‘’\s]+$', "", title).strip()
        # 截断超长标题
        if len(title) > 10:
            title = title[:10]
        if not title or title == "新对话":
            title = _fallback_auto_title(dialogue_lines)
        resolved_title = title or "新对话"
        log_structured(
            logger,
            "info",
            "chat.auto_title.completed",
            request_id=request_id,
            user_id=user_id,
            llm_profile_id=str(llm_config.get("profile_id") or ""),
            llm_model=llm_config["model"],
            title=resolved_title,
        )
        return {"title": resolved_title, "request_id": request_id}
    except LLMConcurrencyBusyError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except Exception as e:
        log_structured(
            logger,
            "exception",
            "chat.auto_title.failed",
            request_id=request_id,
            user_id=user_id,
            llm_profile_id=str(llm_config.get("profile_id") or ""),
            llm_model=llm_config["model"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"标题生成失败: {str(e)}")


@router.post("/chat/test-connection")
async def test_connection(config: ConfigUpdateRequest, user: dict = Depends(get_current_user)):
    """测试 LLM API 连接是否正常"""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可以测试 LLM 连接")
    request_id = new_request_id("llmtest")
    try:
        log_structured(
            logger,
            "info",
            "chat.test_connection.started",
            request_id=request_id,
            user_id=str(user.get("id") or ""),
            api_url=config.api_url,
            model=config.model,
        )
        result = await llm_service.test_connection(
            api_url=config.api_url,
            api_key=config.api_key,
            model=config.model,
            user_id=str(user.get("id") or ""),
        )
        model_count = len(result.get("available_models", []))
        message = f"连接成功，发现 {model_count} 个可用模型" if model_count else "连接成功"
        log_structured(
            logger,
            "info",
            "chat.test_connection.completed",
            request_id=request_id,
            user_id=str(user.get("id") or ""),
            api_url=config.api_url,
            model=result.get("model") or config.model,
            available_model_count=model_count,
            fallback=result.get("fallback", False),
        )
        return {"success": True, "message": message, "request_id": request_id, **result}
    except LLMConcurrencyBusyError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except Exception as e:
        log_structured(
            logger,
            "exception",
            "chat.test_connection.failed",
            request_id=request_id,
            user_id=str(user.get("id") or ""),
            api_url=config.api_url,
            model=config.model,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")
