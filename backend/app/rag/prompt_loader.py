# Built with Spec4 AI - https://spec4.ai
"""Thin resolver for versioned RAG prompt templates."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def load_prompt(version: str) -> str:
    """Load a versioned prompt template's raw content by name.

    Google-style docstring per project convention.

    Args:
        version: The template's version name, matching its filename without
            extension (e.g. "answer_v1" for prompts/answer_v1.md).

    Returns:
        The template file's full text content, including its `{{...}}`
        placeholders for the caller to fill in.
    """
    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
