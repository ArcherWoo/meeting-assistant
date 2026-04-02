from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


BlockType = Literal[
    "document",
    "sheet",
    "slide",
    "title",
    "heading",
    "paragraph",
    "list_item",
    "table",
    "note",
    "image",
    "header",
    "footer",
]


class MergedRange(BaseModel):
    start_row: int
    start_col: int
    end_row: int
    end_col: int

    @property
    def row_span(self) -> int:
        return self.end_row - self.start_row + 1

    @property
    def col_span(self) -> int:
        return self.end_col - self.start_col + 1


class TableCell(BaseModel):
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    value: str = ""
    formula: str | None = None
    is_header: bool = False
    header_path: list[str] = Field(default_factory=list)
    comment: str | None = None


class StructuredTable(BaseModel):
    id: str
    source_block_id: str
    title: str | None = None
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    header_depth: int = 1
    cells: list[TableCell] = Field(default_factory=list)
    merged_ranges: list[MergedRange] = Field(default_factory=list)
    semantic_schema: dict[str, Any] = Field(default_factory=dict)
    row_count: int = 0
    col_count: int = 0


class DocumentBlock(BaseModel):
    id: str
    block_type: BlockType
    text: str = ""
    level: int | None = None
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    parent_id: str | None = None
    table_id: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    semantic_tags: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    doc_id: str
    filename: str
    file_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    blocks: list[DocumentBlock] = Field(default_factory=list)
    tables: list[StructuredTable] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    parser_trace: dict[str, Any] = Field(default_factory=dict)

