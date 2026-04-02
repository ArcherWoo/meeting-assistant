from __future__ import annotations

import io
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from services.storage import gen_id

from services.document_parsing.models import (
    DocumentBlock,
    MergedRange,
    ParsedDocument,
    StructuredTable,
    TableCell,
)
from services.document_parsing.parsers.common import (
    compact_join,
    excel_col_to_index,
    excel_index_to_col,
    is_probably_numeric,
    normalize_text,
)


NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
NS_PKG_REL = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
CELL_REF_RE = re.compile(r"([A-Z]+)(\d+)")


@dataclass
class SheetEntry:
    name: str
    target: str


class XlsxParser:
    supported_extensions = {".xlsx"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        workbook = zipfile.ZipFile(io.BytesIO(file_content))
        try:
            shared_strings = self._load_shared_strings(workbook)
            sheets = self._load_sheet_entries(workbook)
            blocks: list[DocumentBlock] = []
            tables: list[StructuredTable] = []
            warnings: list[str] = []

            for sheet in sheets:
                sheet_table, sheet_blocks, sheet_warnings = self._parse_sheet(
                    workbook,
                    sheet,
                    shared_strings,
                )
                tables.extend(sheet_table)
                blocks.extend(sheet_blocks)
                warnings.extend(sheet_warnings)

            return ParsedDocument(
                doc_id=gen_id(),
                filename=filename,
                file_type=os.path.splitext(filename)[1].lower().lstrip(".") or "xlsx",
                metadata={"sheet_count": len(sheets)},
                blocks=blocks,
                tables=tables,
                warnings=warnings,
                parser_trace={"parser": "xlsx-ooxml", "sheets": [sheet.name for sheet in sheets]},
            )
        finally:
            workbook.close()

    def _load_shared_strings(self, workbook: zipfile.ZipFile) -> list[str]:
        try:
            raw = workbook.read("xl/sharedStrings.xml")
        except KeyError:
            return []

        root = ET.fromstring(raw)
        values: list[str] = []
        for item in root.findall("x:si", NS_MAIN):
            parts = [node.text or "" for node in item.findall(".//x:t", NS_MAIN)]
            values.append(normalize_text("".join(parts)))
        return values

    def _load_sheet_entries(self, workbook: zipfile.ZipFile) -> list[SheetEntry]:
        workbook_root = ET.fromstring(workbook.read("xl/workbook.xml"))
        rel_root = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall("pr:Relationship", NS_PKG_REL)
            if rel.attrib.get("Id") and rel.attrib.get("Target")
        }

        sheets: list[SheetEntry] = []
        for sheet in workbook_root.findall("x:sheets/x:sheet", NS_MAIN):
            name = sheet.attrib.get("name", "Sheet")
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if not rel_id or rel_id not in rel_map:
                continue
            target = rel_map[rel_id].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            sheets.append(SheetEntry(name=name, target=target))
        return sheets

    def _parse_sheet(
        self,
        workbook: zipfile.ZipFile,
        sheet: SheetEntry,
        shared_strings: list[str],
    ) -> tuple[list[StructuredTable], list[DocumentBlock], list[str]]:
        root = ET.fromstring(workbook.read(sheet.target))
        cell_map: dict[tuple[int, int], dict[str, Any]] = {}
        max_row = 0
        max_col = 0

        for cell in root.findall("x:sheetData/x:row/x:c", NS_MAIN):
            ref = cell.attrib.get("r", "")
            match = CELL_REF_RE.fullmatch(ref)
            if not match:
                continue
            col_index = excel_col_to_index(match.group(1))
            row_index = int(match.group(2))
            value = self._resolve_cell_value(cell, shared_strings)
            formula = normalize_text(cell.findtext("x:f", default="", namespaces=NS_MAIN))
            cell_map[(row_index, col_index)] = {"value": value, "formula": formula or None}
            max_row = max(max_row, row_index)
            max_col = max(max_col, col_index)

        merged_ranges: list[MergedRange] = []
        merge_lookup: dict[tuple[int, int], MergedRange] = {}
        for merge in root.findall("x:mergeCells/x:mergeCell", NS_MAIN):
            raw_ref = merge.attrib.get("ref", "")
            parsed = self._parse_range(raw_ref)
            if not parsed:
                continue
            merged_ranges.append(parsed)
            max_row = max(max_row, parsed.end_row)
            max_col = max(max_col, parsed.end_col)
            for row in range(parsed.start_row, parsed.end_row + 1):
                for col in range(parsed.start_col, parsed.end_col + 1):
                    merge_lookup[(row, col)] = parsed

        if not cell_map and not merged_ranges:
            block = DocumentBlock(
                id=gen_id(),
                block_type="sheet",
                text=f"工作表 {sheet.name} 为空",
                sheet=sheet.name,
                source_locator={"sheet": sheet.name},
            )
            return [], [block], []

        header_depth = self._detect_header_depth(cell_map, merge_lookup, max_row, max_col)
        table_block_id = gen_id()
        table_id = gen_id()
        table_cells: list[TableCell] = []

        for row in range(1, max_row + 1):
            for col in range(1, max_col + 1):
                merge = merge_lookup.get((row, col))
                if merge and (row != merge.start_row or col != merge.start_col):
                    continue
                anchor_row = merge.start_row if merge else row
                anchor_col = merge.start_col if merge else col
                raw = cell_map.get((anchor_row, anchor_col), {})
                value = normalize_text(str(raw.get("value") or ""))
                formula = raw.get("formula")
                header_path = []
                if row > header_depth:
                    header_path = self._build_header_path(
                        col=col,
                        header_depth=header_depth,
                        cell_map=cell_map,
                        merge_lookup=merge_lookup,
                    )
                elif value:
                    header_path = [value]
                table_cells.append(
                    TableCell(
                        row=row,
                        col=col,
                        row_span=merge.row_span if merge else 1,
                        col_span=merge.col_span if merge else 1,
                        value=value,
                        formula=formula,
                        is_header=row <= header_depth,
                        header_path=header_path,
                    )
                )

        table = StructuredTable(
            id=table_id,
            source_block_id=table_block_id,
            title=sheet.name,
            sheet=sheet.name,
            header_depth=header_depth,
            cells=table_cells,
            merged_ranges=merged_ranges,
            row_count=max_row,
            col_count=max_col,
            semantic_schema={
                "merged_range_count": len(merged_ranges),
                "header_depth": header_depth,
            },
        )

        sheet_summary = DocumentBlock(
            id=gen_id(),
            block_type="sheet",
            text=f"工作表 {sheet.name}，共 {max_row} 行 {max_col} 列",
            sheet=sheet.name,
            source_locator={"sheet": sheet.name, "row_count": max_row, "col_count": max_col},
        )
        table_block = DocumentBlock(
            id=table_block_id,
            block_type="table",
            text=f"{sheet.name} 表格",
            sheet=sheet.name,
            table_id=table_id,
            source_locator={"sheet": sheet.name, "row_count": max_row, "col_count": max_col},
        )

        warnings: list[str] = []
        if merged_ranges:
            warnings.append(f"{sheet.name}: preserved {len(merged_ranges)} merged ranges")
        return [table], [sheet_summary, table_block], warnings

    def _resolve_cell_value(self, cell: ET.Element, shared_strings: list[str]) -> str:
        cell_type = cell.attrib.get("t", "")
        if cell_type == "inlineStr":
            return normalize_text("".join(node.text or "" for node in cell.findall(".//x:t", NS_MAIN)))

        raw = normalize_text(cell.findtext("x:v", default="", namespaces=NS_MAIN))
        if cell_type == "s" and raw.isdigit():
            index = int(raw)
            return shared_strings[index] if 0 <= index < len(shared_strings) else raw
        if cell_type == "b":
            return "TRUE" if raw == "1" else "FALSE"
        return raw

    def _parse_range(self, raw_ref: str) -> MergedRange | None:
        if ":" not in raw_ref:
            return None
        start_ref, end_ref = raw_ref.split(":", 1)
        start = CELL_REF_RE.fullmatch(start_ref.upper())
        end = CELL_REF_RE.fullmatch(end_ref.upper())
        if not start or not end:
            return None
        return MergedRange(
            start_row=int(start.group(2)),
            start_col=excel_col_to_index(start.group(1)),
            end_row=int(end.group(2)),
            end_col=excel_col_to_index(end.group(1)),
        )

    def _detect_header_depth(
        self,
        cell_map: dict[tuple[int, int], dict[str, Any]],
        merge_lookup: dict[tuple[int, int], MergedRange],
        max_row: int,
        max_col: int,
    ) -> int:
        candidate_depth = 0
        for row in range(1, min(max_row, 4) + 1):
            values = []
            for col in range(1, max_col + 1):
                merge = merge_lookup.get((row, col))
                key = (merge.start_row, merge.start_col) if merge else (row, col)
                values.append(normalize_text(str(cell_map.get(key, {}).get("value") or "")))
            non_empty = [value for value in values if value]
            if not non_empty:
                if candidate_depth > 0:
                    break
                continue
            text_ratio = sum(0 if is_probably_numeric(value) else 1 for value in non_empty) / len(non_empty)
            if row == 1 or text_ratio >= 0.6:
                candidate_depth = row
                continue
            break
        return max(candidate_depth, 1)

    def _build_header_path(
        self,
        *,
        col: int,
        header_depth: int,
        cell_map: dict[tuple[int, int], dict[str, Any]],
        merge_lookup: dict[tuple[int, int], MergedRange],
    ) -> list[str]:
        parts: list[str] = []
        seen: set[str] = set()
        for header_row in range(1, header_depth + 1):
            merge = merge_lookup.get((header_row, col))
            key = (merge.start_row, merge.start_col) if merge else (header_row, col)
            value = normalize_text(str(cell_map.get(key, {}).get("value") or ""))
            if value and value not in seen:
                parts.append(value)
                seen.add(value)
        return parts


