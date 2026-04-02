from __future__ import annotations

import os

from services.ppt_parser import PPTParser
from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument, StructuredTable, TableCell


class PptDocumentParser:
    supported_extensions = {".ppt", ".pptx"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        parser = PPTParser()
        parsed = await parser.parse(file_content, filename)

        blocks: list[DocumentBlock] = []
        tables: list[StructuredTable] = []
        for slide in parsed.get("slides", []):
            slide_index = int(slide.get("index", 0) or 0)
            slide_title = str(slide.get("title") or f"幻灯片 {slide_index}").strip()
            slide_block_id = gen_id()
            blocks.append(
                DocumentBlock(
                    id=slide_block_id,
                    block_type="slide",
                    text=slide_title,
                    slide=slide_index,
                    source_locator={"slide": slide_index},
                )
            )
            if slide.get("title"):
                blocks.append(
                    DocumentBlock(
                        id=gen_id(),
                        block_type="title",
                        text=slide_title,
                        slide=slide_index,
                        parent_id=slide_block_id,
                        source_locator={"slide": slide_index},
                    )
                )
            for text in slide.get("texts", []):
                normalized = str(text or "").strip()
                if not normalized or normalized == slide_title:
                    continue
                blocks.append(
                    DocumentBlock(
                        id=gen_id(),
                        block_type="paragraph",
                        text=normalized,
                        slide=slide_index,
                        parent_id=slide_block_id,
                        source_locator={"slide": slide_index},
                    )
                )

            for table_index, table in enumerate(slide.get("tables", []), start=1):
                table_block_id = gen_id()
                table_id = gen_id()
                rows = table.get("rows", []) or []
                cells: list[TableCell] = []
                for row_idx, row in enumerate(rows, start=1):
                    for col_idx, value in enumerate(row, start=1):
                        cells.append(
                            TableCell(
                                row=row_idx,
                                col=col_idx,
                                value=str(value or "").strip(),
                                is_header=row_idx == 1,
                                header_path=[str(rows[0][col_idx - 1]).strip()] if row_idx > 1 and rows and col_idx - 1 < len(rows[0]) and str(rows[0][col_idx - 1]).strip() else [],
                            )
                        )
                tables.append(
                    StructuredTable(
                        id=table_id,
                        source_block_id=table_block_id,
                        title=f"{slide_title} 表格 {table_index}",
                        slide=slide_index,
                        header_depth=1 if rows else 0,
                        cells=cells,
                        row_count=len(rows),
                        col_count=max((len(row) for row in rows), default=0),
                    )
                )
                blocks.append(
                    DocumentBlock(
                        id=table_block_id,
                        block_type="table",
                        text=f"{slide_title} 表格 {table_index}",
                        slide=slide_index,
                        table_id=table_id,
                        parent_id=slide_block_id,
                        source_locator={"slide": slide_index, "table_index": table_index},
                    )
                )

            notes = str(slide.get("notes") or "").strip()
            if notes:
                blocks.append(
                    DocumentBlock(
                        id=gen_id(),
                        block_type="note",
                        text=notes,
                        slide=slide_index,
                        parent_id=slide_block_id,
                        source_locator={"slide": slide_index},
                    )
                )

        return ParsedDocument(
            doc_id=gen_id(),
            filename=filename,
            file_type=os.path.splitext(filename)[1].lower().lstrip(".") or "pptx",
            metadata=parsed.get("metadata", {}),
            blocks=blocks,
            tables=tables,
            parser_trace={"parser": "python-pptx-adapter", "legacy_parser": parsed.get("extraction_stats", {}).get("parser", "")},
        )

