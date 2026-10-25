# Built with Spec4 AI - https://spec4.ai
"""The single-call route: one generation call over the request alone.

Goes through the shared generation service (`services/generation.py`) -- the
same LiteLLM path and model registry the Single-Call example's entry point
uses -- rather than through `single_call.service.run_plain_call` itself. That
entry point cannot serve here unmodified: it charges the shared usage gate a
unit of its own (the Router run already holds its two), takes no system
instruction, and returns no timing. Wrapping one layer down keeps the
Single-Call slice untouched and the run inside its two held units.

The generation service is synchronous, so the call runs in a worker thread
rather than blocking the event loop the run is streaming on. The response is
capped with `max_tokens` -- the one keyword this revision added to the shared
service. It returns no token counts, so none are reported: the cost strip
counts calls and measured time, and a token figure that was not measured is
not shown.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import structlog

from backend.app.services import generation
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR: Final[Path] = Path(__file__).parent / "prompts"
SINGLE_CALL_PROMPT_VERSION: Final[str] = "single_call_v1"
#: Response-length cap passed to the generation service.
MAX_ANSWER_TOKENS: Final[int] = 400
#: Longest answer shown on the card. Longer answers are cut at a sentence
#: boundary with an ellipsis.
MAX_ANSWER_CHARS: Final[int] = 1200

_SENTENCE_END: Final = re.compile(r"[.!?](?=\s|$)")


@dataclass(frozen=True)
class SingleCallAnswer:
    """A generated answer.

    Attributes:
        answer_text: The answer, possibly truncated at a sentence boundary.
        model: The slug that served it.
        elapsed_ms: This call's own measured time.
        truncated: True when the answer was cut to fit the card.
        prompt_tokens: Not reported by the generation service; always None.
        completion_tokens: Not reported by the generation service; always None.
    """

    answer_text: str
    model: str
    elapsed_ms: int
    truncated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class SingleCallFailure:
    """Every model in the chain failed, or the response was empty.

    Attributes:
        message: A plain statement for the card. No answer is fabricated.
        elapsed_ms: Time spent before failing.
    """

    message: str
    elapsed_ms: int


def truncate_at_sentence(text: str, limit: int = MAX_ANSWER_CHARS) -> tuple[str, bool]:
    """Cut text to a limit at the last sentence end, adding an ellipsis.

    Args:
        text: The answer.
        limit: Maximum characters.

    Returns:
        The possibly-cut text, and whether it was cut.
    """
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped, False
    head = stripped[:limit]
    ends = [match.end() for match in _SENTENCE_END.finditer(head)]
    cut = head[: ends[-1]] if ends else head.rsplit(" ", 1)[0]
    return f"{cut.rstrip()} …", True


async def answer(request: str) -> SingleCallAnswer | SingleCallFailure:
    """Answer a request with one generation call.

    Args:
        request: The visitor's request, verbatim. Placed in a delimited user
            turn; the instructions are in the system prompt.

    Returns:
        The answer with its model and measured time, or a typed failure.
    """
    system_prompt = load_prompt(PROMPTS_DIR, SINGLE_CALL_PROMPT_VERSION)
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            generation.generate_text,
            system_prompt=system_prompt,
            user_prompt=untrusted_block("visitor request", request),
            max_tokens=MAX_ANSWER_TOKENS,
        )
    except generation.GenerationServiceError:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.warning("router_single_call_failed", elapsed_ms=elapsed_ms)
        return SingleCallFailure(
            message=(
                "The single-call route could not produce an answer: every model "
                "in the shared generation chain failed. No answer is shown "
                "rather than an invented one."
            ),
            elapsed_ms=elapsed_ms,
        )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    text, truncated = truncate_at_sentence(result.text)
    logger.info(
        "router_single_call_completed",
        model=result.model,
        elapsed_ms=elapsed_ms,
        chars=len(text),
        truncated=truncated,
    )
    return SingleCallAnswer(
        answer_text=text, model=result.model, elapsed_ms=elapsed_ms, truncated=truncated
    )
