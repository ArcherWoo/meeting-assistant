from __future__ import annotations

import re
from typing import Iterable


def normalize_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact_join(parts: Iterable[str], sep: str = "\n") -> str:
    return sep.join(part for part in (normalize_text(part) for part in parts) if part)


def excel_col_to_index(col_letters: str) -> int:
    result = 0
    for char in col_letters.upper():
        result = result * 26 + (ord(char) - 64)
    return result


def excel_index_to_col(index: int) -> str:
    if index <= 0:
        return ""
    letters: list[str] = []
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def is_probably_numeric(value: str) -> bool:
    normalized = value.strip().replace(",", "")
    if not normalized:
        return False
    try:
        float(normalized.rstrip("%"))
        return True
    except ValueError:
        return False

