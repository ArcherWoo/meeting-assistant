from __future__ import annotations

import os

from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument, StructuredTable, TableCell
from services.document_parsing.parsers.common import normalize_text
from services.document_parsing.parsers.ocr_utils import (
    build_ocr_structure,
    extract_ocr_layout_from_image_bytes,
    inspect_image_metadata,
)


class ImageParser:
    supported_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        warnings: list[str] = []
        metadata = inspect_image_metadata(file_content, warnings)
        ocr_layout, ocr_engine = extract_ocr_layout_from_image_bytes(file_content, warnings)
        ocr_text = normalize_text(str(ocr_layout.get("text") or ""))
        ocr_structure = build_ocr_structure(
            text=ocr_text,
            lines=list(ocr_layout.get("lines") or []),
            source="ocr",
            include_prefix=True,
        )

        description = self._build_description(filename, len(file_content), metadata, ocr_engine)
        blocks = [
            DocumentBlock(
                id=gen_id(),
                block_type="image",
                text=description,
                source_locator={
                    "filename": filename,
                    "format": metadata.get("format"),
                    "width": metadata.get("width"),
                    "height": metadata.get("height"),
                },
                semantic_tags=["image_asset"],
            )
        ]
        tables: list[StructuredTable] = []

        embedded_text = normalize_text(str(metadata.get("embedded_text") or ""))
        if embedded_text:
            blocks.append(
                DocumentBlock(
                    id=gen_id(),
                    block_type="paragraph",
                    text=f"Image metadata text\n{embedded_text}",
                    source_locator={"filename": filename, "source": "embedded_metadata"},
                    semantic_tags=["image_metadata_text"],
                )
            )

        if ocr_text:
            for table_index, table_payload in enumerate(ocr_structure.get("tables") or [], start=1):
                table_model, table_block = self._build_ocr_table(table_payload, table_index)
                tables.append(table_model)
                blocks.append(table_block)

            for ocr_block in ocr_structure.get("blocks") or []:
                locator = {
                    "filename": filename,
                    "source": "ocr",
                    "engine": ocr_engine,
                    "ocr_segment_index": ocr_block.get("ocr_segment_index"),
                }
                blocks.append(
                    DocumentBlock(
                        id=gen_id(),
                        block_type=str(ocr_block.get("block_type") or "paragraph"),  # type: ignore[arg-type]
                        text=str(ocr_block.get("text") or ""),
                        source_locator=locator,
                        semantic_tags=list(ocr_block.get("semantic_tags") or []),
                    )
                )
        else:
            warnings.append("OCR text was not extracted for this image.")

        return ParsedDocument(
            doc_id=gen_id(),
            filename=filename,
            file_type=os.path.splitext(filename)[1].lower().lstrip(".") or "image",
            metadata={
                "format": metadata.get("format"),
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "mode": metadata.get("mode"),
                "frame_count": metadata.get("frame_count"),
            },
            blocks=blocks,
            tables=tables,
            warnings=warnings,
            parser_trace={
                "parser": "image-metadata-ocr",
                "ocr_engine": ocr_engine,
                "has_embedded_text": bool(embedded_text),
            },
        )

    def _build_ocr_table(
        self,
        table_payload: dict[str, object],
        table_index: int,
    ) -> tuple[StructuredTable, DocumentBlock]:
        table_block_id = gen_id()
        table_id = gen_id()
        rows = list(table_payload.get("rows") or [])
        col_count = max((len(row) for row in rows if isinstance(row, list)), default=0)
        header_depth = 1 if rows else 0
        cells: list[TableCell] = []

        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                continue
            for col_index, value in enumerate(row, start=1):
                text = normalize_text(str(value or ""))
                if not text:
                    continue
                header_path = []
                if row_index > header_depth and rows and isinstance(rows[0], list) and col_index <= len(rows[0]):
                    anchor = normalize_text(str(rows[0][col_index - 1] or ""))
                    header_path = [anchor] if anchor else []
                elif row_index <= header_depth:
                    header_path = [text]
                cells.append(
                    TableCell(
                        row=row_index,
                        col=col_index,
                        value=text,
                        is_header=row_index <= header_depth,
                        header_path=header_path,
                    )
                )

        title = normalize_text(str(table_payload.get("title") or f"OCR Table {table_index}"))
        table_model = StructuredTable(
            id=table_id,
            source_block_id=table_block_id,
            title=title,
            header_depth=header_depth,
            cells=cells,
            row_count=len(rows),
            col_count=col_count,
            semantic_schema={"source": "image_ocr", "detector": "ocr_table"},
        )
        table_block = DocumentBlock(
            id=table_block_id,
            block_type="table",
            text=title,
            table_id=table_id,
            source_locator={"source": "ocr", "table_index": table_index},
            semantic_tags=["ocr_table"],
        )
        return table_model, table_block

    def _build_description(
        self,
        filename: str,
        file_size: int,
        metadata: dict[str, object],
        ocr_engine: str | None,
    ) -> str:
        parts = [f"Image file: {filename}"]
        if metadata.get("format"):
            parts.append(f"format {metadata['format']}")
        if metadata.get("width") and metadata.get("height"):
            parts.append(f"size {metadata['width']}x{metadata['height']}")
        if metadata.get("mode"):
            parts.append(f"mode {metadata['mode']}")
        if metadata.get("frame_count"):
            parts.append(f"frames {metadata['frame_count']}")
        parts.append(f"file_size_kb {file_size / 1024:.1f}")
        parts.append(f"ocr {'enabled' if ocr_engine else 'unavailable'}")
        return ", ".join(parts)
