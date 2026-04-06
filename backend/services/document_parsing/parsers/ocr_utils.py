from __future__ import annotations

import io
import re
from collections import Counter
from typing import Any

from services.document_parsing.parsers.common import compact_join, normalize_text


LIST_ITEM_RE = re.compile(r"^([-*•]|\d+[.)])\s+")
SENTENCE_END_RE = re.compile(r"[。！？!?；;.]$")
SECTION_PREFIX_RE = re.compile(r"^(section|chapter|part|appendix)\b", re.IGNORECASE)


def inspect_image_metadata(file_content: bytes, warnings: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": None,
        "width": None,
        "height": None,
        "mode": None,
        "frame_count": None,
        "embedded_text": "",
    }
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:
        warnings.append(f"Pillow unavailable: {exc}")
        return metadata

    try:
        image = Image.open(io.BytesIO(file_content))
        metadata["format"] = str(image.format or "")
        metadata["width"] = int(image.width)
        metadata["height"] = int(image.height)
        metadata["mode"] = str(image.mode or "")
        metadata["frame_count"] = int(getattr(image, "n_frames", 1) or 1)

        text_fragments: list[str] = []
        info = getattr(image, "info", {}) or {}
        for key in ("Description", "Comment", "XML:com.adobe.xmp", "parameters"):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                text_fragments.append(value)
        png_text = getattr(image, "text", {}) or {}
        if isinstance(png_text, dict):
            for value in png_text.values():
                if isinstance(value, str) and value.strip():
                    text_fragments.append(value)
        metadata["embedded_text"] = "\n".join(
            dict.fromkeys(
                normalize_text(fragment)
                for fragment in text_fragments
                if normalize_text(fragment)
            )
        )
        image.close()
        return metadata
    except Exception as exc:
        warnings.append(f"Image inspection failed: {exc}")
        return metadata


def extract_ocr_text_from_image_bytes(
    file_content: bytes,
    warnings: list[str],
) -> tuple[str, str | None]:
    layout, engine = extract_ocr_layout_from_image_bytes(file_content, warnings)
    return str(layout.get("text") or ""), engine


def extract_ocr_layout_from_image_bytes(
    file_content: bytes,
    warnings: list[str],
) -> tuple[dict[str, Any], str | None]:
    empty_layout = {"text": "", "lines": []}
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
        from pytesseract import Output  # type: ignore
    except Exception as exc:
        warnings.append(f"OCR dependencies unavailable: {exc}")
        return empty_layout, None

    try:
        image = Image.open(io.BytesIO(file_content))
        data = pytesseract.image_to_data(image, output_type=Output.DICT)
        layout = _build_layout_from_tesseract_data(data)
        if not layout["text"]:
            layout["text"] = normalize_text(pytesseract.image_to_string(image) or "")
        image.close()
        return layout, "tesseract"
    except Exception as exc:
        warnings.append(f"OCR extraction failed: {exc}")
        return empty_layout, None


