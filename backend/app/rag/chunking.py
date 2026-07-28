# Built with Spec4 AI - https://spec4.ai
"""Hand-rolled paragraph/fixed-window chunking for the RAG reference dataset."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_WINDOW_CHARS = 500

#: Characters of trailing context repeated at the start of the next window.
#: Without it, a paragraph longer than the window is cut at an arbitrary point
#: and the fact spanning that cut becomes unretrievable from either side.
#: Applied as a ceiling on OVERLAP_FRACTION so that a caller shrinking the
#: window (tests, experiments) gets a proportionally smaller overlap rather
#: than an overlap that no longer fits inside it.
DEFAULT_OVERLAP_CHARS = 100
OVERLAP_FRACTION = 0.2


def default_overlap_for(window_chars: int) -> int:
    """The overlap used when a caller doesn't specify one."""
    return min(DEFAULT_OVERLAP_CHARS, int(window_chars * OVERLAP_FRACTION))

#: Sentence terminator followed by whitespace and something that plausibly
#: starts a new sentence. Splitting on sentences rather than raw word count
#: keeps passages readable: the visitor sees every retrieved passage in the
#: UI, and a passage starting "and Gemini programs." reads as a bug.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")

#: Tokens that end in a period without ending a sentence. A miss here only
#: costs one over-eager split, so this list is kept short deliberately rather
#: than grown into a general abbreviation dictionary.
_ABBREVIATIONS = frozenset(
    {
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st",
        "e.g", "i.e", "etc", "vs", "no", "approx", "est",
        "u.s", "u.k", "u.s.s.r", "cf", "al", "fig",
    }
)


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
    overlap_chars: int | None = None,
) -> list[Passage]:
    """Split a document's text into overlapping, sentence-aligned passages.

    Paragraphs (blank-line-separated blocks) are kept whole whenever they fit
    within ``window_chars``. Longer paragraphs are packed sentence by sentence
    into windows, and each window after the first repeats up to
    ``overlap_chars`` of the preceding window's trailing sentences, so a fact
    straddling a window boundary is still retrievable in full from one side.
    A single sentence longer than the window is split on word boundaries as a
    last resort.

    Google-style docstring per project convention.

    Args:
        source_title: Title of the document being chunked.
        text: The document's raw text content.
        window_chars: Maximum character length of a single passage.
        overlap_chars: Trailing context repeated at the start of each
            subsequent window. Defaults to ``default_overlap_for(window_chars)``.
            Must be smaller than ``window_chars``.

    Returns:
        An ordered list of Passage objects covering the entire document.

    Raises:
        ValueError: If ``overlap_chars`` is negative or leaves no room for new
            content within ``window_chars``.
    """
    if overlap_chars is None:
        overlap_chars = default_overlap_for(window_chars)
    if overlap_chars < 0 or overlap_chars >= window_chars:
        raise ValueError("overlap_chars must be >= 0 and < window_chars")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    passages: list[Passage] = []
    for paragraph in paragraphs:
        for window in _split_into_windows(paragraph, window_chars, overlap_chars):
            passage_number = len(passages) + 1
            passages.append(
                Passage(
                    passage_id=f"{_slugify(source_title)}-{passage_number}",
                    source_title=source_title,
                    text_excerpt=window,
                )
            )
    return passages


def embedding_text(passage: Passage) -> str:
    """Build the text actually embedded for retrieval, which is not the excerpt.

    A chunk loses its subject the moment it is separated from its document:
    "It was launched in 1977" embeds nothing about Voyager, so a question
    naming Voyager cannot reach it. Prefixing the source title restores the
    subject to the vector. The excerpt itself is left untouched, since that is
    what the visitor reads and what is quoted into the generation prompt.

    Args:
        passage: The passage about to be embedded.

    Returns:
        The passage's text with its source title prepended as context.
    """
    return f"{passage.source_title}: {passage.text_excerpt}"


def _split_into_windows(
    paragraph: str, window_chars: int, overlap_chars: int
) -> list[str]:
    """Split one paragraph into overlapping windows of at most window_chars.

    Args:
        paragraph: A single paragraph's text.
        window_chars: Maximum character length of a window.
        overlap_chars: Trailing context to repeat at the start of each
            subsequent window.

    Returns:
        An ordered list of window strings that together cover every word of
        the paragraph, in order, with no gaps.
    """
    if len(paragraph) <= window_chars:
        return [paragraph]

    units = _split_sentences(paragraph)

    windows: list[str] = []
    current: list[str] = []
    for unit in units:
        # A single sentence too long for the window has no boundary to align
        # to, so fall back to word-splitting just that sentence.
        if len(unit) > window_chars:
            if current:
                windows.append(" ".join(current))
                current = []
            windows.extend(_split_words(unit, window_chars, overlap_chars))
            continue

        if current and _joined_len(current) + 1 + len(unit) > window_chars:
            windows.append(" ".join(current))
            current = _overlap_tail(current, overlap_chars, window_chars - len(unit) - 1)
        current.append(unit)

    if current:
        windows.append(" ".join(current))
    return windows


def _split_sentences(paragraph: str) -> list[str]:
    """Split a paragraph into sentences, re-joining false abbreviation splits."""
    parts = _SENTENCE_BOUNDARY.split(paragraph)

    sentences: list[str] = []
    for part in parts:
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def _ends_with_abbreviation(sentence: str) -> bool:
    """Whether a sentence's final token is an abbreviation rather than an end."""
    last_word = sentence.split()[-1] if sentence.split() else ""
    stripped = last_word.rstrip(".").lower()
    return stripped in _ABBREVIATIONS or len(stripped) == 1


def _overlap_tail(units: list[str], overlap_chars: int, budget: int) -> list[str]:
    """Select trailing units to repeat at the start of the next window.

    Args:
        units: The units making up the window that just closed.
        overlap_chars: The configured overlap allowance.
        budget: Characters still available in the next window once the unit
            that triggered the split is accounted for. Keeps the overlap from
            pushing the next window past window_chars.

    Returns:
        The trailing units that fit, in original order, possibly empty.
    """
    allowance = min(overlap_chars, budget)
    if allowance <= 0:
        return []

    tail: list[str] = []
    for unit in reversed(units):
        if _joined_len(tail) + (1 if tail else 0) + len(unit) > allowance:
            break
        tail.insert(0, unit)
    return tail


def _split_words(sentence: str, window_chars: int, overlap_chars: int) -> list[str]:
    """Split an over-long sentence on word boundaries, with overlap."""
    words = sentence.split()
    windows: list[str] = []
    current: list[str] = []
    for word in words:
        if current and _joined_len(current) + 1 + len(word) > window_chars:
            windows.append(" ".join(current))
            current = _overlap_tail(current, overlap_chars, window_chars - len(word) - 1)
        current.append(word)
    if current:
        windows.append(" ".join(current))
    return windows


def _joined_len(units: list[str]) -> int:
    """Length of units joined by single spaces, without building the string."""
    if not units:
        return 0
    return sum(len(unit) for unit in units) + len(units) - 1


def _slugify(title: str) -> str:
    """Convert a document title into a lowercase, hyphenated identifier prefix."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
