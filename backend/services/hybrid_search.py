"""
Hybrid search service.

Combines three retrieval channels:
1. Structured SQLite procurement records
2. SQLite-backed generic knowledge chunks
3. LanceDB semantic search when embeddings are configured
"""
import logging
import re
from typing import List, Optional

from services.embedding_service import embedding_service
from services.knowledge_service import knowledge_service
from services.storage import storage

logger = logging.getLogger(__name__)


class HybridSearchService:
    """Hybrid retrieval for structured records and document chunks."""

    QUERY_STOPWORDS = {
        "请问",
        "帮我",
        "帮忙",
        "告诉我",
        "知识库",
        "文件名",
        "文件",
        "内容",
        "里面",
        "里",
        "这个",
        "这份",
        "一下",
        "一下子",
        "有无",
        "有没有",
        "是否",
        "什么",
        "哪些",
        "多少",
        "怎么",
        "如何",
        "以及",
        "还有",
        "关于",
        "用户",
        "上传",
        "数据",
        "历史",
        "记录",
        "给我",
        "看下",
        "看看",
        "一下",
        "一下吧",
        "呢",
        "吗",
        "吧",
        "呀",
        "啊",
        "的",
        "了",
        "和",
    }

    def _extract_query_terms(self, query: str) -> List[str]:
        normalized = " ".join((query or "").lower().split())
        if not normalized:
            return []

        candidates: list[str] = [normalized]
        candidates.extend(
            term.strip()
            for term in re.split(r"[\s,.;:!?，。；：！？、/\\()（）【】\[\]\"'`]+", normalized)
            if len(term.strip()) >= 2
        )
        candidates.extend(re.findall(r"[a-z0-9][a-z0-9_.-]{1,}", normalized))

        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
            cleaned = segment
            for stopword in sorted(self.QUERY_STOPWORDS, key=len, reverse=True):
                cleaned = cleaned.replace(stopword, " ")
            candidates.extend(part.strip() for part in cleaned.split() if len(part.strip()) >= 2)

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if len(candidate) < 2 or candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
            if len(deduped) >= 8:
                break
        return deduped

    @staticmethod
    def _merge_unique(primary: List[dict], secondary: List[dict], limit: int) -> List[dict]:
        merged: list[dict] = []
        seen_ids: set[str] = set()

        for item in [*primary, *secondary]:
            raw_id = item.get("id") or item.get("import_id") or f"_row_{len(merged)}"
            item_id = str(raw_id)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            merged.append(item)
            if len(merged) >= limit:
                break

        return merged

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        supplier: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        """
        Execute hybrid search and return:
        {"query": str, "structured": [...], "semantic": [...]}
        """
        structured = await self._structured_search(
            query, category=category, supplier=supplier, limit=limit,
        )

        remaining = max(limit - len(structured), 0)
        if remaining > 0:
            text_matches = await self._text_search(query, limit=remaining)
            structured = self._merge_unique(structured, text_matches, limit)

        semantic = await self._semantic_search(query, limit=min(limit, 5))

        if not structured and not semantic:
            structured = await self._legacy_import_notice(limit=min(limit, 3))

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
        """Structured SQLite search over procurement records."""
        try:
            if category or supplier:
                return await storage.search_procurement(
                    category=category, supplier=supplier, limit=limit,
                )

            return await storage._fetchall(
                "SELECT * FROM procurement_records "
                "WHERE item_name LIKE ? OR category LIKE ? OR supplier LIKE ? "
                "ORDER BY extracted_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            )
        except Exception as e:
            logger.warning(f"Structured search failed: {e}")
            return []

    async def _text_search(self, query: str, limit: int = 5) -> List[dict]:
        """Fallback SQLite search over persisted knowledge chunks."""
        if limit <= 0:
            return []

        keywords = self._extract_query_terms(query)
        if not keywords:
            return []

        try:
            return await storage.search_knowledge_chunks(keywords, limit=limit)
        except Exception as e:
            logger.warning(f"Knowledge chunk search failed: {e}")
            return []

    async def _legacy_import_notice(self, limit: int = 3) -> List[dict]:
        """
        When the database only contains old import records without indexed chunks,
        surface a truthful notice instead of silently behaving as if nothing exists.
        """
        try:
            chunk_count = await storage.count_knowledge_chunks()
            if chunk_count > 0:
                return []

            record_row = await storage._fetchone("SELECT COUNT(*) AS cnt FROM procurement_records")
            import_row = await storage._fetchone("SELECT COUNT(*) AS cnt FROM ppt_imports")
            if (record_row["cnt"] if record_row else 0) > 0:
                return []
            if not import_row or int(import_row["cnt"]) <= 0:
                return []

            rows = await storage.list_unindexed_imports(limit)
            notices: list[dict] = []
            for row in rows:
                filename = str(row.get("file_name") or "已导入文件")
                notices.append({
                    "id": f"legacy-import-{row.get('id')}",
                    "import_id": row.get("id"),
                    "source_file": filename,
                    "file_type": "import",
                    "slide_index": 0,
                    "chunk_type": "text",
                    "chunk_index": 1,
                    "content": (
                        f"已导入文件《{filename}》，但当前库中还没有可检索的正文片段。"
                        "这通常是旧版本导入留下的记录；重新导入一次即可补建索引。"
                    ),
                    "score": 0.0,
                })
            return notices
        except Exception as e:
            logger.warning(f"Legacy import fallback failed: {e}")
            return []

    async def _semantic_search(self, query: str, limit: int = 5) -> List[dict]:
        """LanceDB semantic search."""
        if not embedding_service.is_configured:
            return []
        if len(query.strip()) < 4:
            return []
        try:
            query_vec = await embedding_service.embed_text(query)
            return await knowledge_service.vector_search(query_vec, limit=limit)
        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")
            return []

    async def price_analysis(self, category: str, current_price: float) -> dict:
        """Compare a price against historical procurement records."""
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
            logger.warning(f"Price analysis failed: {e}")
            return {"has_history": False, "category": category, "error": str(e)}


hybrid_search = HybridSearchService()