def build_ocr_structure(
    *,
    text: str,
    lines: list[dict[str, Any]],
    source: str = "ocr",
    include_prefix: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    if not lines:
        return {
            "blocks": segment_ocr_text(text, source=source, include_prefix=include_prefix),
            "tables": [],
        }

    parsed_lines = [_decorate_ocr_line(line) for line in lines if normalize_text(str(line.get("text") or ""))]
    if not parsed_lines:
        return {
            "blocks": segment_ocr_text(text, source=source, include_prefix=include_prefix),
            "tables": [],
        }

    consumed_indexes: set[int] = set()
    tables: list[dict[str, Any]] = []
    table_counter = 1

    for cluster in _detect_table_clusters(parsed_lines):
        cluster_rows = [_normalize_table_row(parsed_lines[index]["cells"]) for index in cluster]
        if not cluster_rows:
            continue

        title = ""
        previous_index = cluster[0] - 1
        if previous_index >= 0 and previous_index not in consumed_indexes:
            previous_text = normalize_text(str(parsed_lines[previous_index].get("text") or ""))
            if previous_text and _looks_like_heading(previous_text):
                title = previous_text
                consumed_indexes.add(previous_index)

        for index in cluster:
            consumed_indexes.add(index)

        tables.append({
            "title": title or f"OCR Table {table_counter}",
            "rows": cluster_rows,
            "source": source,
        })
        table_counter += 1

    non_table_segments: list[str] = []
    current_segment: list[str] = []
    for index, line in enumerate(parsed_lines):
        if index in consumed_indexes:
            if current_segment:
                non_table_segments.append("\n".join(current_segment))
                current_segment = []
            continue
        current_segment.append(str(line.get("text") or ""))
    if current_segment:
        non_table_segments.append("\n".join(current_segment))

    blocks: list[dict[str, Any]] = []
    prefix_pending = include_prefix
    for segment in non_table_segments:
        segmented = segment_ocr_text(segment, source=source, include_prefix=prefix_pending)
        if segmented:
            blocks.extend(segmented)
            prefix_pending = False

    if not blocks and text and not tables:
        blocks = segment_ocr_text(text, source=source, include_prefix=include_prefix)

    return {"blocks": blocks, "tables": tables}


def segment_ocr_text(
    text: str,
    *,
    source: str = "ocr",
    include_prefix: bool = False,
) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    segments = [
        normalize_text(segment)
        for segment in re.split(r"\n\s*\n", normalized)
        if normalize_text(segment)
    ]
    if not segments:
        segments = [normalized]

    blocks: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        lines = [normalize_text(line) for line in segment.split("\n") if normalize_text(line)]
        if not lines:
            continue
        first_line = lines[0]
        line_count = len(lines)

        block_type = "paragraph"
        semantic_tags = ["ocr_text"]
        if LIST_ITEM_RE.match(first_line):
            block_type = "list_item"
            semantic_tags.append("list_like")
        elif index == 1 and line_count <= 2 and len(first_line) <= 80:
            block_type = "title"
            semantic_tags.append("section_header")
        elif line_count <= 2 and _looks_like_heading(first_line):
            block_type = "heading"
            semantic_tags.append("section_header")

        content = compact_join(lines)
        if include_prefix and index == 1:
            content = f"OCR text\n{content}"

        blocks.append(
            {
                "block_type": block_type,
                "text": content,
                "semantic_tags": semantic_tags,
                "source": source,
                "ocr_segment_index": index,
            }
        )
    return blocks


def _build_layout_from_tesseract_data(data: dict[str, list[Any]]) -> dict[str, Any]:
    line_groups: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    total_items = len(data.get("text", []))
    for index in range(total_items):
        text = normalize_text(str(data.get("text", [""])[index] or ""))
        if not text:
            continue
        confidence = _coerce_float((data.get("conf") or [None])[index])
        if confidence is not None and confidence < 0:
            continue
        key = (
            _coerce_int((data.get("block_num") or [0])[index]) or 0,
            _coerce_int((data.get("par_num") or [0])[index]) or 0,
            _coerce_int((data.get("line_num") or [0])[index]) or 0,
        )
        line_groups.setdefault(key, []).append(
            {
                "text": text,
                "left": _coerce_int((data.get("left") or [0])[index]) or 0,
                "top": _coerce_int((data.get("top") or [0])[index]) or 0,
                "width": _coerce_int((data.get("width") or [0])[index]) or 0,
                "height": _coerce_int((data.get("height") or [0])[index]) or 0,
                "conf": confidence,
            }
        )

    lines: list[dict[str, Any]] = []
    for _, words in sorted(line_groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        ordered_words = sorted(words, key=lambda word: (int(word["left"]), int(word["top"])))
        line_text = " ".join(str(word["text"]) for word in ordered_words if word.get("text"))
        if not line_text:
            continue
        lines.append(
            {
                "text": normalize_text(line_text),
                "words": ordered_words,
                "top": min(int(word["top"]) for word in ordered_words),
                "left": min(int(word["left"]) for word in ordered_words),
            }
        )

    return {
        "text": "\n".join(str(line["text"]) for line in lines),
        "lines": lines,
    }


def _decorate_ocr_line(line: dict[str, Any]) -> dict[str, Any]:
    words = list(line.get("words") or [])
    cells = _split_words_into_cells(words)
    decorated = dict(line)
    decorated["cells"] = cells
    return decorated


def _split_words_into_cells(words: list[dict[str, Any]]) -> list[str]:
    if not words:
        return []
    ordered_words = sorted(words, key=lambda word: int(word.get("left", 0)))
    widths = [max(int(word.get("width", 0)), 1) for word in ordered_words]
    average_width = sum(widths) / len(widths) if widths else 1
    gap_threshold = max(24.0, average_width * 1.8)

    cells: list[list[str]] = [[]]
    previous_right: float | None = None
    for word in ordered_words:
        left = float(int(word.get("left", 0)))
        width = float(max(int(word.get("width", 0)), 1))
        if previous_right is not None and left - previous_right > gap_threshold:
            cells.append([])
        cells[-1].append(str(word.get("text") or ""))
        previous_right = left + width

    return [normalize_text(" ".join(cell)) for cell in cells if normalize_text(" ".join(cell))]


def _detect_table_clusters(lines: list[dict[str, Any]]) -> list[list[int]]:
    clusters: list[list[int]] = []
    current: list[int] = []
    for index, line in enumerate(lines):
        cell_count = len(line.get("cells") or [])
        if cell_count >= 2:
            current.append(index)
            continue
        if len(current) >= 2:
            cluster = _finalize_table_cluster(lines, current)
            if cluster:
                clusters.append(cluster)
        current = []

    if len(current) >= 2:
        cluster = _finalize_table_cluster(lines, current)
        if cluster:
            clusters.append(cluster)
    return clusters


def _finalize_table_cluster(lines: list[dict[str, Any]], indexes: list[int]) -> list[int]:
    counts = [len(lines[index].get("cells") or []) for index in indexes if len(lines[index].get("cells") or []) >= 2]
    if len(counts) < 2:
        return []
    dominant_count, dominant_freq = Counter(counts).most_common(1)[0]
    if dominant_count < 2 or dominant_freq < 2:
        return []
    cluster = [
        index
        for index in indexes
        if abs(len(lines[index].get("cells") or []) - dominant_count) <= 1
    ]
    return cluster if len(cluster) >= 2 else []


def _normalize_table_row(cells: list[str]) -> list[str]:
    cleaned = [normalize_text(cell) for cell in cells if normalize_text(cell)]
    return cleaned


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _looks_like_heading(text: str) -> bool:
    candidate = normalize_text(text)
    if not candidate or len(candidate) > 60:
        return False
    if SENTENCE_END_RE.search(candidate):
        return False
    if candidate.endswith(":") or candidate.endswith("："):
        return True
    if SECTION_PREFIX_RE.match(candidate):
        return True
    if re.match(r"^第[一二三四五六七八九十0-9]+[章节部分篇]", candidate):
        return True
    if re.match(r"^[一二三四五六七八九十]+、", candidate):
        return True

    words = [word for word in re.split(r"\s+", candidate) if word]
    if not words:
        return False
    if len(words) <= 6 and all(word[:1].isupper() for word in words if word[:1].isalpha()):
        return True
    return candidate.isupper() and len(candidate) <= 40
