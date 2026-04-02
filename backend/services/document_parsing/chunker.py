from __future__ import annotations

import json
from typing import Any

from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument, StructuredTable, TableCell
from services.document_parsing.parsers.common import compact_join, excel_index_to_col, normalize_text
from services.document_parsing.parsers.docx_parser import render_docx_table
from services.document_parsing.parsers.xlsx_parser import render_table_window


def chunk_parsed_document(document: ParsedDocument) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    chunk_index = 1

    table_by_id = {table.id: table for table in document.tables}
    pending_blocks: list[DocumentBlock] = []
    pending_key: tuple[str, str] | None = None

    def flush_pending() -> None:
        nonlocal chunk_index, pending_blocks, pending_key
        if not pending_blocks:
            return
        chunks.append(_render_text_block_group(document, pending_blocks, chunk_index))
        chunk_index += 1
        pending_blocks = []
        pending_key = None

    for block in document.blocks:
        if block.block_type == "table":
            flush_pending()
            table = table_by_id.get(block.table_id or "")
            if table:
                for table_chunk in _chunk_table(table, starting_index=chunk_index):
                    chunks.append(table_chunk)
                    chunk_index += 1
            continue
        key = _block_group_key(block)
        if pending_key is None or key == pending_key:
            pending_blocks.append(block)
            pending_key = key
            continue
        flush_pending()
        pending_blocks.append(block)
        pending_key = key

    flush_pending()

    chunks.sort(key=lambda item: int(item.get("chunk_index") or 0))
    return chunks


def _block_group_key(block: DocumentBlock) -> tuple[str, str]:
    location = (
        block.sheet
        or (f"slide:{block.slide}" if block.slide else "")
        or (f"page:{block.page}" if block.page else "")
        or "document"
    )
    return (location, block.block_type)


def _render_text_block_group(
    document: ParsedDocument,
    blocks: list[DocumentBlock],
    chunk_index: int,
) -> dict[str, Any]:
    content = compact_join(block.text for block in blocks)
    first = blocks[0]
    locator = dict(first.source_locator)
    if first.sheet:
        locator["sheet"] = first.sheet
    if first.slide:
        locator["slide"] = first.slide
    if first.page:
        locator["page"] = first.page
    semantic_tags: list[str] = []
    for block in blocks:
        for tag in block.semantic_tags:
            if tag not in semantic_tags:
                semantic_tags.append(tag)
    return {
        "id": gen_id(),
        "source_file": document.filename,
        "slide_index": first.slide or 0,
        "chunk_type": first.block_type if first.block_type in {"note", "paragraph", "heading", "title", "header", "footer"} else "text",
        "chunk_index": chunk_index,
        "content": content[:4000],
        "char_start": None,
        "char_end": None,
        "metadata_json": json.dumps(
            {
                "file_type": document.file_type,
                "block_type": first.block_type,
                "locator": locator,
                "semantic_tags": semantic_tags,
            },
            ensure_ascii=False,
        ),
    }


def _chunk_table(table: StructuredTable, *, starting_index: int) -> list[dict[str, Any]]:
    if table.sheet:
        return _chunk_sheet_table(table, starting_index=starting_index)
    return [_render_table_as_single_chunk(table, chunk_index=starting_index)]


def _chunk_sheet_table(table: StructuredTable, *, starting_index: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    row_numbers = sorted({cell.row for cell in table.cells if cell.row > table.header_depth})
    if not row_numbers:
        return [_render_table_as_single_chunk(table, chunk_index=starting_index)]

    window_size = 20
    chunk_index = starting_index
    for offset in range(0, len(row_numbers), window_size):
        start_row = row_numbers[offset]
        end_row = row_numbers[min(offset + window_size - 1, len(row_numbers) - 1)]
        content = render_table_window(table, start_row=start_row, end_row=end_row)
        chunks.append({
            "id": gen_id(),
            "source_file": table.title or table.sheet or "table",
            "slide_index": table.slide or 0,
            "chunk_type": "table",
            "chunk_index": chunk_index,
            "content": normalize_text(content)[:5000],
            "char_start": None,
            "char_end": None,
            "metadata_json": json.dumps(
                {
                    "block_type": "table",
                    "locator": {
                        "sheet": table.sheet,
                        "row_start": start_row,
                        "row_end": end_row,
                    },
                    "table": {
                        "title": table.title,
                        "header_depth": table.header_depth,
                        "merged_ranges": [
                            f"{excel_index_to_col(item.start_col)}{item.start_row}:{excel_index_to_col(item.end_col)}{item.end_row}"
                            for item in table.merged_ranges
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        })
        chunk_index += 1
    return chunks


def _render_table_as_single_chunk(table: StructuredTable, *, chunk_index: int) -> dict[str, Any]:
    content = render_docx_table(table) if not table.sheet else render_table_window(table, 1, table.row_count)
    return {
        "id": gen_id(),
        "source_file": table.title or table.sheet or "table",
        "slide_index": table.slide or 0,
        "chunk_type": "table",
        "chunk_index": chunk_index,
        "content": normalize_text(content)[:5000],
        "char_start": None,
        "char_end": None,
        "metadata_json": json.dumps(
            {
                "block_type": "table",
                "locator": {
                    "sheet": table.sheet,
                    "slide": table.slide,
                    "page": table.page,
                },
                "table": {
                    "title": table.title,
                    "header_depth": table.header_depth,
                    "row_count": table.row_count,
                    "col_count": table.col_count,
                },
            },
            ensure_ascii=False,
        ),
    }
