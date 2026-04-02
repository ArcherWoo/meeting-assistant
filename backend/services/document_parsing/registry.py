from __future__ import annotations

import os

from services.document_parsing.models import ParsedDocument
from services.document_parsing.parsers.csv_parser import CsvParser
from services.document_parsing.parsers.docx_parser import DocxParser
from services.document_parsing.parsers.image_parser import ImageParser
from services.document_parsing.parsers.pdf_parser import PdfParser
from services.document_parsing.parsers.ppt_parser_adapter import PptDocumentParser
from services.document_parsing.parsers.text_parser import PlainTextParser
from services.document_parsing.parsers.xlsx_parser import XlsxParser


class DocumentParserRegistry:
    def __init__(self) -> None:
        self._parsers = [
            PptDocumentParser(),
            PdfParser(),
            DocxParser(),
            XlsxParser(),
            CsvParser(),
            ImageParser(),
            PlainTextParser(),
        ]

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        ext = os.path.splitext(filename)[1].lower()
        for parser in self._parsers:
            if ext in getattr(parser, "supported_extensions", set()):
                return await parser.parse(file_content, filename)
        return await PlainTextParser().parse(file_content, filename)


document_parser_registry = DocumentParserRegistry()

