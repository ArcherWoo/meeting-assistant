"""
设置路由
GET  /api/settings/system-prompt/{mode}  - 获取指定模式的 System Prompt
PUT  /api/settings/system-prompt/{mode}  - 保存指定模式的 System Prompt
GET  /api/settings/embedding             - 获取 Embedding API 配置
PUT  /api/settings/embedding             - 保存 Embedding API 配置
DELETE /api/settings/embedding           - 清除 Embedding API 配置
POST /api/settings/embedding/test        - 测试 Embedding 连通性
"""
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.storage import storage

router = APIRouter()

# 支持的模式（与前端 AppMode 保持一致：copilot / builder / agent）
VALID_MODES = {"copilot", "builder", "agent"}

# 默认 System Prompt
DEFAULT_PROMPTS = {
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


class SystemPromptRequest(BaseModel):
    """System Prompt 更新请求"""
    prompt: str


class EmbeddingConfigRequest(BaseModel):
    """Embedding API 配置请求"""
    api_url: str = ""
    api_key: str = ""
    model: str = "text-embedding-3-small"


def _settings_key(mode: str) -> str:
    return f"system_prompt_{mode}"


@router.get("/settings/system-prompt/{mode}")
async def get_system_prompt(mode: str) -> dict:
    """获取指定模式的 System Prompt（未设置则返回默认值）"""
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"不支持的模式：{mode}，可选值：{', '.join(VALID_MODES)}")
    value = await storage.get_setting(_settings_key(mode), default="")
    return {
        "mode": mode,
        "prompt": value if value else DEFAULT_PROMPTS.get(mode, ""),
        "is_custom": bool(value),
    }


@router.put("/settings/system-prompt/{mode}")
async def update_system_prompt(mode: str, request: SystemPromptRequest) -> dict:
    """保存指定模式的 System Prompt"""
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"不支持的模式：{mode}，可选值：{', '.join(VALID_MODES)}")
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="System Prompt 不能为空")
    await storage.set_setting(_settings_key(mode), prompt)
    return {"mode": mode, "prompt": prompt, "message": f"{mode} 模式的 System Prompt 已保存"}


@router.delete("/settings/system-prompt/{mode}")
async def reset_system_prompt(mode: str) -> dict:
    """重置指定模式的 System Prompt 为默认值"""
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"不支持的模式：{mode}，可选值：{', '.join(VALID_MODES)}")
    await storage.set_setting(_settings_key(mode), "")
    return {
        "mode": mode,
        "prompt": DEFAULT_PROMPTS.get(mode, ""),
        "message": f"{mode} 模式的 System Prompt 已重置为默认值",
    }


# ===== Embedding 配置 =====

_EMB_URL_KEY = "embedding_api_url"
_EMB_KEY_KEY = "embedding_api_key"
_EMB_MODEL_KEY = "embedding_model"
_EMB_MODEL_DEFAULT = "text-embedding-3-small"


@router.get("/settings/embedding")
async def get_embedding_config() -> dict:
    """获取 Embedding API 配置"""
    api_url = await storage.get_setting(_EMB_URL_KEY, default="")
    api_key = await storage.get_setting(_EMB_KEY_KEY, default="")
    model = await storage.get_setting(_EMB_MODEL_KEY, default=_EMB_MODEL_DEFAULT)
    return {
        "api_url": api_url,
        "api_key": api_key,
        "model": model or _EMB_MODEL_DEFAULT,
        "is_configured": bool(api_url and api_key),
    }


@router.put("/settings/embedding")
async def update_embedding_config(request: EmbeddingConfigRequest) -> dict:
    """保存 Embedding API 配置"""
    await storage.set_setting(_EMB_URL_KEY, request.api_url.strip())
    await storage.set_setting(_EMB_KEY_KEY, request.api_key.strip())
    await storage.set_setting(_EMB_MODEL_KEY, request.model.strip() or _EMB_MODEL_DEFAULT)
    return {
        "message": "Embedding 配置已保存",
        "is_configured": bool(request.api_url.strip() and request.api_key.strip()),
    }


@router.delete("/settings/embedding")
async def reset_embedding_config() -> dict:
    """清除 Embedding API 配置（回退到使用 LLM API 凭证）"""
    await storage.set_setting(_EMB_URL_KEY, "")
    await storage.set_setting(_EMB_KEY_KEY, "")
    await storage.set_setting(_EMB_MODEL_KEY, "")
    return {"message": "Embedding 配置已清除"}


@router.post("/settings/embedding/test")
async def test_embedding_config(request: EmbeddingConfigRequest) -> dict:
    """测试 Embedding API 连通性"""
    if not request.api_url.strip() or not request.api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Base URL 和 API Key")
    url = request.api_url.rstrip("/") + "/embeddings"
    model = request.model.strip() or _EMB_MODEL_DEFAULT
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                json={"model": model, "input": ["连接测试"]},
                headers={
                    "Authorization": f"Bearer {request.api_key}",
                    "Content-Type": "application/json",
                },
            )
        if response.status_code == 200:
            data = response.json()
            dim = len(data["data"][0]["embedding"]) if data.get("data") else 0
            return {"success": True, "message": f"连接成功，向量维度: {dim}", "dimension": dim}
        else:
            detail = response.json().get("error", {}).get("message", response.text[:200])
            return {"success": False, "message": f"连接失败: {detail}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}

