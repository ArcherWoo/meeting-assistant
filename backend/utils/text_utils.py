"""
文本处理工具。

统一处理中文字符判断、中文片段提取和含中文 slug 生成，
避免在业务代码里散落难读的字符区间正则。
"""

from __future__ import annotations


def is_han_character(char: str) -> bool:
    """判断字符是否属于常用汉字区间。"""
    if not char:
        return False
    codepoint = ord(char)
    return 0x4E00 <= codepoint <= 0x9FFF


def contains_han_text(text: str) -> bool:
    """判断文本中是否包含中文。"""
    return any(is_han_character(char) for char in str(text or ""))


def extract_han_segments(
    text: str,
    *,
    min_length: int = 1,
    max_length: int | None = None,
) -> list[str]:
    """
    提取连续中文片段。

    当设置 ``max_length`` 时，会把超长片段按固定长度切开，
    方便用于关键词提取和召回打分。
    """
    segments: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if not current:
            return
        segment = "".join(current)
        current.clear()
        if len(segment) < min_length:
            return
        if max_length is None or len(segment) <= max_length:
            segments.append(segment)
            return

        start = 0
        while start < len(segment):
            chunk = segment[start : start + max_length]
            if len(chunk) >= min_length:
                segments.append(chunk)
            start += max_length

    for char in str(text or ""):
        if is_han_character(char):
            current.append(char)
            continue
        flush()
    flush()
    return segments


def slugify_preserving_han(name: str, *, fallback: str = "unnamed-skill") -> str:
    """
    生成 slug，保留 ASCII 单词字符、连字符和中文。
    其它字符统一折叠成单个连字符。
    """
    slug_chars: list[str] = []
    last_was_dash = False

    for char in str(name or "").strip():
        lowered = char.lower() if char.isascii() else char
        is_safe_ascii = lowered.isascii() and (lowered.isalnum() or lowered == "_")
        if is_safe_ascii or is_han_character(lowered):
            slug_chars.append(lowered)
            last_was_dash = False
            continue
        if not last_was_dash:
            slug_chars.append("-")
            last_was_dash = True

    slug = "".join(slug_chars).strip("-")
    return slug or fallback
