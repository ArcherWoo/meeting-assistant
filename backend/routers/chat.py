"""
聊天路由 - 处理 LLM 对话请求
支持流式 SSE 响应，兼容 OpenAI 协议
"""
import json
import logging
import re
from typing import AsyncGenerator, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.llm_service import LLMService
from services.storage import storage
from services.context_assembler import context_assembler, AssembledContext
from services.embedding_service import embedding_service
from services.prompt_template_service import DEFAULT_SYSTEM_PROMPTS

logger = logging.getLogger(__name__)

router = APIRouter()
llm_service = LLMService()

_ATTACHMENT_SEPARATOR = "\n\n---\n📎 附件"


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

class ChatMessage(BaseModel):
    """单条消息"""
    role: str  # system / user / assistant / tool
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    messages: list[ChatMessage]
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True
    # LLM 配置（前端传入，避免后端存储敏感信息）
    api_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    # 当前交互模式（用于注入 System Prompt）
    mode: str = ""
    # 单独给 RAG 检索使用的纯净查询，避免附件全文污染召回
    rag_query: str = ""


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
    model: str = "gpt-4o"


async def _build_messages(request: ChatRequest) -> list[dict]:
    """构建发送给 LLM 的消息列表（纯消息构建，不含 RAG 逻辑）"""
    messages = [m.model_dump() for m in request.messages]

    # 若消息列表中已有 system 消息则不再注入
    has_system = any(m["role"] == "system" for m in messages)
    if has_system or not request.mode:
        return messages

    # 从数据库获取自定义 System Prompt；未设置时回退到角色默认值或旧内置默认值
    custom_prompt = await storage.get_setting(f"system_prompt_{request.mode}", default="")
    if custom_prompt.strip():
        base_prompt = custom_prompt.strip()
    else:
        role = await storage.get_role(request.mode)
        if role and role.get("system_prompt"):
            base_prompt = role["system_prompt"]
        else:
            base_prompt = DEFAULT_SYSTEM_PROMPTS.get(request.mode, "")

    if base_prompt:
        messages = [{"role": "system", "content": base_prompt}] + messages
    return messages


async def _assemble_context(request: ChatRequest, messages: list[dict]) -> AssembledContext:
    """独立的上下文组装步骤，仅拥有 'rag' 能力的角色才执行 RAG 检索。"""
    if not request.mode:
        return AssembledContext()

    # 从数据库获取角色，检查是否具备 rag 能力
    import json as _json
    role = await storage.get_role(request.mode)
    if role:
        try:
            caps = _json.loads(role.get("capabilities") or "[]")
        except (ValueError, TypeError):
            caps = []
        if "rag" not in caps:
            return AssembledContext()
    else:
        # 角色不存在时降级：仅旧内置 copilot/agent 支持 RAG
        if request.mode not in {"copilot", "agent"}:
            return AssembledContext()

    # 配置 embedding 服务：优先 DB 中独立 embedding 配置，回退到 LLM API 凭证
    emb_url = await storage.get_setting("embedding_api_url")
    emb_key = await storage.get_setting("embedding_api_key")
    emb_model = await storage.get_setting("embedding_model") or "text-embedding-3-small"
    if emb_url and emb_key:
        embedding_service.configure(api_url=emb_url, api_key=emb_key, model=emb_model)
    elif not embedding_service.is_configured and request.api_url and request.api_key:
        embedding_service.configure(
            api_url=request.api_url,
            api_key=request.api_key,
            model="text-embedding-3-small",
        )

    # 取最后一条 user 消息作为回退 query；优先使用前端显式传入的 rag_query
    user_query = ""
    for m in reversed(messages):
        if m["role"] == "user":
            user_query = m["content"]
            break

    rag_query = _strip_attachment_context(request.rag_query) or _strip_attachment_context(user_query)

    if not rag_query:
        return AssembledContext()

    try:
        return await context_assembler.assemble(user_query=rag_query, mode=request.mode)
    except Exception as e:
        logger.warning(f"[RAG] 上下文组装失败，降级为无增强回答: {e}")
        return AssembledContext()


async def _stream_with_metadata(
    raw_stream: AsyncGenerator[str, None],
    ctx: AssembledContext,
    retrieved_ctx: Optional[AssembledContext] = None,
    suggested_skill: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    """包装 LLM 流式输出，在 [DONE] 之前注入 context_metadata 和 skill_suggestion 事件。"""
    raw_ctx = retrieved_ctx or ctx

    def _build_context_metadata_payload() -> dict:
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

        return payload

    def _build_skill_suggestion_payload(skill: dict) -> dict:
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

    async for chunk in raw_stream:
        if chunk.strip() == "data: [DONE]":
            # 在 [DONE] 之前注入元数据
            if ctx.has_context or raw_ctx.has_context:
                metadata = {
                    "type": "context_metadata",
                    "sources": _build_context_metadata_payload(),
                }
                yield f"data: {json.dumps(metadata, ensure_ascii=False)}\n\n"

            # 如果有匹配到的 Skill，注入推荐事件
            top_skill = suggested_skill or (raw_ctx.matched_skills[0] if raw_ctx.matched_skills else None)
            if top_skill:
                yield f"data: {json.dumps(_build_skill_suggestion_payload(top_skill), ensure_ascii=False)}\n\n"

            yield chunk
            return
        yield chunk


@router.post("/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    流式聊天接口 - SSE 格式返回 LLM 响应
    兼容 OpenAI Chat Completions API 协议
    """
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")

    messages = await _build_messages(request)

    # 独立的上下文组装步骤（仅 copilot 模式）
    assembled_ctx = await _assemble_context(request, messages)
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

    if request.stream:
        raw_stream = llm_service.stream_chat(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            api_url=request.api_url,
            api_key=request.api_key,
        )
        return StreamingResponse(
            _stream_with_metadata(
                raw_stream,
                prompt_ctx,
                assembled_ctx,
                assembled_ctx.matched_skills[0] if assembled_ctx.matched_skills else None,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        result = await llm_service.chat(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            api_url=request.api_url,
            api_key=request.api_key,
        )
        return result


@router.post("/chat/auto-title")
async def generate_auto_title(request: AutoTitleRequest):
    """
    根据前 3 轮对话内容（最多 6 条消息），调用 LLM 生成语义化中文标题（10 字以内）
    """
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")

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
        result = await llm_service.chat(
            messages=messages_for_llm,
            model=request.model,
            temperature=0.3,
            max_tokens=30,
            api_url=request.api_url,
            api_key=request.api_key,
        )
        title = llm_service.extract_text_content(result)
        title = re.sub(r'^["“”‘’\s]+|["“”‘’\s]+$', "", title).strip()
        # 截断超长标题
        if len(title) > 10:
            title = title[:10]
        if not title or title == "新对话":
            title = _fallback_auto_title(dialogue_lines)
        return {"title": title or "新对话"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"标题生成失败: {str(e)}")


@router.post("/chat/test-connection")
async def test_connection(config: ConfigUpdateRequest):
    """测试 LLM API 连接是否正常"""
    try:
        result = await llm_service.test_connection(
            api_url=config.api_url,
            api_key=config.api_key,
            model=config.model,
        )
        model_count = len(result.get("available_models", []))
        message = f"连接成功，发现 {model_count} 个可用模型" if model_count else "连接成功"
        return {"success": True, "message": message, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")
