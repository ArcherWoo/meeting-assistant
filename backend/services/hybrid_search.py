"""
Hybrid search service.

Combines three retrieval channels:
1. Structured SQLite procurement records
2. SQLite-backed generic knowledge chunks
3. LanceDB semantic search when embeddings are configured
"""
import logging
import json
import re
from typing import List, Optional

from services.embedding_service import embedding_service
from services.knowledge_service import knowledge_service
from services.llm_service import LLMService, llm_service as shared_llm_service
from services.retrieval_planner import RetrievalPlannerSettings
from services.storage import storage
from utils.text_utils import extract_han_segments

logger = logging.getLogger(__name__)


class HybridSearchService:
    """Hybrid retrieval for structured records and document chunks."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self._llm_service = llm_service or shared_llm_service

    MAX_QUERY_TERMS = 14
    MAX_CHINESE_SUBTERM_LENGTH = 6
    QUERY_STOPWORDS = {
        "请",
        "请帮我",
        "请帮忙",
        "麻烦",
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
        "查看",
        "查询",
        "检索",
        "查找",
        "核对",
        "评估",
        "分析",
        "判断",
        "确认",
        "呢",
        "吗",
        "吧",
        "呀",
        "啊",
        "的",
        "了",
        "和",
        "与",
        "及",
        "并",
        "并且",
    }

    def _expand_chinese_subterms(self, fragment: str) -> list[str]:
        text = fragment.strip()
        if len(text) < 2:
            return []
        if len(text) <= 3:
            return [text]

        terms = [text]
        max_window = min(self.MAX_CHINESE_SUBTERM_LENGTH, len(text) - 1)
        for window in range(max_window, 1, -1):
            for start in range(0, len(text) - window + 1):
                terms.append(text[start:start + window])
        return terms

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

        for segment in extract_han_segments(normalized, min_length=2):
            cleaned = segment
            for stopword in sorted(self.QUERY_STOPWORDS, key=len, reverse=True):
                cleaned = cleaned.replace(stopword, " ")
            for part in [part.strip() for part in cleaned.split() if len(part.strip()) >= 2]:
                candidates.extend(self._expand_chinese_subterms(part))

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if len(candidate) < 2 or candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
            if len(deduped) >= self.MAX_QUERY_TERMS:
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
        llm_settings: RetrievalPlannerSettings | None = None,
    ) -> dict:
        """
        Execute hybrid search and return:
        {"query": str, "structured": [...], "semantic": [...]}
        """
        planner_settings = llm_settings or RetrievalPlannerSettings()
        candidate_limit = limit
        if planner_settings.is_configured:
            candidate_limit = max(limit, min(limit * 2, 10))

        structured = await self._structured_search(
            query, category=category, supplier=supplier, limit=candidate_limit,
        )

        remaining = max(candidate_limit - len(structured), 0)
        if remaining > 0:
            text_matches = await self._text_search(query, limit=remaining)
            structured = self._merge_unique(structured, text_matches, candidate_limit)

        semantic = await self._semantic_search(query, limit=min(limit, 5))

        if not semantic and planner_settings.is_configured and structured:
            reranked = await self._llm_rerank_candidates(
                query=query,
                candidates=structured,
                limit=limit,
                settings=planner_settings,
            )
            if reranked:
                structured = reranked
            else:
                structured = structured[:limit]
        else:
            structured = structured[:limit]

        if not structured and not semantic:
            structured = await self._legacy_import_notice(limit=min(limit, 3))

        return {
            "query": query,
            "structured": structured,
            "semantic": semantic,
        }

    @staticmethod
    def _candidate_snippet(item: dict) -> str:
        parts = [
            str(item.get("item_name") or "").strip(),
            str(item.get("category") or "").strip(),
            str(item.get("supplier") or "").strip(),
            str(item.get("raw_text") or "").strip(),
            str(item.get("content") or "").strip(),
            str(item.get("source_file") or "").strip(),
        ]
        return " ".join(part for part in parts if part)[:320]

    def _build_rerank_prompt(self, query: str, candidates: list[dict], limit: int) -> list[dict]:
        lines: list[str] = []
        for index, item in enumerate(candidates, 1):
            lines.append(
                f"[{index}] id={item.get('id') or ''}\n"
                f"source={item.get('source_file') or 'structured-record'}\n"
                f"snippet={self._candidate_snippet(item)}"
            )

        return [
            {
                "role": "system",
                "content": (
                    "你是企业知识检索重排器。"
                    "给定用户问题和候选知识片段，只返回最相关的结果。"
                    "请只输出 JSON，不要输出 Markdown。"
                    '格式：{"selected_ids":["id1","id2"],"notes":"一句话"}。'
                    "如果都不相关，selected_ids 返回空数组。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{query}\n"
                    f"最多保留 {limit} 条候选。\n"
                    "候选片段：\n"
                    + "\n\n".join(lines)
                ),
            },
        ]

    async def _llm_rerank_candidates(
        self,
        *,
        query: str,
        candidates: list[dict],
        limit: int,
        settings: RetrievalPlannerSettings,
    ) -> list[dict]:
        if not candidates:
            return []
        try:
            response = await self._llm_service.chat(
                messages=self._build_rerank_prompt(query, candidates, limit),
                model=settings.model.strip() or "gpt-4o",
                temperature=0.1,
                max_tokens=600,
                api_url=settings.api_url,
                api_key=settings.api_key,
                user_id=settings.user_id or None,
            )
            text = self._llm_service.extract_text_content(response)
            if not text:
                return []
            payload = json.loads(self._extract_json_payload(text))
            raw_ids = payload.get("selected_ids") or []
            if not isinstance(raw_ids, list):
                return []

            candidates_by_id = {
                str(item.get("id") or ""): item
                for item in candidates
                if str(item.get("id") or "")
            }
            selected: list[dict] = []
            seen: set[str] = set()
            for raw_id in raw_ids:
                candidate_id = str(raw_id or "").strip()
                if not candidate_id or candidate_id in seen:
                    continue
                item = candidates_by_id.get(candidate_id)
                if item is None:
                    continue
                seen.add(candidate_id)
                enriched = dict(item)
                enriched["rerank_strategy"] = "llm_fallback"
                selected.append(enriched)
                if len(selected) >= limit:
                    break
            return selected
        except Exception as exc:
            logger.info("LLM rerank fallback failed: %s", exc)
            return []

    @staticmethod
    def _extract_json_payload(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError(f"rerank response did not contain JSON: {text[:200]}")
        return stripped[start:end + 1]

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
        # 仅跳过空串或 1 字符噪声查询，保留 2~3 字中文短查询的语义召回机会。
        if len(query.strip()) < 2:
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
