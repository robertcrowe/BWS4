# Built with Spec4 AI - https://spec4.ai
"""The free-form question's suitability advisory. Advisory, and only ever that.

## The one property everything here protects

**Nothing in this module may prevent a run from starting.** Every failure path
-- timeout, model-chain exhaustion, a refused usage gate, a second validation
failure, the session cap, an unparseable question -- resolves to the same thing:
`None`, which the frontend renders as "we could not assess this, start the run
and the trace will show what happens". Start stays enabled and the visitor's
two-run allowance is untouched.

That is not politeness. A check implemented as a precondition would mean an
upstream free-tier outage silently closes the entire example, and the failure
would look like the app being broken rather than a hint being unavailable. So
there is exactly one exit type -- `QuestionSuitability | None` -- and no
exception escapes `assess`.

## Why the quota controls are here and not left to the UI

The check costs a model call and a visitor gets two runs, so an uncapped check
lets *typing* spend more of the shared allowance than *running*. Three
independent controls, and the server owns all three because a client-side
debounce protects nothing against a client that does not implement it:

* a **cache** keyed by the SHA-256 of the normalised question, so re-submitting
  the same text is free;
* a **per-session cap**, beyond which the neutral state is served with no call
  at all;
* a **length/shape precheck** that rejects fragments before any call.

The 600ms debounce and blur-only firing are genuinely the browser's job, and
they are implemented there -- but they are an optimisation on top of these,
never the protection itself.

## What is not stored

Never the question. The cache key is a hash of the normalised text and the
persisted verdict is four derived fields on `react_runs`. The question does
reach a model provider, which is why the input carries a disclosure notice --
but nothing in this project's own storage keeps it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import structlog

from backend.app.core import observability
from backend.app.core.config import get_settings
from backend.app.react import schemas
from backend.app.react.presets import PRESETS, HopSource
from backend.app.services import agent_runtime
from backend.app.services.prompt_context import with_current_date
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent / "prompts"

#: The prompt version in force. Bumped by adding `suitability_v2.md` alongside.
SUITABILITY_PROMPT_VERSION: Final[str] = "suitability_v1"

#: Attempts at a valid verdict: one ask, then one repair with the validation
#: error appended. A second failure resolves to the neutral state rather than
#: spending a third call on a model that has now contradicted itself twice.
SUITABILITY_ATTEMPTS: Final[int] = 2

#: Shortest input worth a model call. Below this it is a fragment, not a
#: question, and refusing before the call is the cheapest control there is.
MIN_QUESTION_CHARS: Final[int] = 8

#: Longest input accepted, matching the client-side cap.
MAX_QUESTION_CHARS: Final[int] = 300

#: Cap on the derived live-hop phrase, matching the schema's bound.
MAX_LIVE_HOP_DESCRIPTION: Final[int] = schemas.MAX_LIVE_HOP_CHARS

_WHITESPACE = re.compile(r"\s+")


def normalise(question: str) -> str:
    """Reduce a question to its cache identity.

    Lowercased and whitespace-collapsed, so trailing spaces and capitalisation
    do not each buy their own model call.

    Args:
        question: The visitor's text.

    Returns:
        The normalised form.
    """
    return _WHITESPACE.sub(" ", question.strip().lower())


def question_hash(question: str) -> str:
    """Return the cache key for a question.

    A hash rather than the text, because this value is what gets persisted on
    the run record and what appears in telemetry -- and the question itself must
    not be kept.

    Args:
        question: The visitor's text.

    Returns:
        Hex SHA-256 of the normalised question.
    """
    return hashlib.sha256(normalise(question).encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    verdict: schemas.QuestionSuitability
    stored_at: float


#: Process-local verdict cache. Not Redis and not a table: a verdict is cheap to
#: recompute, worthless across deployments, and keeping it in memory means there
#: is no store that could accidentally come to hold question text.
_CACHE: dict[str, _Entry] = {}

#: Checks spent per session id, process-local for the same reason.
_SESSION_CHECKS: dict[str, int] = {}


def reset_state() -> None:
    """Clear the cache and the session counters. Test hook.

    Process-local state must not leak between tests, the same reason
    `embeddings/service.reset_cache()` exists.
    """
    _CACHE.clear()
    _SESSION_CHECKS.clear()


def cached(question: str) -> schemas.QuestionSuitability | None:
    """Return a still-fresh verdict for this question, if one was computed.

    Args:
        question: The visitor's text.

    Returns:
        The cached verdict, or None when there is none or it has expired.
    """
    entry = _CACHE.get(question_hash(question))
    if entry is None:
        return None
    ttl = get_settings().react_suitability_cache_ttl_hours * 3600
    if time.monotonic() - entry.stored_at > ttl:
        del _CACHE[question_hash(question)]
        return None
    return entry.verdict


def checks_remaining(session_id: str) -> int:
    """How many checks this session may still spend.

    Args:
        session_id: The browser session's opaque id.

    Returns:
        Remaining checks, never negative.
    """
    cap = get_settings().react_suitability_checks_per_session
    return max(0, cap - _SESSION_CHECKS.get(session_id, 0))


def _prechecked(question: str) -> bool:
    """Whether a question is worth spending a model call on."""
    stripped = question.strip()
    if not MIN_QUESTION_CHARS <= len(stripped) <= MAX_QUESTION_CHARS:
        return False
    # A fragment with no letters is not a question anyone can classify.
    return any(character.isalpha() for character in stripped)


async def _ask(
    question: str, validation_error: str | None
) -> schemas.QuestionSuitability:
    """Make one attempt at a verdict.

    Args:
        question: The visitor's text.
        validation_error: The previous attempt's complaint, on the repair.

    Returns:
        The validated verdict.

    Raises:
        agent_runtime.AgentLaneError: If the lane could not produce one.
    """
    instructions = with_current_date(
        load_prompt(PROMPTS_DIR, SUITABILITY_PROMPT_VERSION)
    )
    prompt = untrusted_block("visitor question", question)
    if validation_error:
        prompt += (
            "\n\nYour previous response was rejected. The system reported: "
            f"{validation_error}. Return a verdict that satisfies it."
        )

    result = await agent_runtime.run_typed_step(
        label="react-suitability",
        instructions=instructions,
        user_prompt=prompt,
        output_type=schemas.QuestionSuitability,
        # Zero tools, structurally. If this could search, the "will this
        # exercise the loop" verdict would start consuming the very quota the
        # run it precedes is about to need.
        request_limit=1,
    )
    return result.output


def preset_verdict(question: str) -> schemas.QuestionSuitability | None:
    """Derive a curated question's verdict from the catalogue, with no call.

    **A preset's structure is not something to ask a model about.** It was
    characterised by hand when the preset was written -- how many hops, which of
    them are time-variable, whether every hop needs an observation -- and that
    metadata is already in `presets.py`. Spending a model call to re-derive it
    would pay for an answer the repository already holds, and would risk the
    model disagreeing with the curation the preset set is built on.

    Args:
        question: The submitted text, matched byte-for-byte against the
            catalogue. Recognised, never claimed -- the same rule the moderation
            gate follows, so no id can buy a bypass.

    Returns:
        The derived verdict, or None when this is not a curated question.
    """
    stripped = question.strip()
    preset = next((item for item in PRESETS if item.question.strip() == stripped), None)
    if preset is None:
        return None

    live_hops = [
        hop for hop in preset.expected_hops if hop.source is HopSource.TIME_VARIABLE
    ]
    return schemas.QuestionSuitability(
        verdict="multi_hop_live" if live_hops else "multi_hop_static",
        estimated_hops=preset.hop_count,
        requires_live_info=bool(live_hops),
        live_hop_description=live_hops[0].fact[:MAX_LIVE_HOP_DESCRIPTION]
        if live_hops
        else None,
        exercises_loop=True,
        confidence="high",
        visitor_message=(
            f"This curated question chains {preset.hop_count} facts"
            + (", at least one of which changes over time." if live_hops else ".")
        ),
    )


async def assess(
    question: str, *, session_id: str
) -> schemas.QuestionSuitability | None:
    """Judge whether a question will exercise the loop.

    **Never raises and never blocks.** Every failure resolves to `None`, which
    the frontend renders as the neutral "unknown" state with Start enabled --
    see the module docstring for why that is the whole design rather than a
    convenience.

    Args:
        question: The visitor's own question.
        session_id: The browser session, for the per-session check cap.

    Returns:
        The verdict, or None when nothing could assess it. `None` covers the
        cap, the precheck, a timeout, an exhausted chain and a twice-invalid
        response alike -- the caller's response to all of them is identical, and
        distinguishing them would invite a caller to treat one as an error.
    """
    curated = preset_verdict(question)
    if curated is not None:
        logger.info("react_suitability_skipped", reason="curated_preset")
        return curated

    if not _prechecked(question):
        logger.info("react_suitability_skipped", reason="precheck")
        return None

    hit = cached(question)
    if hit is not None:
        logger.info(
            "react_suitability_cache_hit", question_hash=question_hash(question)
        )
        return hit

    if checks_remaining(session_id) == 0:
        logger.info("react_suitability_skipped", reason="session_cap")
        return None

    _SESSION_CHECKS[session_id] = _SESSION_CHECKS.get(session_id, 0) + 1
    settings = get_settings()
    validation_error: str | None = None

    for attempt in range(1, SUITABILITY_ATTEMPTS + 1):
        try:
            with observability.span("react.suitability", "react suitability check"):
                async with asyncio.timeout(settings.react_suitability_timeout_seconds):
                    verdict = await _ask(question, validation_error)
        except TimeoutError:
            # The advisory is a hint; a hint the visitor is waiting on has
            # stopped being one.
            logger.warning("react_suitability_timeout", attempt=attempt)
            return None
        except agent_runtime.AgentLaneError as exc:
            # The lane collapses "the chain is exhausted" and "the output would
            # not validate" into one type, so this repairs for both. A repair
            # against a dead chain costs one extra fast failure; refusing to
            # repair would lose the case the policy exists for. The message is
            # the framework's own -- never the question, which must not reach a
            # prompt this way or Sentry either.
            validation_error = str(exc)
            logger.warning(
                "react_suitability_rejected",
                attempt=attempt,
                error_type=type(exc).__name__,
            )
            if attempt == SUITABILITY_ATTEMPTS:
                return None
            continue

        _CACHE[question_hash(question)] = _Entry(
            verdict=verdict, stored_at=time.monotonic()
        )
        logger.info(
            "react_suitability_assessed",
            question_hash=question_hash(question),
            verdict=verdict.verdict,
            estimated_hops=verdict.estimated_hops,
            requires_live_info=verdict.requires_live_info,
            confidence=verdict.confidence,
            attempts=attempt,
        )
        return verdict

    return None
