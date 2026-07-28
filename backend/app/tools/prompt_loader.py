# Built with Spec4 AI - https://spec4.ai
"""Thin resolver for versioned tool-use agent prompt templates.

Mirrors rag/prompt_loader.py deliberately: each package owns its own prompts/
directory, and the resolver is named prompt_loader.py rather than prompts.py
so it doesn't collide with that sibling directory.
"""

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
            extension (e.g. "agent_v1" for prompts/agent_v1.md).

    Returns:
        The template file's full text content.
    """
    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
