"""
知识库路由 - PRD §10.1
POST /api/knowledge/ingest        - 文件导入知识库（PPT/PDF/DOCX/图片等）
POST /api/knowledge/extract-text  - 提取文件文本（不写入知识库，用于附件模式）
POST /api/knowledge/query         - 混合检索
GET  /api/knowledge/stats         - 知识库统计
GET  /api/knowledge/imports       - 已导入文件列表
DELETE /api/knowledge/imports/{id} - 删除已导入记录
"""
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from services.llm_profiles import get_runtime_llm_config
from services.knowledge_service import knowledge_service
from services.hybrid_search import hybrid_search
from services.embedding_service import embedding_service
from services.retrieval_planner import RetrievalPlannerSettings
from services.runtime_paths import IMPORTED_FILES_DIR
from services.runtime_controls import AttachmentParseBusyError, attachment_parse_controller
from services.storage import storage
from routers.auth import get_current_user
from utils.decryption_handler import decrypt_esafenet_file

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


def _collect_uploaded_files(
    file: UploadFile | None,
    files: list[UploadFile] | None,
) -> tuple[list[UploadFile], bool]:
    """兼容旧单文件字段 `file` 与新批量字段 `files`。"""
    collected: list[UploadFile] = []
    if file is not None:
        collected.append(file)
    if files:
        collected.extend(files)
    batch_mode = bool(files)
    return collected, batch_mode


async def _build_embedding_fn() -> tuple[Optional[object], dict]:
    """返回 embedding_fn 及当前启用状态，优先单独 Embedding 配置，缺失时回退到活动 LLM 配置。"""
    emb_url = await storage.get_setting("embedding_api_url", "")
    emb_key = await storage.get_setting("embedding_api_key", "")
    emb_model = await storage.get_setting("embedding_model", "text-embedding-3-small")

    if emb_url and emb_key:
        embedding_service.configure(api_url=emb_url, api_key=emb_key, model=emb_model)

        async def embedding_fn(texts: list) -> list:
            return await embedding_service.embed_batch(texts)

        return embedding_fn, {
            "enabled": True,
            "source": "embedding_settings",
            "model": emb_model or "text-embedding-3-small",
        }

    llm_runtime = await get_runtime_llm_config()
    if llm_runtime["api_url"] and llm_runtime["api_key"]:
        fallback_model = "text-embedding-3-small"
        embedding_service.configure(
            api_url=llm_runtime["api_url"],
            api_key=llm_runtime["api_key"],
            model=fallback_model,
        )

        async def embedding_fn(texts: list) -> list:
            return await embedding_service.embed_batch(texts)

        return embedding_fn, {
            "enabled": True,
            "source": "active_llm_profile",
            "model": fallback_model,
        }

    return None, {
        "enabled": False,
        "source": "disabled",
        "model": "",
    }


