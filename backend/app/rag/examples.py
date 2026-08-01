# Built with Spec4 AI - https://spec4.ai
"""The curated questions the RAG screen offers as one-click examples.

Held server-side so the safety gate can *recognise* them rather than take a
client's word that a question is one. `services/text_gate.py` matches the
submitted text against these strings byte-for-byte; nothing accepts an id, so
there is no token to attach to arbitrary text to skip moderation.

**These must stay identical to `EXAMPLE_QUESTIONS` in
`frontend/src/apps/rag/QuestionAnswer.tsx`.** They are duplicated rather than
served, because an endpoint and a fetch would be a lot of machinery for five
strings that change when someone edits the screen. The duplication is safe in
the direction that matters: if the two drift, an example stops being recognised
and gets moderated like free text — a lost exemption, never a bypass.

The last two are deliberately unanswerable from the dataset. They are what makes
the screen honest about what retrieval cannot do, so they matter more than the
ones that work.
"""

from __future__ import annotations

from typing import Final

EXAMPLE_QUESTIONS: Final[tuple[str, ...]] = (
    "When did Voyager 1 launch and what is it doing now?",
    "What did the Apollo 11 mission accomplish?",
    "What does the James Webb Space Telescope observe?",
    "Who was the first woman in space?",
    "What's the best pizza topping?",
)
