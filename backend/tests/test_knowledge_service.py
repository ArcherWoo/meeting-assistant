import hashlib
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.hybrid_search import hybrid_search
from services.knowledge_service import KnowledgeService
from services.storage import storage
from services.embedding_service import embedding_service


class KnowledgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = KnowledgeService()

    def test_extract_pdf_text_falls_back_to_pypdf_when_pymupdf_is_missing(self):
        with patch.object(
            KnowledgeService,
            "_extract_pdf_text_with_pymupdf",
            side_effect=ModuleNotFoundError("No module named 'fitz'"),
        ):
            with patch.object(
                KnowledgeService,
                "_extract_pdf_text_with_pypdf",
                return_value="PDF body text",
            ) as pypdf_mock:
                text = self.service._extract_pdf_text_sync(b"%PDF-1.4", "sample.pdf")

        self.assertEqual(text, "PDF body text")
        pypdf_mock.assert_called_once_with(b"%PDF-1.4")

    def test_extract_pdf_text_reports_missing_parser_when_no_pdf_dependency_exists(self):
        with patch.object(
            KnowledgeService,
            "_extract_pdf_text_with_pymupdf",
            side_effect=ModuleNotFoundError("No module named 'fitz'"),
        ):
            with patch.object(
                KnowledgeService,
                "_extract_pdf_text_with_pypdf",
                side_effect=ModuleNotFoundError("No module named 'pypdf'"),
            ):
                text = self.service._extract_pdf_text_sync(b"%PDF-1.4", "sample.pdf")

        self.assertIn("缺少 PDF 解析依赖", text)
        self.assertIn("sample.pdf", text)

    def test_split_into_chunks_assigns_stable_fragment_indexes(self):
        ppt_data = {
            "slides": [
                {
                    "index": 1,
                    "texts": ["封面内容"],
                    "tables": [{"markdown": "| 型号 | 价格 |\n| --- | --- |"}],
                    "notes": "演讲备注",
                }
            ]
        }

        chunks = self.service._split_into_chunks(ppt_data, "报价方案.pptx")

        self.assertEqual(len(chunks), 3)
        self.assertEqual([chunk["chunk_index"] for chunk in chunks], [1, 2, 3])
        self.assertEqual(chunks[0]["chunk_type"], "text")
        self.assertEqual(chunks[1]["chunk_type"], "table")
        self.assertEqual(chunks[2]["chunk_type"], "note")

    def test_split_text_into_chunks_tracks_char_ranges(self):
        text = "  " + ("A" * 160) + "  "
        chunks = self.service._split_text_into_chunks(text, "会议纪要.txt", chunk_size=120)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["chunk_index"], 1)
        self.assertEqual(chunks[0]["char_start"], 2)
        self.assertEqual(chunks[0]["char_end"], 120)
        self.assertEqual(chunks[0]["content"], "A" * 118)

    def test_chunk_metadata_roundtrip_preserves_fragment_locator(self):
        raw_metadata = self.service._build_chunk_metadata(
            "import-1",
            {"chunk_index": 4, "char_start": 120, "char_end": 268},
        )

        self.assertEqual(
            self.service._parse_chunk_metadata(raw_metadata),
            {
                "import_id": "import-1",
                "chunk_index": 4,
                "char_start": 120,
                "char_end": 268,
            },
        )


class KnowledgeServiceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_vectors_for_file_escapes_lancedb_literal(self):
        service = KnowledgeService()
        table = Mock()
        lance_db = Mock()
        lance_db.table_names.return_value = ["doc_chunks"]
        lance_db.open_table.return_value = table
        service._lance_db = lance_db

        deleted = await service._delete_vectors_for_file("quote's.txt")

        self.assertTrue(deleted)
        table.delete.assert_called_once_with("source_file = 'quote''s.txt'")


class HybridSearchServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_config = (
            embedding_service._api_url,
            embedding_service._api_key,
            embedding_service._model,
            embedding_service._dimension,
        )

    async def asyncTearDown(self):
        api_url, api_key, model, dimension = self.original_config
        embedding_service.configure(api_url=api_url, api_key=api_key, model=model, dimension=dimension)

    async def test_semantic_search_keeps_short_chinese_queries(self):
        embedding_service.configure(api_url="https://example.com/v1", api_key="sk-test")
        with patch.object(embedding_service, "embed_text", AsyncMock(return_value=[0.1, 0.2])) as embed_mock:
            with patch("services.hybrid_search.knowledge_service.vector_search", AsyncMock(return_value=[{"id": "chunk-1"}])) as vector_mock:
                result = await hybrid_search._semantic_search("电脑", limit=3)

        self.assertEqual(result, [{"id": "chunk-1"}])
        embed_mock.assert_awaited_once_with("电脑")
        vector_mock.assert_awaited_once_with([0.1, 0.2], limit=3)

    async def test_semantic_search_skips_single_character_noise(self):
        embedding_service.configure(api_url="https://example.com/v1", api_key="sk-test")
        with patch.object(embedding_service, "embed_text", AsyncMock(return_value=[0.1, 0.2])) as embed_mock:
            result = await hybrid_search._semantic_search("价", limit=3)

        self.assertEqual(result, [])
        embed_mock.assert_not_awaited()

    async def test_extract_query_terms_from_natural_language_keeps_core_chinese_phrases(self):
        terms = hybrid_search._extract_query_terms("请帮我核对付款方式是否合理，并评估单一来源风险是否可接受")

        self.assertIn("付款方式", terms)
        self.assertIn("单一来源风险", terms)


class KnowledgeServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = KnowledgeService()
        self.temp_root = Path(BACKEND_ROOT) / ".tmp-test-data"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_root / f"knowledge-{uuid.uuid4().hex}.db"
        self.original_db_path = storage._db_path

        if storage._db is not None:
            await storage.close()

        storage._db_path = self.db_path
        await storage.initialize()

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        self.db_path.unlink(missing_ok=True)
        temp_root = Path(BACKEND_ROOT) / ".tmp-test-data"
        try:
            temp_root.rmdir()
        except OSError:
            pass

    async def test_generic_ingest_persists_and_searches_chunks_without_embeddings(self):
        content = (
            "星云科技提供会议助手私有化部署服务，"
            "交付周期为30天，包含实施、培训与验收支持。"
        ).encode("utf-8")

        result = await self.service.ingest_file(content, "test_kb.txt")

        self.assertEqual(result["status"], "completed")
        self.assertGreater(result["chunks_count"], 0)
        self.assertGreater(await storage.count_knowledge_chunks(source_file="test_kb.txt"), 0)

        results = await hybrid_search.search("星云科技 交付周期", limit=5)
        self.assertTrue(results["structured"])
        self.assertEqual(results["structured"][0]["source_file"], "test_kb.txt")
        self.assertIn("星云科技", results["structured"][0]["content"])
        self.assertIn("chunk_index", results["structured"][0])

        stats = await self.service.get_stats()
        self.assertEqual(stats["total_ppt_imports"], 1)
        self.assertGreater(stats["total_text_chunks"], 0)

    async def test_natural_language_query_without_spaces_recalls_relevant_chunk(self):
        content = (
            "供应商需补充单一来源风险说明。"
            "付款方式为30%预付款，70%验收后支付。"
            "若价格高于历史均价，需要补充偏差解释。"
        ).encode("utf-8")

        result = await self.service.ingest_file(content, "natural_query.txt")

        self.assertEqual(result["status"], "completed")
        results = await hybrid_search.search("请帮我核对付款方式是否合理，并评估单一来源风险是否可接受", limit=5)

        self.assertTrue(results["structured"])
        self.assertEqual(results["structured"][0]["source_file"], "natural_query.txt")
        self.assertIn("付款方式", results["structured"][0]["content"])

    async def test_reupload_completed_legacy_import_backfills_missing_chunks(self):
        content = "阿尔法项目在4月15日完成上线验收。".encode("utf-8")
        file_hash = hashlib.md5(content).hexdigest()

        import_id = await storage.record_ppt_import(
            file_name="legacy.txt",
            file_hash=file_hash,
            file_size=len(content),
            slide_count=0,
        )
        await storage.update_ppt_import_status(import_id, "completed", 0)

        self.assertEqual(await storage.count_knowledge_chunks(import_id=import_id), 0)

        result = await self.service.ingest_file(content, "legacy.txt")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["import_id"], import_id)
        self.assertGreater(await storage.count_knowledge_chunks(import_id=import_id), 0)

    async def test_legacy_imports_without_chunks_return_reindex_notice(self):
        content = "旧版本导入的测试文件。".encode("utf-8")
        file_hash = hashlib.md5(content).hexdigest()

        await storage.record_ppt_import(
            file_name="legacy-only.txt",
            file_hash=file_hash,
            file_size=len(content),
            slide_count=0,
        )

        results = await hybrid_search.search("知识库里有什么", limit=5)

        self.assertTrue(results["structured"])
        self.assertEqual(results["structured"][0]["source_file"], "legacy-only.txt")
        self.assertIn("重新导入一次即可补建索引", results["structured"][0]["content"])

    async def test_delete_import_reuses_safe_vector_delete_helper(self):
        content = b"quoted file"
        file_hash = hashlib.md5(content).hexdigest()
        import_id = await storage.record_ppt_import(
            file_name="quote's.txt",
            file_hash=file_hash,
            file_size=len(content),
            slide_count=0,
        )

        with patch.object(self.service, "_delete_vectors_for_file", AsyncMock(return_value=True)) as delete_mock:
            result = await self.service.delete_import(import_id)

        delete_mock.assert_awaited_once_with("quote's.txt")
        self.assertTrue(result["deleted"])
        self.assertTrue(result["deleted_vectors"])


if __name__ == "__main__":
    unittest.main()
