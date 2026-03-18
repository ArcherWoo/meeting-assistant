"""
聊天路由 - 处理 LLM 对话请求
支持流式 SSE 响应，兼容 OpenAI 协议
"""
import re
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.llm_service import LLMService
from services.storage import storage
from services.context_assembler import context_assembler
from services.embedding_service import embedding_service

router = APIRouter()
llm_service = LLMService()


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

# 各模式默认 System Prompt（与 settings.py 中的 DEFAULT_PROMPTS 保持一致）
# 模式与前端 AppMode 对应：copilot / builder / agent
_DEFAULT_PROMPTS: dict[str, str] = {
    "copilot": (
        "你是一个专业的会议助手。请根据用户的问题，提供清晰、准确、有帮助的回答。"
        "回答时请保持简洁，优先给出结论，再补充细节。"
    ),
    "builder": (
        "你是一个 Skill Builder 助手，专门帮助用户创建和优化工作流技能（Skill）。"
        "请引导用户描述他们的工作场景和重复性任务，帮助他们将这些任务抽象为可执行的 Skill 模板。"
        "生成的 Skill 应使用标准 Markdown 格式，包含描述、触发条件、执行步骤和输出格式。"
    ),
    "agent": (
        "你是一个智能 Agent，能够调用各种工具和技能完成复杂任务。"
        "请分析用户的需求，选择合适的工具，并逐步执行任务。"
        "执行过程中保持透明，让用户了解每一步的进展。"
    ),
}


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
    """构建发送给 LLM 的消息列表，必要时在头部注入 System Prompt + RAG 上下文"""
    messages = [m.model_dump() for m in request.messages]

    # 若消息列表中已有 system 消息则不再注入
    has_system = any(m["role"] == "system" for m in messages)
    if has_system or not request.mode:
        return messages

    # 从数据库获取自定义 System Prompt（未设置时使用默认值）
    custom_prompt = await storage.get_setting(f"system_prompt_{request.mode}", default="")
    system_content = custom_prompt.strip() if custom_prompt.strip() else _DEFAULT_PROMPTS.get(request.mode, "")

    # ── P1: Copilot 模式下注入知识库 + Know-how 上下文 ──
    if request.mode == "copilot" and system_content:
        # 配置 embedding 服务：优先 DB 中独立 embedding 配置，回退到 LLM API 凭证
        emb_url = await storage.get_setting("embedding_api_url")
        emb_key = await storage.get_setting("embedding_api_key")
        emb_model = await storage.get_setting("embedding_model") or "text-embedding-3-small"
        if emb_url and emb_key:
            # 独立 embedding 配置存在：始终用最新配置（覆盖旧值，以便设置更改后立即生效）
            embedding_service.configure(api_url=emb_url, api_key=emb_key, model=emb_model)
        elif not embedding_service.is_configured and request.api_url and request.api_key:
            # 无独立配置时，懒初始化为 LLM API 凭证（首次请求时一次性设置）
            embedding_service.configure(
                api_url=request.api_url,
                api_key=request.api_key,
                model="text-embedding-3-small",
            )

        # 取最后一条 user 消息作为检索 query
        user_query = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user_query = m["content"]
                break

        if user_query:
            try:
                ctx = await context_assembler.assemble(
                    user_query=user_query, mode=request.mode,
                )
                if ctx.has_context:
                    system_content += ctx.to_prompt_suffix()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"[RAG] 上下文组装失败，降级为无增强回答: {e}"
                )

    if system_content:
        messages = [{"role": "system", "content": system_content}] + messages
    return messages


@router.post("/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    流式聊天接口 - SSE 格式返回 LLM 响应
    兼容 OpenAI Chat Completions API 协议
    """
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")

    messages = await _build_messages(request)

    if request.stream:
        return StreamingResponse(
            llm_service.stream_chat(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                api_url=request.api_url,
                api_key=request.api_key,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式响应
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

