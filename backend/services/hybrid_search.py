"""
混合检索引擎 - Hybrid Search
遵循 PRD §12.5：SQLite 精确查询（硬查询）+ LanceDB 语义检索（软查询）+ LLM 综合分析
"""
import logging
from typing import Any, Callable, List, Optional

from services.embedding_service import embedding_service
from services.knowledge_service import knowledge_service
from services.storage import storage

logger = logging.getLogger(__name__)


class HybridSearchService:
    """混合检索：结构化精确查询 + 语义向量检索"""

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        supplier: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        """
        执行混合检索，返回结构化结果 + 语义结果
        返回: {"structured": [...], "semantic": [...], "query": str}
        """
        # 1. SQLite 结构化查询（精确匹配）
        structured = await self._structured_search(
            query, category=category, supplier=supplier, limit=limit,
        )

        # 2. LanceDB 语义检索（模糊匹配）
        semantic = await self._semantic_search(query, limit=min(limit, 5))

        return {
            "query": query,
            "structured": structured,
            "semantic": semantic,
        }

    async def _structured_search(
        self,
        query: str,
        category: Optional[str] = None,
        supplier: Optional[str] = None,
        limit: int = 10,
    ) -> List[dict]:
        """SQLite 结构化查询 - 按品类/供应商/品名精确或模糊查询"""
        try:
            # 优先使用显式过滤条件
            if category or supplier:
                return await storage.search_procurement(
                    category=category, supplier=supplier, limit=limit,
                )

            # 无显式条件时，按品名/品类/供应商模糊匹配
            rows = await storage._fetchall(
                "SELECT * FROM procurement_records "
                "WHERE item_name LIKE ? OR category LIKE ? OR supplier LIKE ? "
                "ORDER BY extracted_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
            return rows
        except Exception as e:
            logger.warning(f"结构化检索失败: {e}")
            return []

    async def _semantic_search(
        self, query: str, limit: int = 5,
    ) -> List[dict]:
        """LanceDB 向量语义检索"""
        if not embedding_service.is_configured:
            return []
        # 极短查询（< 4 字符）没有语义检索价值，跳过 embedding 调用
        if len(query.strip()) < 4:
            return []
        try:
            query_vec = await embedding_service.embed_text(query)
            return await knowledge_service.vector_search(query_vec, limit=limit)
        except Exception as e:
            logger.warning(f"语义检索失败: {e}")
            return []

    async def price_analysis(
        self, category: str, current_price: float,
    ) -> dict:
        """价格合理性分析 - 与历史同品类均价对比"""
        try:
            row = await storage._fetchone(
                "SELECT AVG(unit_price) as avg_price, COUNT(*) as cnt, "
                "MIN(unit_price) as min_price, MAX(unit_price) as max_price "
                "FROM procurement_records WHERE category=? AND unit_price IS NOT NULL",
                (category,),
            )
            if not row or not row["avg_price"]:
                return {"has_history": False, "category": category}

            avg = row["avg_price"]
            deviation = ((current_price - avg) / avg) * 100 if avg else 0

            return {
                "has_history": True,
                "category": category,
                "current_price": current_price,
                "avg_price": round(avg, 2),
                "min_price": round(row["min_price"], 2),
                "max_price": round(row["max_price"], 2),
                "history_count": row["cnt"],
                "deviation_pct": round(deviation, 1),
                "judgment": (
                    "正常" if abs(deviation) <= 15
                    else "偏高" if deviation > 15
                    else "偏低"
                ),
            }
        except Exception as e:
            logger.warning(f"价格分析失败: {e}")
            return {"has_history": False, "category": category, "error": str(e)}


# 全局单例
hybrid_search = HybridSearchService()

