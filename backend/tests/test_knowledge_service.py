import hashlib
import io
import json
import os
import sys
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.hybrid_search import hybrid_search
from services.context_assembler import AssembledContext
from services.document_parsing.prompt_render import render_document_for_prompt
from services.document_parsing.parsers.image_parser import ImageParser
from services.document_parsing.parsers.ocr_utils import build_ocr_structure, segment_ocr_text
from services.document_parsing.parsers.pdf_parser import PdfParser
from services.document_parsing.registry import document_parser_registry
from services.knowledge_service import KnowledgeService
from services.retrieval_planner import RetrievalPlannerSettings
from services.storage import storage
from services.embedding_service import embedding_service


def build_test_xlsx_bytes() -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>
"""
    root_rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
    workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Pricing" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""
    workbook_rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
    shared_strings = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="7" uniqueCount="7">
  <si><t>Quote Matrix</t></si>
  <si><t>Hardware</t></si>
  <si><t>Service</t></si>
  <si><t>Model</t></si>
  <si><t>Unit Price</t></si>
  <si><t>Implementation</t></si>
  <si><t>Server</t></si>
</sst>
"""
    worksheet_xml = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:C4"/>
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>1</v></c>
      <c r="C2" t="s"><v>2</v></c>
    </row>
    <row r="3">
      <c r="A3" t="s"><v>3</v></c>
      <c r="B3" t="s"><v>4</v></c>
      <c r="C3" t="s"><v>5</v></c>
    </row>
    <row r="4">
      <c r="A4" t="s"><v>6</v></c>
      <c r="B4"><v>12000</v></c>
      <c r="C4"><f>1000+2000</f><v>3000</v></c>
    </row>
  </sheetData>
  <mergeCells count="2">
    <mergeCell ref="A1:C1"/>
    <mergeCell ref="A2:B2"/>
  </mergeCells>
</worksheet>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
    return buffer.getvalue()


def build_test_docx_bytes() -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    root_rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Project Outline</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Intro paragraph</w:t></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Section</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Detail</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Attachments</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Structured parsing</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <w:r><w:t>Closing note</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


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


