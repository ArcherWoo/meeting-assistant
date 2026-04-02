from __future__ import annotations

from services.document_parsing.chunker import chunk_parsed_document
from services.document_parsing.models import ParsedDocument
from services.document_parsing.parsers.common import compact_join


def render_document_for_prompt(document: ParsedDocument) -> str:
    chunks = chunk_parsed_document(document)
    return compact_join(chunk.get("content", "") for chunk in chunks)

