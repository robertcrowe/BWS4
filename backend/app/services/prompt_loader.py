# Built with Spec4 AI - https://spec4.ai
"""Framework resolver for versioned in-repo prompt templates.

Three near-identical copies of this already exist -- `rag/prompt_loader.py`,
`tools/prompt_loader.py`, `chained_calls/prompt_loader.py` -- and CLAUDE.md
records consolidating them here as a known gap, noting that v3 Phase 1 added the
third only because its instruction said to mirror the existing one. This phase's
instruction says to use "the same thin resolver **pattern**", which the shared
module satisfies without making it four.

The three existing copies are deliberately left alone: migrating them is three
one-line edits plus their tests, which is real work in three shipped apps and
belongs to a change that is about those apps. This module is the destination
when that happens.

It takes the directory as an argument rather than deriving it from the caller,
so one function serves every package without inspecting stack frames.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache
def load_prompt(prompts_dir: Path, version: str) -> str:
    """Load a versioned prompt template's raw content.

    Google-style docstring per project convention.

    Args:
        prompts_dir: The package's `prompts/` directory.
        version: The template's version name, matching its filename without
            extension (e.g. "planner_v1" for prompts/planner_v1.md).

    Returns:
        The template file's full text content.

    Raises:
        FileNotFoundError: If no such version exists. Loud by design -- a
            missing prompt is a deployment fault, and a caller that fell back
            to some other version would run a prompt nobody chose.
    """
    return (prompts_dir / f"{version}.md").read_text(encoding="utf-8")
