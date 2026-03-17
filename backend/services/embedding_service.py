"""
Embedding 服务 - 文本向量化
支持两种后端：
  1. 云端 OpenAI 兼容 API（默认，text-embedding-3-small 等）
  2. 本地 BGE-M3 ONNX Runtime（TODO - Phase 2 后续）
遵循 PRD §1.4 技术栈：BGE-M3 768 维，中英文优秀
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 默认向量维度（BGE-M3 = 768，OpenAI text-embedding-3-small = 1536）
DEFAULT_DIMENSION = 768


class EmbeddingService:
    """文本 Embedding 服务"""

    def __init__(self) -> None:
        self._api_url: str = ""
        self._api_key: str = ""
        self._model: str = "text-embedding-3-small"
        self._dimension: int = DEFAULT_DIMENSION

    def configure(self, api_url: str, api_key: str, model: str = "text-embedding-3-small", dimension: int = DEFAULT_DIMENSION) -> None:
        """配置 Embedding API 参数"""
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_configured(self) -> bool:
        return bool(self._api_url and self._api_key)

    async def embed_text(self, text: str) -> list[float]:
        """将单条文本转为向量"""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量文本向量化
        调用 OpenAI 兼容的 /embeddings 接口
        """
        if not self.is_configured:
            raise RuntimeError("EmbeddingService 未配置，请先调用 configure()")

        url = f"{self._api_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload: dict = {
            "model": self._model,
            "input": texts,
        }
        # 部分 API 支持 dimensions 参数（如 OpenAI text-embedding-3-*）
        if self._dimension and "text-embedding-3" in self._model:
            payload["dimensions"] = self._dimension

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        # 按 index 排序确保顺序一致
        embeddings = sorted(data["data"], key=lambda x: x["index"])
        return [e["embedding"] for e in embeddings]


# 全局单例
embedding_service = EmbeddingService()

