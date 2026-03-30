"""
会话与消息路由
提供前端聊天所需的数据库真相源 API。
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routers.auth import get_current_user
from services.storage import storage

router = APIRouter()


class ConversationCreateRequest(BaseModel):
    role_id: str
    surface: str = "chat"
    title: str = "新对话"


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None
    surface: Optional[str] = None
    role_id: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_title_customized: Optional[bool] = None


class MessageCreateRequest(BaseModel):
    role: str
    content: str = ""
    model: str = ""
    token_input: int = 0
    token_output: int = 0
    duration_ms: int = 0
    metadata: dict = Field(default_factory=dict)


class MessageUpdateRequest(BaseModel):
    content: Optional[str] = None
    model: Optional[str] = None
    token_input: Optional[int] = None
    token_output: Optional[int] = None
    duration_ms: Optional[int] = None
    metadata: Optional[dict] = None


def _parse_string_list(raw_value) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    text = str(raw_value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


async def _ensure_role_allows_surface(role_id: str, surface: str) -> None:
    role = await storage.get_role(role_id)
    if not role:
        raise HTTPException(status_code=400, detail="角色不存在")

    allowed_surfaces = _parse_string_list(role.get("allowed_surfaces")) or ["chat"]
    if surface not in allowed_surfaces:
        raise HTTPException(status_code=400, detail=f"角色 {role_id} 不允许在 {surface} surface 下创建会话")


@router.get("/chat/state")
async def get_chat_state(user: dict = Depends(get_current_user)) -> dict:
    """一次性返回默认工作区下的所有会话与消息。"""
    workspace_id = await storage.get_default_workspace_id()
    owner_id = None if user.get("role") == "admin" else user["id"]
    conversations = await storage.list_conversations(workspace_id, owner_id=owner_id)
    messages_by_conversation: dict[str, list[dict]] = {}

    for conversation in conversations:
        msgs = await storage.list_messages(conversation["id"])

        # 后端补偿：对 agent surface 对话，注入尚未写回 messages 表的已完成 agent_run
        if conversation.get("surface") == "agent":
            # 收集已写回消息中记录的 runId，用于去重
            persisted_run_ids: set[str] = set()
            for m in msgs:
                meta = m.get("metadata") or {}
                agent_result = meta.get("agentResult") or {}
                rid = agent_result.get("runId")
                if rid:
                    persisted_run_ids.add(rid)

            # 查询该对话下所有终态 agent_run
            terminal_runs = await storage.list_agent_runs_for_conversation(conversation["id"])
            for run in terminal_runs:
                run_id = run.get("runId") or run.get("id") or ""
                if not run_id or run_id in persisted_run_ids:
                    continue
                # 构造补偿消息（结构与 _normalize_message_row 输出一致）
                final_result = run.get("finalResult") or run.get("final_result") or {}
                summary = (final_result.get("summary") or "").strip()
                raw_text = (final_result.get("raw_text") or "").strip()
                content = raw_text or summary or "（Agent 已完成执行）"
                compensation_msg = {
                    "id": f"compensated-{run_id}",
                    "conversation_id": conversation["id"],
                    "conversationId": conversation["id"],
                    "role": "assistant",
                    "content": content,
                    "model": run.get("model") or "",
                    "token_input": 0,
                    "tokenInput": 0,
                    "token_output": 0,
                    "tokenOutput": 0,
                    "duration_ms": 0,
                    "durationMs": 0,
                    "metadata": {
                        "agentResult": {
                            "runId": run_id,
                            "summary": summary,
                            "raw_text": raw_text,
                            "used_tools": final_result.get("used_tools") or [],
                            "citations": final_result.get("citations") or [],
                            "artifacts": final_result.get("artifacts") or [],
                            "next_actions": final_result.get("next_actions") or [],
                        }
                    },
                    "created_at": run.get("completedAt") or run.get("createdAt") or "",
                    "createdAt": run.get("completedAt") or run.get("createdAt") or "",
                    "_compensated": True,
                }
                msgs.append(compensation_msg)

            # 按 created_at 重新排序（补偿消息插在时间轴正确位置）
            msgs.sort(key=lambda m: m.get("created_at") or "")

        messages_by_conversation[conversation["id"]] = msgs

    return {
        "workspace_id": workspace_id,
        "conversations": conversations,
        "messages_by_conversation": messages_by_conversation,
    }


@router.post("/conversations")
async def create_conversation(request: ConversationCreateRequest, user: dict = Depends(get_current_user)) -> dict:
    role_id = request.role_id.strip()
    if not role_id:
        raise HTTPException(status_code=400, detail="角色 ID 不能为空")
    surface = (request.surface or "chat").strip() or "chat"
    if surface not in {"chat", "agent"}:
        raise HTTPException(status_code=400, detail="surface 必须是 chat 或 agent")
    await _ensure_role_allows_surface(role_id, surface)

    workspace_id = await storage.get_default_workspace_id()
    conversation = await storage.create_conversation(
        workspace_id=workspace_id,
        title=request.title.strip() or "新对话",
        surface=surface,
        role_id=role_id,
        is_title_customized=0,
        owner_id=user["id"],
    )
    return {"conversation": conversation}


@router.put("/conversations/{conversation_id}")
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest, user: dict = Depends(get_current_user)) -> dict:
    existing = await storage.get_conversation(conversation_id)
    if not existing:
        raise HTTPException(status_code=404, detail="对话不存在")

    updates: dict = {}
    if request.title is not None:
        updates["title"] = request.title.strip() or "新对话"
    if request.surface is not None:
        surface = request.surface.strip() or "chat"
        if surface not in {"chat", "agent"}:
            raise HTTPException(status_code=400, detail="surface 必须是 chat 或 agent")
        updates["surface"] = surface
    if request.role_id is not None:
        role_id = request.role_id.strip()
        if not role_id:
            raise HTTPException(status_code=400, detail="角色 ID 不能为空")
        updates["role_id"] = role_id
    if request.is_pinned is not None:
        updates["is_pinned"] = int(request.is_pinned)
    if request.is_title_customized is not None:
        updates["is_title_customized"] = int(request.is_title_customized)

    next_role_id = updates.get("role_id", existing["roleId"])
    next_surface = updates.get("surface", existing["surface"])
    await _ensure_role_allows_surface(str(next_role_id), str(next_surface))

    conversation = await storage.update_conversation(conversation_id, **updates)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"conversation": conversation}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: dict = Depends(get_current_user)) -> dict:
    existing = await storage.get_conversation(conversation_id)
    if not existing:
        raise HTTPException(status_code=404, detail="对话不存在")

    await storage.delete_conversation(conversation_id)
    return {"id": conversation_id, "message": "对话已删除"}


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: str, user: dict = Depends(get_current_user)) -> dict:
    conversation = await storage.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = await storage.list_messages(conversation_id)
    return {"messages": messages, "total": len(messages)}


@router.post("/conversations/{conversation_id}/messages")
async def create_message(conversation_id: str, request: MessageCreateRequest, user: dict = Depends(get_current_user)) -> dict:
    conversation = await storage.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="对话不存在")

    message = await storage.add_message(
        conversation_id=conversation_id,
        role=request.role,
        content=request.content,
        model=request.model,
        token_input=request.token_input,
        token_output=request.token_output,
        duration_ms=request.duration_ms,
        metadata=json.dumps(request.metadata, ensure_ascii=False),
    )
    return {"message": message}


@router.put("/messages/{message_id}")
async def update_message(message_id: str, request: MessageUpdateRequest, user: dict = Depends(get_current_user)) -> dict:
    updates = request.model_dump(exclude_none=True)
    message = await storage.update_message(message_id, **updates)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"message": message}
