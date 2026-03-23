"""
知识库路由 - PRD §10.1
POST /api/knowledge/ingest        - 文件导入知识库（PPT/PDF/DOCX/图片等）
POST /api/knowledge/extract-text  - 提取文件文本（不写入知识库，用于附件模式）
POST /api/knowledge/query         - 混合检索
GET  /api/knowledge/stats         - 知识库统计
GET  /api/knowledge/imports       - 已导入文件列表
DELETE /api/knowledge/imports/{id} - 删除已导入记录
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from services.knowledge_service import knowledge_service
from services.hybrid_search import hybrid_search
from services.embedding_service import embedding_service
from services.storage import storage

logger = logging.getLogger(__name__)
router = APIRouter()

# 支持的文件扩展名
ALLOWED_EXTENSIONS = {
    ".ppt", ".pptx",                          # PPT
    ".pdf",                                     # PDF
    ".doc", ".docx",                            # Word
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",  # 图片
    ".txt", ".md", ".csv", ".json", ".xml",     # 纯文本
    ".xls", ".xlsx",                            # Excel
}


class QueryRequest(BaseModel):
    """混合检索请求"""
    query: str
    category: Optional[str] = None
    top_k: int = 5
    # LLM/Embedding 配置（前端传入）
    api_url: str = ""
    api_key: str = ""
    embedding_model: str = "text-embedding-3-small"


def _get_file_ext(filename: str) -> str:
    """获取文件扩展名（小写）"""
    import os
    return os.path.splitext(filename)[1].lower()


@router.post("/knowledge/ingest")
async def ingest_file(file: UploadFile = File(...)) -> dict:
    """
    将文件导入知识库
    支持: PPT/PPTX, PDF, DOC/DOCX, 图片(PNG/JPG/...), 纯文本(TXT/MD/CSV/JSON)
    Pipeline: 解析 → LLM 结构化提取 → SQLite → 分块 → Embedding → LanceDB
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = _get_file_ext(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '{ext}'。支持的格式: {allowed}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 从数据库读取 Embedding 配置
    emb_url = await storage.get_setting("embedding_api_url", "")
    emb_key = await storage.get_setting("embedding_api_key", "")
    emb_model = await storage.get_setting("embedding_model", "text-embedding-3-small")

    embedding_fn = None
    if emb_url and emb_key:
        embedding_service.configure(api_url=emb_url, api_key=emb_key, model=emb_model)
        async def embedding_fn(texts: list) -> list:
            return await embedding_service.embed_batch(texts)

    try:
        result = await knowledge_service.ingest_file(
            file_content=content,
            filename=file.filename,
            llm_fn=None,
            embedding_fn=embedding_fn,
        )
        return result
    except Exception as e:
        logger.error(f"文件导入失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.post("/knowledge/query")
async def query_knowledge(request: QueryRequest) -> dict:
    """
    混合检索 - SQLite 精确查询 + LanceDB 语义检索
    """
    try:
        results = await hybrid_search.search(
            query=request.query,
            category=request.category,
            limit=request.top_k,
        )
        return results
    except Exception as e:
        logger.error(f"知识库检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")


@router.get("/knowledge/stats")
async def get_stats() -> dict:
    """获取知识库统计信息"""
    try:
        stats = await knowledge_service.get_stats()
        return stats
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.post("/knowledge/extract-text")
async def extract_text(file: UploadFile = File(...)) -> dict:
    """
    提取文件文本内容（不写入知识库）。
    用于 📎 附件模式：将文件内容作为上下文发送给 LLM。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = _get_file_ext(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 '{ext}'。支持的格式: {allowed}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        result = await knowledge_service.extract_text(
            file_content=content,
            filename=file.filename,
        )
        return result
    except Exception as e:
        logger.error(f"文件文本提取失败: {e}")
        raise HTTPException(status_code=500, detail=f"文本提取失败: {str(e)}")


@router.get("/knowledge/imports")
async def list_imports() -> dict:
    """获取已导入文件列表"""
    try:
        imports = await knowledge_service.list_imports()
        return {"imports": imports, "total": len(imports)}
    except Exception as e:
        logger.error(f"获取导入列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取导入列表失败: {str(e)}")


@router.delete("/knowledge/imports/{import_id}")
async def delete_import(import_id: str) -> dict:
    """删除指定的知识库导入记录"""
    try:
        result = await knowledge_service.delete_import(import_id)
        if not result.get("deleted"):
            raise HTTPException(status_code=404, detail=result.get("message", "记录不存在"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除导入记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

