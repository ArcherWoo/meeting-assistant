from __future__ import annotations

import os

from services.storage import gen_id

from services.document_parsing.models import DocumentBlock, ParsedDocument
from services.document_parsing.parsers.common import normalize_text


class PlainTextParser:
    supported_extensions = {".txt", ".md", ".json", ".xml"}

    async def parse(self, file_content: bytes, filename: str) -> ParsedDocument:
        text = self._decode_bytes(file_content)
        paragraphs = [normalize_text(part) for part in text.split("\n\n")]
        blocks = [
            DocumentBlock(
                id=gen_id(),
                block_type="paragraph",
                text=paragraph,
                source_locator={"paragraph_index": index + 1},
            )
            for index, paragraph in enumerate(paragraphs)
            if paragraph
        ]
        return ParsedDocument(
            doc_id=gen_id(),
            filename=filename,
            file_type=os.path.splitext(filename)[1].lower().lstrip(".") or "text",
            metadata={"char_count": len(text)},
            blocks=blocks,
            parser_trace={"parser": "plain-text"},
        )

    @staticmethod
    def _decode_bytes(file_content: bytes) -> str:
        for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                return file_content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return file_content.decode("utf-8", errors="replace")

