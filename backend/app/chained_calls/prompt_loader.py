# Built with Spec4 AI - https://spec4.ai
"""Thin resolver for versioned chained-calls persona prompt templates.

Deliberately a near-copy of `rag/prompt_loader.py` rather than a shared import:
the instruction for this phase is to mirror that resolver, and the two already
sit alongside a third in `tools/`. Consolidating all three into `services/` is
the obvious follow-up and is tracked as a known gap -- adding a fourth caller
to a module that does not exist yet would have been the wrong order.

The module is named `prompt_loader.py`, not `prompts.py`, for the same reason
its RAG counterpart is: a `prompts/` directory sits beside it in this package.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def load_persona_prompt(version: str) -> str:
    """Load a versioned persona prompt template's raw content by name.

    Google-style docstring per project convention.

    Args:
        version: The template's version name, matching its filename without
            extension (e.g. "writer_v1" for prompts/writer_v1.md).

    Returns:
        The template file's full text content.
    """
    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
