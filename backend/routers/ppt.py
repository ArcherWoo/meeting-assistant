"""
PPT 解析路由
Phase 1: 使用 python-pptx 基础解析
Phase 2: 集成 Docling 双引擎方案
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.ppt_parser import PPTParser

router = APIRouter()
ppt_parser = PPTParser()


@router.post("/ppt/parse")
async def parse_pptx(file: UploadFile = File(...)):
    """
    解析上传的 PPT 文件，返回结构化内容
    支持 .pptx 格式
    """
    if not file.filename or not file.filename.endswith(('.pptx', '.ppt')):
        raise HTTPException(status_code=400, detail="仅支持 .pptx 格式文件")

    try:
        content = await file.read()
        result = await ppt_parser.parse(content, file.filename)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PPT 解析失败: {str(e)}")

