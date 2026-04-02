from __future__ import annotations

import io
import os
import zipfile
from collections import defaultdict
from typing import Any
from xml.etree import ElementTree as ET

from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument, StructuredTable, TableCell
from services.document_parsing.parsers.common import compact_join, normalize_text


NS_W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
NS_REL = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


class DocxParser:
    supported_extensions = {".docx"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        archive = zipfile.ZipFile(io.BytesIO(file_content))
        try:
            blocks: list[DocumentBlock] = []
            tables: list[StructuredTable] = []
            warnings: list[str] = []

            rels = self._load_relationships(archive, "word/_rels/document.xml.rels")
            blocks.extend(self._parse_related_story(archive, rels, "header", "header"))

            document_root = ET.fromstring(archive.read("word/document.xml"))
            body = document_root.find("w:body", NS_W)
            if body is not None:
                for child in body:
                    tag = self._strip_ns(child.tag)
                    if tag == "p":
                        block = self._parse_paragraph(child)
                        if block:
                            blocks.append(block)
                    elif tag == "tbl":
                        table, table_block = self._parse_table(child)
                        tables.append(table)
                        blocks.append(table_block)

            blocks.extend(self._parse_related_story(archive, rels, "footer", "footer"))
            return ParsedDocument(
                doc_id=gen_id(),
                filename=filename,
                file_type=os.path.splitext(filename)[1].lower().lstrip(".") or "docx",
                blocks=blocks,
                tables=tables,
                warnings=warnings,
                parser_trace={"parser": "docx-ooxml", "table_count": len(tables)},
            )
        finally:
            archive.close()

    def _load_relationships(self, archive: zipfile.ZipFile, rels_path: str) -> dict[str, str]:
        try:
            root = ET.fromstring(archive.read(rels_path))
        except KeyError:
            return {}
        rels: dict[str, str] = {}
        for rel in root.findall("pr:Relationship", NS_REL):
            rel_type = rel.attrib.get("Type", "")
            target = rel.attrib.get("Target", "")
            if rel_type and target:
                rels[rel_type.rsplit("/", 1)[-1]] = target.lstrip("/")
        return rels

    def _parse_related_story(
        self,
        archive: zipfile.ZipFile,
        rels: dict[str, str],
        story_key: str,
        block_type: str,
    ) -> list[DocumentBlock]:
        target = rels.get(story_key)
        if not target:
            return []
        path = target if target.startswith("word/") else f"word/{target}"
        try:
            root = ET.fromstring(archive.read(path))
        except KeyError:
            return []
        text = compact_join(
            normalize_text("".join(node.text or "" for node in paragraph.findall(".//w:t", NS_W)))
            for paragraph in root.findall(".//w:p", NS_W)
        )
        if not text:
            return []
        return [
            DocumentBlock(
                id=gen_id(),
                block_type=block_type,  # type: ignore[arg-type]
                text=text,
                source_locator={"story": story_key},
            )
        ]

    def _parse_paragraph(self, paragraph: ET.Element) -> DocumentBlock | None:
        text = self._paragraph_text(paragraph)
        if not text:
            return None
        style_node = paragraph.find("w:pPr/w:pStyle", NS_W)
        style_val = style_node.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") if style_node is not None else ""
        style_name = (style_val or "").lower()
        level = None
        block_type: str = "paragraph"
        if style_name.startswith("heading"):
            suffix = style_name.replace("heading", "")
            if suffix.isdigit():
                level = int(suffix)
            block_type = "heading"
        elif paragraph.find("w:pPr/w:numPr", NS_W) is not None:
            block_type = "list_item"
        return DocumentBlock(
            id=gen_id(),
            block_type=block_type,  # type: ignore[arg-type]
            text=text,
            level=level,
            source_locator={"style": style_val or ""},
        )

    def _parse_table(self, table: ET.Element) -> tuple[StructuredTable, DocumentBlock]:
        table_block_id = gen_id()
        table_id = gen_id()
        cells: list[TableCell] = []
        active_vertical: dict[int, TableCell] = {}
        max_col = 0
        row_index = 0

        for row in table.findall("w:tr", NS_W):
            row_index += 1
            col_index = 1
            current_row_vertical_touched: set[int] = set()
            for tc in row.findall("w:tc", NS_W):
                while col_index in active_vertical and col_index not in current_row_vertical_touched:
                    col_index += 1

                tc_pr = tc.find("w:tcPr", NS_W)
                grid_span = 1
                v_merge = None
                if tc_pr is not None:
                    grid_span_node = tc_pr.find("w:gridSpan", NS_W)
                    if grid_span_node is not None:
                        grid_span = int(grid_span_node.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "1"))
                    v_merge_node = tc_pr.find("w:vMerge", NS_W)
                    if v_merge_node is not None:
                        v_merge = v_merge_node.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "continue")

                text = compact_join((self._paragraph_text(p) for p in tc.findall("w:p", NS_W)), sep="\n")

                if v_merge == "continue":
                    for merged_col in range(col_index, col_index + grid_span):
                        anchor = active_vertical.get(merged_col)
                        if anchor:
                            anchor.row_span += 1
                            current_row_vertical_touched.add(merged_col)
                    col_index += grid_span
                    continue

                cell = TableCell(
                    row=row_index,
                    col=col_index,
                    col_span=grid_span,
                    value=text,
                    is_header=row_index == 1,
                )
                cells.append(cell)
                if v_merge == "restart":
                    for merged_col in range(col_index, col_index + grid_span):
                        active_vertical[merged_col] = cell
                        current_row_vertical_touched.add(merged_col)
                else:
                    for merged_col in range(col_index, col_index + grid_span):
                        active_vertical.pop(merged_col, None)
                max_col = max(max_col, col_index + grid_span - 1)
                col_index += grid_span

        header_labels = {cell.col: cell.value for cell in cells if cell.row == 1 and cell.value}
        for cell in cells:
            if cell.row > 1 and cell.col in header_labels:
                cell.header_path = [header_labels[cell.col]]

        title = next((cell.value for cell in cells if cell.row == 1 and cell.value), "DOCX 表格")
        table_model = StructuredTable(
            id=table_id,
            source_block_id=table_block_id,
            title=title,
            header_depth=1 if any(cell.row == 1 for cell in cells) else 0,
            cells=cells,
            row_count=row_index,
            col_count=max_col,
            semantic_schema={"source": "docx"},
        )
        block = DocumentBlock(
            id=table_block_id,
            block_type="table",
            text=title,
            table_id=table_id,
            source_locator={"rows": row_index, "cols": max_col},
        )
        return table_model, block

    def _paragraph_text(self, paragraph: ET.Element) -> str:
        parts: list[str] = []
        for node in paragraph.iter():
            tag = self._strip_ns(node.tag)
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag in {"br", "cr"}:
                parts.append("\n")
        return normalize_text("".join(parts))

    @staticmethod
    def _strip_ns(tag: str) -> str:
        return tag.split("}", 1)[-1]


def render_docx_table(table: StructuredTable) -> str:
    rows: dict[int, list[TableCell]] = defaultdict(list)
    for cell in table.cells:
        rows[cell.row].append(cell)

    lines = [f"表格: {table.title or 'DOCX 表格'}"]
    for row_index in sorted(rows):
        row_cells = sorted(rows[row_index], key=lambda item: item.col)
        if row_index <= table.header_depth:
            lines.append(f"表头第 {row_index} 行: " + " | ".join(cell.value for cell in row_cells))
            continue
        pairs = []
        for cell in row_cells:
            label = " > ".join(cell.header_path) if cell.header_path else f"列{cell.col}"
            pairs.append(f"{label}={cell.value}")
        lines.append(f"第 {row_index} 行: " + " | ".join(pairs))
    return compact_join(lines)
