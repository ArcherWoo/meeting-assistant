from __future__ import annotations

import io
import os
import re
from typing import Any

from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument, StructuredTable, TableCell
from services.document_parsing.parsers.common import compact_join, normalize_text
from services.document_parsing.parsers.ocr_utils import (
    build_ocr_structure,
    extract_ocr_layout_from_image_bytes,
)


LIST_ITEM_RE = re.compile(r"^([-\*\u2022]|\d+[.)])\s+")


class PdfParser:
    supported_extensions = {".pdf"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        warnings: list[str] = []
        pages = self._extract_pages(file_content, warnings)
        blocks: list[DocumentBlock] = []
        tables: list[StructuredTable] = []
        scanned_pages: list[int] = []
        ocr_pages: list[int] = []

        for page_payload in pages:
            page_number = int(page_payload.get("page_number") or 0) or 1
            page_has_blocks = False
            for block_payload in page_payload.get("blocks", []):
                text = normalize_text(str(block_payload.get("text") or ""))
                if not text:
                    continue
                page_has_blocks = True
                semantic_tags = list(block_payload.get("semantic_tags") or [])
                if block_payload.get("source") == "ocr" and "ocr_text" not in semantic_tags:
                    semantic_tags.append("ocr_text")
                blocks.append(
                    DocumentBlock(
                        id=gen_id(),
                        block_type=str(block_payload.get("block_type") or "paragraph"),  # type: ignore[arg-type]
                        text=text,
                        page=page_number,
                        source_locator=self._build_source_locator(page_number, block_payload),
                        semantic_tags=semantic_tags,
                    )
                )

            page_has_tables = False
            for table_index, table_payload in enumerate(page_payload.get("tables", []), start=1):
                table_model, table_block = self._build_table(page_number, table_index, table_payload)
                tables.append(table_model)
                blocks.append(table_block)
                page_has_tables = True

            if page_payload.get("ocr_applied"):
                ocr_pages.append(page_number)

            if not page_has_blocks and not page_has_tables:
                scanned_pages.append(page_number)

        if scanned_pages:
            warnings.append(
                "PDF pages without extractable text detected: "
                + ", ".join(str(page) for page in scanned_pages)
            )

        if not blocks:
            blocks.append(
                DocumentBlock(
                    id=gen_id(),
                    block_type="paragraph",
                    text=f"[PDF file: {filename}, no readable text was extracted. The file may be image-only or scanned.]",
                    page=1,
                    source_locator={"page": 1},
                    semantic_tags=["scanned_pdf"],
                )
            )

        return ParsedDocument(
            doc_id=gen_id(),
            filename=filename,
            file_type=os.path.splitext(filename)[1].lower().lstrip(".") or "pdf",
            metadata={
                "page_count": len(pages),
                "scanned_pages": scanned_pages,
                "ocr_pages": ocr_pages,
            },
            blocks=blocks,
            tables=tables,
            warnings=warnings,
            parser_trace={
                "parser": "pdf-layout-aware",
                "page_count": len(pages),
                "table_count": len(tables),
                "ocr_page_count": len(ocr_pages),
            },
        )

    def _extract_pages(self, file_content: bytes, warnings: list[str]) -> list[dict[str, Any]]:
        pymupdf_pages = self._extract_with_pymupdf(file_content, warnings)
        if pymupdf_pages:
            return pymupdf_pages
        return self._extract_with_pypdf(file_content, warnings)

    def _extract_with_pymupdf(self, file_content: bytes, warnings: list[str]) -> list[dict[str, Any]]:
        try:
            import fitz  # type: ignore
        except Exception as exc:
            warnings.append(f"PyMuPDF unavailable: {exc}")
            return []

        try:
            doc = fitz.open(stream=file_content, filetype="pdf")
        except Exception as exc:
            warnings.append(f"PyMuPDF open failed: {exc}")
            return []

        try:
            pages: list[dict[str, Any]] = []
            for page_number, page in enumerate(doc, start=1):
                page_payload: dict[str, Any] = {
                    "page_number": page_number,
                    "blocks": [],
                    "tables": [],
                    "ocr_applied": False,
                }
                page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
                try:
                    raw_dict = page.get_text("dict", sort=True)
                except Exception as exc:
                    warnings.append(f"PyMuPDF dict extraction failed on page {page_number}: {exc}")
                    raw_dict = {}

                text_blocks = self._extract_layout_blocks(raw_dict, page_number, page_height)
                if text_blocks:
                    page_payload["blocks"] = text_blocks
                else:
                    plain_text = normalize_text(page.get_text() or "")
                    if plain_text:
                        page_payload["blocks"] = self._split_plain_page_text(plain_text, page_number)

                table_payloads = self._extract_tables_from_page(page, page_number, warnings)
                if table_payloads:
                    page_payload["tables"] = table_payloads

                self._apply_page_ocr_if_needed(page, page_payload, page_number, warnings)
                pages.append(page_payload)
            return pages
        finally:
            doc.close()

    def _apply_page_ocr_if_needed(
        self,
        page: Any,
        page_payload: dict[str, Any],
        page_number: int,
        warnings: list[str],
    ) -> None:
        if page_payload.get("blocks") or page_payload.get("tables"):
            return

        image_bytes = self._render_page_image(page, page_number, warnings)
        if not image_bytes:
            return

        ocr_layout, ocr_engine = extract_ocr_layout_from_image_bytes(image_bytes, warnings)
        ocr_text = normalize_text(str(ocr_layout.get("text") or ""))
        if not ocr_text:
            return

        ocr_structure = build_ocr_structure(
            text=ocr_text,
            lines=list(ocr_layout.get("lines") or []),
            source="ocr",
            include_prefix=True,
        )

        page_payload["blocks"] = []
        page_payload["tables"] = list(page_payload.get("tables") or [])
        for table_payload in ocr_structure.get("tables") or []:
            table_payload["title"] = table_payload.get("title") or f"PDF Page {page_number} OCR Table"
            table_payload["source"] = "ocr"
            page_payload["tables"].append(table_payload)

        for ocr_block in ocr_structure.get("blocks") or []:
            semantic_tags = list(ocr_block.get("semantic_tags") or [])
            if "scanned_pdf" not in semantic_tags:
                semantic_tags.append("scanned_pdf")
            page_payload["blocks"].append(
                {
                    "block_type": ocr_block.get("block_type") or "paragraph",
                    "text": ocr_block.get("text") or "",
                    "semantic_tags": semantic_tags,
                    "source": "ocr",
                    "ocr_engine": ocr_engine,
                    "ocr_segment_index": ocr_block.get("ocr_segment_index"),
                }
            )
        page_payload["ocr_applied"] = True

    def _render_page_image(
        self,
        page: Any,
        page_number: int,
        warnings: list[str],
    ) -> bytes:
        try:
            try:
                import fitz  # type: ignore

                matrix = fitz.Matrix(2.0, 2.0)
            except Exception:
                matrix = None
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            if hasattr(pixmap, "tobytes"):
                return pixmap.tobytes("png")
            if hasattr(pixmap, "pil_tobytes"):
                return pixmap.pil_tobytes(format="PNG")
        except Exception as exc:
            warnings.append(f"PDF OCR rendering failed on page {page_number}: {exc}")
        return b""

    def _extract_layout_blocks(
        self,
        raw_dict: dict[str, Any],
        page_number: int,
        page_height: float,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        text_block_index = 0
        for block in raw_dict.get("blocks", []):
            if int(block.get("type", 0) or 0) != 0:
                continue
            lines: list[str] = []
            font_sizes: list[float] = []
            for line in block.get("lines", []):
                line_text_parts: list[str] = []
                for span in line.get("spans", []):
                    span_text = str(span.get("text") or "")
                    if span_text:
                        line_text_parts.append(span_text)
                    span_size = span.get("size")
                    if isinstance(span_size, (int, float)):
                        font_sizes.append(float(span_size))
                line_text = normalize_text("".join(line_text_parts))
                if line_text:
                    lines.append(line_text)
            text = compact_join(lines)
            if not text:
                continue

            text_block_index += 1
            avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0.0
            block_type = self._classify_text_block(
                text=text,
                page_number=page_number,
                block_index=text_block_index,
                avg_font_size=avg_font_size,
                page_height=page_height,
                bbox=block.get("bbox"),
            )
            semantic_tags: list[str] = []
            if block_type in {"title", "heading"}:
                semantic_tags.append("section_header")
            if LIST_ITEM_RE.match(text):
                semantic_tags.append("list_like")

            blocks.append(
                {
                    "block_type": block_type,
                    "text": text,
                    "bbox": self._normalize_bbox(block.get("bbox")),
                    "font_size": avg_font_size,
                    "semantic_tags": semantic_tags,
                }
            )
        return blocks

    def _classify_text_block(
        self,
        *,
        text: str,
        page_number: int,
        block_index: int,
        avg_font_size: float,
        page_height: float,
        bbox: Any,
    ) -> str:
        if LIST_ITEM_RE.match(text):
            return "list_item"

        y_top = 0.0
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 2:
            try:
                y_top = float(bbox[1])
            except (TypeError, ValueError):
                y_top = 0.0

        short_single_line = len(text) <= 80 and "\n" not in text
        near_top = page_height > 0 and y_top <= page_height * 0.18

        if page_number == 1 and block_index == 1 and short_single_line and avg_font_size >= 14:
            return "title"
        if short_single_line and (avg_font_size >= 12.5 or near_top):
            return "heading"
        return "paragraph"

    def _extract_tables_from_page(
        self,
        page: Any,
        page_number: int,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if not hasattr(page, "find_tables"):
            return []

        try:
            finder = page.find_tables()
        except Exception as exc:
            warnings.append(f"PyMuPDF table detection failed on page {page_number}: {exc}")
            return []

        tables = list(getattr(finder, "tables", []) or [])
        extracted: list[dict[str, Any]] = []
        for table_index, table in enumerate(tables, start=1):
            try:
                matrix = table.extract()
            except Exception as exc:
                warnings.append(f"PyMuPDF table extraction failed on page {page_number} table {table_index}: {exc}")
                continue
            cleaned_rows: list[list[str]] = []
            for row in matrix or []:
                cleaned_rows.append([normalize_text(str(cell or "")) for cell in row])
            if not any(any(cell for cell in row) for row in cleaned_rows):
                continue
            extracted.append(
                {
                    "title": f"PDF Page {page_number} Table {table_index}",
                    "rows": cleaned_rows,
                    "bbox": self._normalize_bbox(getattr(table, "bbox", None)),
                }
            )
        return extracted

    def _extract_with_pypdf(self, file_content: bytes, warnings: list[str]) -> list[dict[str, Any]]:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as exc:
            warnings.append(f"pypdf unavailable: {exc}")
            return []

        try:
            reader = PdfReader(io.BytesIO(file_content))
        except Exception as exc:
            warnings.append(f"pypdf open failed: {exc}")
            return []

        pages: list[dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = normalize_text(page.extract_text() or "")
            except Exception as exc:
                warnings.append(f"pypdf text extraction failed on page {page_number}: {exc}")
                text = ""
            page_payload = {
                "page_number": page_number,
                "blocks": self._split_plain_page_text(text, page_number) if text else [],
                "tables": [],
                "ocr_applied": False,
            }
            pages.append(page_payload)
        return pages

    def _split_plain_page_text(self, text: str, page_number: int) -> list[dict[str, Any]]:
        segments = [normalize_text(segment) for segment in re.split(r"\n\s*\n", text) if normalize_text(segment)]
        if not segments and text:
            segments = [text]

        blocks: list[dict[str, Any]] = []
        for block_index, segment in enumerate(segments, start=1):
            lines = [normalize_text(line) for line in segment.split("\n") if normalize_text(line)]
            if not lines:
                continue
            line_count = len(lines)
            first_line = lines[0]
            block_type = "paragraph"
            if LIST_ITEM_RE.match(first_line):
                block_type = "list_item"
            elif block_index == 1 and page_number == 1 and line_count == 1 and len(first_line) <= 80:
                block_type = "title"
            elif line_count == 1 and len(first_line) <= 80:
                block_type = "heading"

            blocks.append(
                {
                    "block_type": block_type,
                    "text": compact_join(lines),
                    "semantic_tags": ["fallback_text"],
                }
            )
        return blocks

    def _build_table(
        self,
        page_number: int,
        table_index: int,
        table_payload: dict[str, Any],
    ) -> tuple[StructuredTable, DocumentBlock]:
        table_block_id = gen_id()
        table_id = gen_id()
        rows = list(table_payload.get("rows") or [])
        col_count = max((len(row) for row in rows), default=0)
        header_depth = 1 if rows else 0
        cells: list[TableCell] = []

        for row_index, row in enumerate(rows, start=1):
            for col_index, value in enumerate(row, start=1):
                if not normalize_text(value):
                    continue
                header_path = [normalize_text(row[col_index - 1])] if row_index == 1 and col_index <= len(row) else []
                if row_index > header_depth and rows and col_index <= len(rows[0]):
                    anchor = normalize_text(rows[0][col_index - 1])
                    header_path = [anchor] if anchor else []
                cells.append(
                    TableCell(
                        row=row_index,
                        col=col_index,
                        value=normalize_text(value),
                        is_header=row_index <= header_depth,
                        header_path=header_path,
                    )
                )

        title = normalize_text(str(table_payload.get("title") or f"PDF Page {page_number} Table {table_index}"))
        table_model = StructuredTable(
            id=table_id,
            source_block_id=table_block_id,
            title=title,
            page=page_number,
            header_depth=header_depth,
            cells=cells,
            row_count=len(rows),
            col_count=col_count,
            semantic_schema={
                "source": "pdf",
                "detector": str(table_payload.get("source") or "layout_table"),
            },
        )
        table_block = DocumentBlock(
            id=table_block_id,
            block_type="table",
            text=title,
            page=page_number,
            table_id=table_id,
            source_locator={
                "page": page_number,
                "table_index": table_index,
                "bbox": table_payload.get("bbox"),
                "source": table_payload.get("source"),
            },
            semantic_tags=["table_block", str(table_payload.get("source") or "layout_table")],
        )
        return table_model, table_block

    def _build_source_locator(self, page_number: int, block_payload: dict[str, Any]) -> dict[str, Any]:
        locator: dict[str, Any] = {"page": page_number}
        bbox = block_payload.get("bbox")
        if bbox:
            locator["bbox"] = bbox
        font_size = block_payload.get("font_size")
        if isinstance(font_size, (int, float)) and font_size > 0:
            locator["font_size"] = round(float(font_size), 2)
        if block_payload.get("source"):
            locator["source"] = block_payload["source"]
        if block_payload.get("ocr_engine"):
            locator["ocr_engine"] = block_payload["ocr_engine"]
        if block_payload.get("ocr_segment_index"):
            locator["ocr_segment_index"] = block_payload["ocr_segment_index"]
        return locator

    def _normalize_bbox(self, bbox: Any) -> list[float] | None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            return None
        normalized: list[float] = []
        for value in bbox[:4]:
            try:
                normalized.append(round(float(value), 2))
            except (TypeError, ValueError):
                return None
        return normalized