def render_table_window(
    table: StructuredTable,
    start_row: int,
    end_row: int,
) -> str:
    cells_by_row: dict[int, list[TableCell]] = defaultdict(list)
    for cell in table.cells:
        if start_row <= cell.row <= end_row:
            cells_by_row[cell.row].append(cell)

    lines = [f"工作表: {table.sheet or table.title or 'Sheet'}"]
    if table.merged_ranges:
        merged = ", ".join(
            f"{excel_index_to_col(item.start_col)}{item.start_row}:{excel_index_to_col(item.end_col)}{item.end_row}"
            for item in table.merged_ranges[:8]
        )
        lines.append(f"合并单元格: {merged}")

    header_rows = list(range(1, min(table.header_depth, table.row_count) + 1))
    data_rows = list(range(max(start_row, table.header_depth + 1), end_row + 1))
    for row in [*header_rows, *data_rows]:
        row_cells = sorted(cells_by_row.get(row, []), key=lambda item: item.col)
        if not row_cells:
            continue
        if row <= table.header_depth:
            values = [cell.value or f"列{cell.col}" for cell in row_cells]
            lines.append(f"表头第 {row} 行: " + " | ".join(values))
            continue
        pairs = []
        for cell in row_cells:
            label = " > ".join(cell.header_path) if cell.header_path else f"列{cell.col}"
            suffix = ""
            if cell.row_span > 1 or cell.col_span > 1:
                suffix = f" [span {cell.row_span}x{cell.col_span}]"
            value = cell.value or ""
            if cell.formula and cell.formula != value:
                value = f"{value} (formula={cell.formula})"
            pairs.append(f"{label}={value}{suffix}")
        lines.append(f"第 {row} 行: " + " | ".join(pairs))
    return compact_join(lines)
