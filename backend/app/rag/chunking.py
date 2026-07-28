# Built with Spec4 AI - https://spec4.ai
"""Hand-rolled paragraph/fixed-window chunking for the RAG reference dataset."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_WINDOW_CHARS = 500


@dataclass(frozen=True)
class Passage:
    """A single retrievable excerpt produced by the chunking pipeline.

    Attributes:
        passage_id: Stable identifier, unique within a source document.
        source_title: Title of the document the passage was drawn from.
        text_excerpt: The passage's text content.
    """

    passage_id: str
    source_title: str
    text_excerpt: str


def chunk_document(
    source_title: str,
    text: str,
    window_chars: int = DEFAULT_WINDOW_CHARS,
) -> list[Passage]:
    """Split a document's text into paragraph/fixed-window passages.

    Paragraphs (blank-line-separated blocks) are kept whole whenever they fit
    within ``window_chars``. Paragraphs longer than the window are further
    split on word boundaries into contiguous, non-overlapping windows, so the
    passages together cover the full document with no gap larger than
    ``window_chars``.

    Google-style docstring per project convention.

    Args:
        source_title: Title of the document being chunked.
        text: The document's raw text content.
        window_chars: Maximum character length of a single passage.

    Returns:
        An ordered list of Passage objects covering the entire document.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    passages: list[Passage] = []
    for paragraph in paragraphs:
        for window in _split_into_windows(paragraph, window_chars):
            passage_number = len(passages) + 1
            passages.append(
                Passage(
                    passage_id=f"{_slugify(source_title)}-{passage_number}",
                    source_title=source_title,
                    text_excerpt=window,
                )
            )
    return passages


def _split_into_windows(paragraph: str, window_chars: int) -> list[str]:
    """Split one paragraph into contiguous windows of at most window_chars.

    Splits occur on word boundaries so words are never broken mid-token.

    Args:
        paragraph: A single paragraph's text.
        window_chars: Maximum character length of a window.

    Returns:
        An ordered list of window strings whose concatenation (with single
        spaces) reproduces the paragraph's words with no gaps.
    """
    if len(paragraph) <= window_chars:
        return [paragraph]

    words = paragraph.split()
    windows: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        added_len = len(word) + (1 if current else 0)
        if current and current_len + added_len > window_chars:
            windows.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += added_len
    if current:
        windows.append(" ".join(current))
    return windows


def _slugify(title: str) -> str:
    """Convert a document title into a lowercase, hyphenated identifier prefix."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
