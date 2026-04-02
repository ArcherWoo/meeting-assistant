from __future__ import annotations

import csv
import io

from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument, StructuredTable, TableCell
from services.document_parsing.parsers.common import normalize_text
from services.document_parsing.parsers.text_parser import PlainTextParser


class CsvParser:
    supported_extensions = {".csv"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        text = PlainTextParser._decode_bytes(file_content)
        reader = csv.reader(io.StringIO(text))
        rows = [[normalize_text(cell) for cell in row] for row in reader]
        if not rows:
            return ParsedDocument(
                doc_id=gen_id(),
                filename=filename,
                file_type="csv",
                parser_trace={"parser": "csv"},
            )

        block_id = gen_id()
        table_id = gen_id()
        cells: list[TableCell] = []
        max_col = max((len(row) for row in rows), default=0)
        for row_index, row in enumerate(rows, start=1):
            for col_index in range(1, max_col + 1):
                value = row[col_index - 1] if col_index - 1 < len(row) else ""
                cells.append(
                    TableCell(
                        row=row_index,
                        col=col_index,
                        value=value,
                        is_header=row_index == 1,
                        header_path=[rows[0][col_index - 1]] if row_index > 1 and col_index - 1 < len(rows[0]) and rows[0][col_index - 1] else [],
                    )
                )

        table = StructuredTable(
            id=table_id,
            source_block_id=block_id,
            title=filename,
            header_depth=1 if rows else 0,
            cells=cells,
            row_count=len(rows),
            col_count=max_col,
        )
        block = DocumentBlock(
            id=block_id,
            block_type="table",
            text=filename,
            table_id=table_id,
            source_locator={"sheet": filename},
        )
        return ParsedDocument(
            doc_id=gen_id(),
            filename=filename,
            file_type="csv",
            blocks=[block],
            tables=[table],
            parser_trace={"parser": "csv"},
        )