async def _validate_and_read_upload(file: UploadFile) -> tuple[str, bytes]:
    """校验单个上传文件并读取内容。"""
    if not file.filename:
        raise ValueError("文件名不能为空")

    ext = _get_file_ext(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(
            f"不支持的文件格式 '{ext}'。支持的格式: {allowed}",
        )

    content = await file.read()
    if not content:
        raise ValueError("文件内容为空")

    return file.filename, content


async def _store_imported_original_file(import_id: str, filename: str, file_content: bytes, *, is_encrypted: bool) -> str:
    effective_content = decrypt_esafenet_file(file_content, filename) if is_encrypted else file_content
    target_path = (IMPORTED_FILES_DIR / import_id / (Path(filename).name or "uploaded-file")).resolve()

    def _write_file() -> str:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(effective_content)
        return str(target_path)

    stored_file_path = await asyncio.to_thread(_write_file)
    try:
        await storage.update_ppt_import_file_path(import_id, stored_file_path)
    except RuntimeError:
        logger.debug("skip imported file path persistence because storage is not initialized")
    return stored_file_path


@router.post("/knowledge/ingest")
async def ingest_file(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    is_encrypted: bool = Form(True),
    user: dict = Depends(get_current_user),
) -> dict:
    """
    将文件导入知识库
    支持: PPT/PPTX, PDF, DOC/DOCX, 图片(PNG/JPG/...), 纯文本(TXT/MD/CSV/JSON)
    Pipeline: 解析 → LLM 结构化提取 → SQLite → 分块 → Embedding → LanceDB
    """
    uploads, batch_mode = _collect_uploaded_files(file, files)
    if not uploads:
        raise HTTPException(status_code=400, detail="至少上传一个文件")

    embedding_fn = None
    embedding_status = {"enabled": False, "source": "disabled", "model": ""}
    embedding_fn_ready = False
    results: list[dict] = []
    errors: list[dict] = []

    try:
        for upload in uploads:
            filename = upload.filename or "未命名文件"
            try:
                validated_filename, content = await _validate_and_read_upload(upload)
                if not embedding_fn_ready:
                    embedding_fn, embedding_status = await _build_embedding_fn()
                    embedding_fn_ready = True
                async with attachment_parse_controller.acquire(mode="ingest"):
                    result = await knowledge_service.ingest_file(
                        file_content=content,
                        filename=validated_filename,
                        llm_fn=None,
                        embedding_fn=embedding_fn,
                        owner_id=user.get("id"),
                        is_encrypted=is_encrypted,
                    )
                import_id = str(result.get("import_id") or "").strip()
                if import_id:
                    await _store_imported_original_file(
                        import_id,
                        validated_filename,
                        content,
                        is_encrypted=is_encrypted,
                    )
                result["embedding_status"] = dict(embedding_status)
                results.append(result)
            except AttachmentParseBusyError as e:
                errors.append({"filename": filename, "error": str(e), "status_code": 429})
            except ValueError as e:
                errors.append({"filename": filename, "error": str(e)})
            except Exception as e:
                logger.error(f"文件导入失败: {filename} - {e}")
                errors.append({"filename": filename, "error": f"导入失败: {str(e)}"})
    except Exception as e:
        logger.error(f"文件导入失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")

    if not batch_mode:
        if errors and not results:
            raise HTTPException(status_code=int(errors[0].get("status_code") or 400), detail=errors[0]["error"])
        if results:
            return results[0]

    return {
        "results": results,
        "errors": errors,
        "total": len(uploads),
        "success_count": len(results),
        "failed_count": len(errors),
    }


@router.post("/knowledge/query")
async def query_knowledge(request: QueryRequest, user: dict = Depends(get_current_user)) -> dict:
    """
    混合检索 - SQLite 精确查询 + LanceDB 语义检索
    """
    try:
        llm_runtime = await get_runtime_llm_config(
            api_url=request.api_url,
            api_key=request.api_key,
            model="",
        )
        results = await hybrid_search.search(
            query=request.query,
            category=request.category,
            limit=request.top_k,
            llm_settings=RetrievalPlannerSettings(
                api_url=llm_runtime["api_url"],
                api_key=llm_runtime["api_key"],
                model=llm_runtime["model"],
                user_id=str(user.get("id") or ""),
            ),
        )
        return results
    except Exception as e:
        logger.error(f"知识库检索失败: {e}")
        raise HTTPException(status_code=500, detail=f"检索失败: {str(e)}")


@router.get("/knowledge/stats")
async def get_stats(user: dict = Depends(get_current_user)) -> dict:
    """获取知识库统计信息"""
    try:
        stats = await knowledge_service.get_stats()
        emb_url = await storage.get_setting("embedding_api_url", "")
        emb_key = await storage.get_setting("embedding_api_key", "")
        emb_model = await storage.get_setting("embedding_model", "text-embedding-3-small")
        stats["embedding_configured"] = bool(emb_url and emb_key)
        stats["embedding_model"] = emb_model or "text-embedding-3-small"
        return stats
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@router.post("/knowledge/extract-text")
async def extract_text(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    fast_mode: bool = Form(True),
    user: dict = Depends(get_current_user),
) -> dict:
    """
    提取文件文本内容（不写入知识库）。
    用于 📎 附件模式：将文件内容作为上下文发送给 LLM。
    """
    uploads, batch_mode = _collect_uploaded_files(file, files)
    if not uploads:
        raise HTTPException(status_code=400, detail="至少上传一个文件")

    extractor = (
        knowledge_service.extract_text_fast
        if fast_mode
        else knowledge_service.extract_text_structured
    )

    async def _extract_single(upload: UploadFile) -> tuple[dict | None, dict | None]:
        filename = upload.filename or "未命名文件"
        try:
            validated_filename, content = await _validate_and_read_upload(upload)
            async with attachment_parse_controller.acquire(mode="fast" if fast_mode else "ingest"):
                result = await extractor(
                    file_content=content,
                    filename=validated_filename,
                )
            return result, None
        except AttachmentParseBusyError as e:
            return None, {"filename": filename, "error": str(e), "status_code": 429}
        except ValueError as e:
            return None, {"filename": filename, "error": str(e)}
        except Exception as e:
            logger.error(f"文件文本提取失败: {filename} - {e}")
            return None, {"filename": filename, "error": f"文本提取失败: {str(e)}"}

    try:
        extracted_items = await asyncio.gather(*[_extract_single(upload) for upload in uploads])
        results = [result for result, _ in extracted_items if result is not None]
        errors = [error for _, error in extracted_items if error is not None]
    except Exception as e:
        logger.error(f"文件文本提取失败: {e}")
        raise HTTPException(status_code=500, detail=f"文本提取失败: {str(e)}")

    if not batch_mode:
        if errors and not results:
            raise HTTPException(status_code=400, detail=errors[0]["error"])
        if results:
            return results[0]

    return {
        "files": results,
        "errors": errors,
        "total": len(uploads),
        "success_count": len(results),
        "failed_count": len(errors),
    }


@router.get("/knowledge/imports")
async def list_imports(user: dict = Depends(get_current_user)) -> dict:
    """获取已导入文件列表"""
    try:
        is_admin = user.get("system_role") == "admin"
        imports = await knowledge_service.list_imports(
            user_id=user.get("id"),
            group_id=user.get("group_id"),
            is_admin=is_admin,
        )
        return {"imports": imports, "total": len(imports)}
    except Exception as e:
        logger.error(f"获取导入列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取导入列表失败: {str(e)}")


@router.delete("/knowledge/imports/{import_id}")
async def delete_import(import_id: str, user: dict = Depends(get_current_user)) -> dict:
    """删除指定的知识库导入记录"""
    try:
        import_row = await storage.get_ppt_import(import_id)
        result = await knowledge_service.delete_import(import_id)
        if not result.get("deleted"):
            raise HTTPException(status_code=404, detail=result.get("message", "记录不存在"))
        stored_file_path = str((import_row or {}).get("stored_file_path") or "").strip()
        if stored_file_path:
            target_dir = Path(stored_file_path).resolve().parent
            if target_dir.exists() and target_dir.is_dir() and target_dir.is_relative_to(IMPORTED_FILES_DIR.resolve()):
                await asyncio.to_thread(shutil.rmtree, target_dir, True)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除导入记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
