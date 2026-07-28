# Built with Spec4 AI - https://spec4.ai
"""Reads the curated reference dataset's Markdown files into plain documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DATASET_DIR = Path(__file__).parent / "dataset"

_ATTRIBUTION_LINE = re.compile(r"^\[Built with Spec4 AI\]\([^)]*\)\n+")
_TITLE_LINE = re.compile(r"# (.+)\n+")
_SOURCE_FOOTER = re.compile(r"\n---\n")


@dataclass(frozen=True)
class Document:
    """A single reference dataset document ready for chunking.

    Attributes:
        title: The document's title, drawn from its Markdown H1 heading.
        text: The document's body text, excluding attribution notes.
        source_path: Filesystem path the document was loaded from.
    """

    title: str
    text: str
    source_path: Path


def load_dataset_documents(dataset_dir: Path = DATASET_DIR) -> list[Document]:
    """Load every Markdown document in the reference dataset directory.

    Google-style docstring per project convention.

    Args:
        dataset_dir: Directory containing one Markdown file per source
            article. Defaults to backend/app/rag/dataset/.

    Returns:
        Documents in filename-sorted order, one per dataset file.
    """
    return [
        _parse_document(path) for path in sorted(dataset_dir.glob("*.md"))
    ]


def _parse_document(path: Path) -> Document:
    """Parse one dataset Markdown file into a title and body text.

    Strips the Spec4 attribution line and the CC BY-SA source footer, leaving
    only the article's own content for chunking.

    Args:
        path: Path to the Markdown file.

    Returns:
        The parsed Document.

    Raises:
        ValueError: If the file has no H1 title line.
    """
    raw = _ATTRIBUTION_LINE.sub("", path.read_text(encoding="utf-8"), count=1)

    title_match = _TITLE_LINE.match(raw)
    if title_match is None:
        raise ValueError(f"dataset file {path} is missing an H1 title line")

    body = raw[title_match.end() :]
    body = _SOURCE_FOOTER.split(body, maxsplit=1)[0]

    return Document(title=title_match.group(1).strip(), text=body.strip(), source_path=path)
