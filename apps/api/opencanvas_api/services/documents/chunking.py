from __future__ import annotations

import re
from dataclasses import dataclass

from opencanvas_api.services.documents.extraction import ExtractedDocument

_SENTENCE_END = re.compile(r"(?<=[.!?])(?:[\"')\]]*)\s+")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    chunk_index: int
    content: str
    page_number: int | None
    heading: str | None
    char_start: int
    char_end: int


def chunk_document(
    extracted: ExtractedDocument, *, chunk_size: int, overlap: int
) -> list[ChunkDraft]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be nonnegative and smaller than chunk_size")

    chunks: list[ChunkDraft] = []
    for segment in extracted.segments:
        text = segment.text
        start = 0
        while start < len(text):
            target_end = min(start + chunk_size, len(text))
            end = _semantic_end(text, start=start, target_end=target_end)
            raw = text[start:end]
            left_trim = len(raw) - len(raw.lstrip())
            right_trimmed = raw.rstrip()
            local_start = start + left_trim
            local_end = start + len(right_trimmed)
            if local_end > local_start:
                chunk_start = segment.char_start + local_start
                chunk_end = segment.char_start + local_end
                chunks.append(
                    ChunkDraft(
                        chunk_index=len(chunks),
                        content=extracted.text[chunk_start:chunk_end],
                        page_number=segment.page_number,
                        heading=segment.heading,
                        char_start=chunk_start,
                        char_end=chunk_end,
                    )
                )
            if end >= len(text):
                break
            next_start = max(start + 1, end - overlap)
            start = _align_start(text, next_start, end)
    return chunks


def _semantic_end(text: str, *, start: int, target_end: int) -> int:
    if target_end >= len(text):
        return len(text)
    minimum = start + max(1, (target_end - start) // 2)
    paragraph = text.rfind("\n\n", minimum, target_end)
    if paragraph >= minimum:
        return paragraph
    sentence_ends = [match.end() for match in _SENTENCE_END.finditer(text, minimum, target_end)]
    if sentence_ends:
        return sentence_ends[-1]
    line = text.rfind("\n", minimum, target_end)
    if line >= minimum:
        return line
    space = text.rfind(" ", minimum, target_end)
    return space if space >= minimum else target_end


def _align_start(text: str, proposed: int, previous_end: int) -> int:
    if proposed <= 0 or proposed >= len(text) or text[proposed - 1].isspace():
        return proposed
    space = text.find(" ", proposed, min(previous_end, proposed + 64))
    return space + 1 if space >= 0 else proposed