class DocumentParsingTests(unittest.IsolatedAsyncioTestCase):
    def test_segment_ocr_text_splits_title_paragraph_and_list(self):
        blocks = segment_ocr_text(
            "Procurement Summary\n\nThe first paragraph explains the scope.\n\n1. Delivery in 10 days",
            include_prefix=True,
        )

        self.assertEqual([block["block_type"] for block in blocks], ["title", "paragraph", "list_item"])
        self.assertTrue(blocks[0]["text"].startswith("OCR text\nProcurement Summary"))
        self.assertIn("list_like", blocks[2]["semantic_tags"])

    def test_build_ocr_structure_recovers_table_from_layout_lines(self):
        structure = build_ocr_structure(
            text="Budget Table\nItem Amount\nServer 12000\nStorage 8000\nNotes follow",
            lines=[
                {"text": "Budget Table", "words": [{"text": "Budget", "left": 10, "top": 10, "width": 40, "height": 10}, {"text": "Table", "left": 56, "top": 10, "width": 34, "height": 10}]},
                {"text": "Item Amount", "words": [{"text": "Item", "left": 10, "top": 30, "width": 25, "height": 10}, {"text": "Amount", "left": 180, "top": 30, "width": 45, "height": 10}]},
                {"text": "Server 12000", "words": [{"text": "Server", "left": 10, "top": 50, "width": 40, "height": 10}, {"text": "12000", "left": 180, "top": 50, "width": 35, "height": 10}]},
                {"text": "Storage 8000", "words": [{"text": "Storage", "left": 10, "top": 70, "width": 45, "height": 10}, {"text": "8000", "left": 180, "top": 70, "width": 28, "height": 10}]},
                {"text": "Notes follow", "words": [{"text": "Notes", "left": 10, "top": 95, "width": 32, "height": 10}, {"text": "follow", "left": 48, "top": 95, "width": 34, "height": 10}]},
            ],
            include_prefix=True,
        )

        self.assertEqual(len(structure["tables"]), 1)
        self.assertEqual(structure["tables"][0]["title"], "Budget Table")
        self.assertEqual(structure["tables"][0]["rows"][1], ["Server", "12000"])
        self.assertTrue(structure["blocks"])
        self.assertIn("Notes follow", structure["blocks"][0]["text"])

    async def test_pdf_parser_preserves_layout_blocks_and_tables(self):
        parser = PdfParser()
        mocked_pages = [
            {
                "page_number": 1,
                "blocks": [
                    {
                        "block_type": "title",
                        "text": "Procurement Report",
                        "bbox": [40.0, 50.0, 320.0, 82.0],
                        "font_size": 18.0,
                        "semantic_tags": ["section_header"],
                    },
                    {
                        "block_type": "paragraph",
                        "text": "Summary paragraph",
                        "bbox": [40.0, 120.0, 420.0, 210.0],
                        "font_size": 10.5,
                        "semantic_tags": [],
                    },
                ],
                "tables": [
                    {
                        "title": "Page 1 Budget",
                        "rows": [
                            ["Item", "Amount"],
                            ["Server", "12000"],
                        ],
                        "bbox": [40.0, 240.0, 420.0, 360.0],
                    }
                ],
            }
        ]

        with patch.object(parser, "_extract_pages", return_value=mocked_pages):
            parsed = await parser.parse(b"%PDF-1.4", "report.pdf")

        self.assertEqual(parsed.metadata["page_count"], 1)
        self.assertEqual([block.block_type for block in parsed.blocks], ["title", "paragraph", "table"])
        self.assertEqual(parsed.blocks[0].source_locator["page"], 1)
        self.assertEqual(parsed.blocks[0].source_locator["font_size"], 18.0)
        self.assertEqual(len(parsed.tables), 1)
        amount_cell = next(cell for cell in parsed.tables[0].cells if cell.row == 2 and cell.col == 2)
        self.assertEqual(amount_cell.header_path, ["Amount"])

        prompt = render_document_for_prompt(parsed)
        self.assertLess(prompt.index("Procurement Report"), prompt.index("Summary paragraph"))
        self.assertIn("Amount=12000", prompt)

    def test_pdf_parser_adds_ocr_block_for_scanned_page(self):
        parser = PdfParser()
        page_payload = {"page_number": 2, "blocks": [], "tables": [], "ocr_applied": False}

        with patch.object(parser, "_render_page_image", return_value=b"png-bytes"):
            with patch(
                "services.document_parsing.parsers.pdf_parser.extract_ocr_layout_from_image_bytes",
                return_value=(
                    {
                        "text": "Scanned contract\nItem Amount\nServer 12000\nStorage 8000",
                        "lines": [
                            {"text": "Scanned contract", "words": [{"text": "Scanned", "left": 10, "top": 10, "width": 40, "height": 10}, {"text": "contract", "left": 58, "top": 10, "width": 42, "height": 10}]},
                            {"text": "Item Amount", "words": [{"text": "Item", "left": 10, "top": 30, "width": 24, "height": 10}, {"text": "Amount", "left": 180, "top": 30, "width": 44, "height": 10}]},
                            {"text": "Server 12000", "words": [{"text": "Server", "left": 10, "top": 50, "width": 38, "height": 10}, {"text": "12000", "left": 180, "top": 50, "width": 36, "height": 10}]},
                            {"text": "Storage 8000", "words": [{"text": "Storage", "left": 10, "top": 70, "width": 42, "height": 10}, {"text": "8000", "left": 180, "top": 70, "width": 28, "height": 10}]},
                        ],
                    },
                    "tesseract",
                ),
            ):
                parser._apply_page_ocr_if_needed(Mock(), page_payload, 2, [])

        self.assertTrue(page_payload["ocr_applied"])
        self.assertEqual(page_payload["blocks"][0]["source"], "ocr")
        self.assertEqual([block["block_type"] for block in page_payload["blocks"]], ["title"])
        self.assertIn("Scanned contract", page_payload["blocks"][0]["text"])
        self.assertEqual(len(page_payload["tables"]), 1)
        self.assertEqual(page_payload["tables"][0]["rows"][1], ["Server", "12000"])

    async def test_xlsx_parser_preserves_merged_ranges_and_header_paths(self):
        parsed = await document_parser_registry.parse(build_test_xlsx_bytes(), "pricing.xlsx")

        self.assertEqual(parsed.file_type, "xlsx")
        self.assertEqual(parsed.metadata["sheet_count"], 1)
        self.assertEqual(len(parsed.tables), 1)

        table = parsed.tables[0]
        self.assertEqual(table.sheet, "Pricing")
        self.assertEqual(table.header_depth, 3)
        self.assertEqual(
            [(item.start_row, item.start_col, item.end_row, item.end_col) for item in table.merged_ranges],
            [(1, 1, 1, 3), (2, 1, 2, 2)],
        )

        price_cell = next(cell for cell in table.cells if cell.row == 4 and cell.col == 2)
        impl_cell = next(cell for cell in table.cells if cell.row == 4 and cell.col == 3)
        self.assertEqual(price_cell.header_path, ["Quote Matrix", "Hardware", "Unit Price"])
        self.assertEqual(impl_cell.header_path, ["Quote Matrix", "Service", "Implementation"])
        self.assertEqual(impl_cell.formula, "1000+2000")

        prompt = render_document_for_prompt(parsed)
        self.assertIn("A1:C1", prompt)
        self.assertIn("Quote Matrix > Hardware > Unit Price=12000", prompt)
        self.assertIn("Quote Matrix > Service > Implementation=3000 (formula=1000+2000)", prompt)

    async def test_docx_parser_keeps_paragraph_table_order(self):
        parsed = await document_parser_registry.parse(build_test_docx_bytes(), "outline.docx")

        self.assertEqual(len(parsed.tables), 1)
        self.assertEqual(
            [block.block_type for block in parsed.blocks],
            ["heading", "paragraph", "table", "paragraph"],
        )

        detail_cell = next(cell for cell in parsed.tables[0].cells if cell.row == 2 and cell.col == 2)
        self.assertEqual(detail_cell.header_path, ["Detail"])

        prompt = render_document_for_prompt(parsed)
        self.assertLess(prompt.index("Project Outline"), prompt.index("Intro paragraph"))
        self.assertLess(prompt.index("Intro paragraph"), prompt.index("Structured parsing"))
        self.assertLess(prompt.index("Structured parsing"), prompt.index("Closing note"))

    async def test_image_parser_includes_metadata_and_ocr_blocks(self):
        with patch(
            "services.document_parsing.parsers.image_parser.inspect_image_metadata",
            return_value={
                "format": "PNG",
                "width": 1280,
                "height": 720,
                "mode": "RGB",
                "frame_count": 1,
                "embedded_text": "diagram note",
            },
        ):
            with patch(
                "services.document_parsing.parsers.image_parser.extract_ocr_layout_from_image_bytes",
                return_value=(
                    {
                        "text": "recognized heading\n\nrecognized text",
                        "lines": [
                            {"text": "recognized heading", "words": [{"text": "recognized", "left": 10, "top": 10, "width": 60, "height": 10}, {"text": "heading", "left": 76, "top": 10, "width": 42, "height": 10}]},
                            {"text": "recognized text", "words": [{"text": "recognized", "left": 10, "top": 30, "width": 60, "height": 10}, {"text": "text", "left": 76, "top": 30, "width": 20, "height": 10}]},
                        ],
                    },
                    "tesseract",
                ),
            ):
                parser = ImageParser()
                parsed = await parser.parse(b"fake-image", "diagram.png")

        self.assertEqual(parsed.metadata["format"], "PNG")
        self.assertEqual([block.block_type for block in parsed.blocks], ["image", "paragraph", "title"])
        self.assertIn("1280x720", parsed.blocks[0].text)
        self.assertIn("diagram note", parsed.blocks[1].text)
        self.assertIn("recognized heading", parsed.blocks[2].text)
        self.assertIn("recognized text", parsed.blocks[2].text)
        self.assertEqual(parsed.parser_trace["ocr_engine"], "tesseract")

    def test_context_assembler_builds_locator_rich_knowledge_citation(self):
        citation = AssembledContext._build_knowledge_citation(
            {
                "id": "chunk-1",
                "source_file": "pricing.xlsx",
                "chunk_type": "table",
                "content": "报价片段",
                "sheet": "Pricing",
                "row_start": 4,
                "row_end": 8,
                "chunk_index": 3,
                "table_title": "Budget Table",
                "source": "ocr",
                "ocr_segment_index": 2,
            },
            1,
        )

        self.assertEqual(citation["sheet"], "Pricing")
        self.assertEqual(citation["row_start"], 4)
        self.assertIn("工作表 Pricing", citation["location"])
        self.assertIn("行 4-8", citation["location"])
        self.assertIn("OCR 恢复", citation["location"])


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


    async def test_search_uses_llm_rerank_fallback_when_semantic_is_unavailable(self):
        candidates = [
            {
                "id": "chunk-1",
                "source_file": "pricing.txt",
                "content": "付款方式为 30% 预付款，70% 验收后支付",
            },
            {
                "id": "chunk-2",
                "source_file": "summary.txt",
                "content": "项目背景与交付计划概述",
            },
        ]

        with patch.object(hybrid_search, "_structured_search", AsyncMock(return_value=[])):
            with patch.object(hybrid_search, "_text_search", AsyncMock(return_value=candidates)):
                with patch.object(hybrid_search, "_semantic_search", AsyncMock(return_value=[])):
                    with patch.object(
                        hybrid_search._llm_service,
                        "chat",
                        AsyncMock(return_value={
                            "choices": [{
                                "message": {
                                    "content": '{"selected_ids":["chunk-1"],"notes":"付款相关最匹配"}',
                                }
                            }]
                        }),
                    ) as chat_mock:
                        with patch.object(
                            hybrid_search._llm_service,
                            "extract_text_content",
                            return_value='{"selected_ids":["chunk-1"],"notes":"付款相关最匹配"}',
                        ):
                            results = await hybrid_search.search(
                                "请核对付款方式是否合理",
                                limit=5,
                                llm_settings=RetrievalPlannerSettings(
                                    api_url="https://example.com/v1",
                                    api_key="sk-test",
                                    model="deepseek-chat",
                                ),
                            )

        chat_mock.assert_awaited_once()
        self.assertEqual([item["id"] for item in results["structured"]], ["chunk-1"])
        self.assertEqual(results["structured"][0]["rerank_strategy"], "llm_fallback")


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

    async def test_xlsx_ingest_persists_structured_chunk_metadata(self):
        result = await self.service.ingest_file(build_test_xlsx_bytes(), "pricing.xlsx")

        self.assertEqual(result["status"], "completed")
        self.assertTrue(any("merged ranges" in warning for warning in result["warnings"]))

        row = await storage._fetchone(
            "SELECT metadata_json, content FROM knowledge_chunks WHERE import_id=? AND chunk_type='table' ORDER BY chunk_index LIMIT 1",
            (result["import_id"],),
        )
        self.assertIsNotNone(row)

        metadata = json.loads(row["metadata_json"])
        self.assertEqual(metadata["locator"]["sheet"], "Pricing")
        self.assertEqual(metadata["locator"]["row_start"], 4)
        self.assertEqual(metadata["locator"]["row_end"], 4)
        self.assertEqual(metadata["table"]["merged_ranges"], ["A1:C1", "A2:B2"])
        self.assertIn("Quote Matrix > Hardware > Unit Price=12000", row["content"])


if __name__ == "__main__":
    unittest.main()
