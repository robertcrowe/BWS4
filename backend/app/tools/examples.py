# Built with Spec4 AI - https://spec4.ai
"""The curated queries the tool-use screen offers as one-click examples.

Held server-side so the safety gate can *recognise* them rather than take a
client's word. See `rag/examples.py` for the reasoning, which is identical —
including that drift between this list and the frontend's costs an exemption
rather than opening a bypass.

The last entry is deliberately something the agent should answer *without*
searching. It is how the screen shows that declining to use a tool is as much a
routing decision as using one, so it needs the same exemption as the rest.
"""

from __future__ import annotations

from typing import Final

EXAMPLE_QUERIES: Final[tuple[str, ...]] = (
    "What is the latest Spec4 release?",
    "Current Mars rover mission status",
    "Recent breakthroughs in agentic AI frameworks",
    "What is 17 times 24?",
)
