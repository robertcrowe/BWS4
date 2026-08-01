# Built with Spec4 AI - https://spec4.ai
"""Shared content-moderation service: screen free-form visitor text before it is used.

Framework-level, not one app's helper. `moderate()` takes text and a caller
label and knows nothing about who called it -- the orchestrated-subagents app is
the first user, not the owner, so this module imports nothing from
`backend/app/orchestrated/`. Any later example app with a free-form input calls
this rather than writing a second gate.

## This service makes no model call and spends no model allowance

It talks to OpenAI's moderation endpoint, which is free of charge and entirely
separate from the OpenRouter free-model pool every example app draws on. That is
why a safety gate can sit in front of a run whose whole budget is three provider
requests without costing it a fourth. **No OpenRouter request belongs anywhere
in this file**, and nothing here is an LLM classifier: the endpoint returns a
classification, and this module parses it.

## Fail closed, and say so in a way the caller can act on

Every failure -- timeout, transport error, exhausted retries, an unparseable
response, a missing key -- returns `allowed=False`. The direction matters more
than any other decision here: an exception path that accidentally let text
through would be a silent safety hole, which is why the network call is wrapped
rather than allowed to propagate.

But "we could not check" is not "this is unsafe", and the caller has to tell
them apart: a fail-closed verdict must not consume the visitor's run allowance,
and the input must stay enabled so retrying is one click. That is what
`ModerationCategory.UNAVAILABLE` is for. **Allowance is the caller's business,
not this service's** -- `moderate()` returns a verdict and spends nothing.

## What is never retained

The `moderation_log` table has no column for the question, by design. What is
written is a *salted* hash: enough to notice the same text arriving repeatedly,
not enough to recover it. Nothing in this module logs, returns, or echoes the
submitted text -- an unsafe or injected question reflected back into the page
would be the gate defeating its own purpose.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import time
import unicodedata
from collections.abc import Awaitable, Callable
from enum import StrEnum

import httpx
import structlog
from fastapi import Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from backend.app.core.config import get_settings
from backend.app.db.models import ModerationLogEntry
from backend.app.db.session import get_db_session

logger = structlog.get_logger()

MODERATION_URL = "https://api.openai.com/v1/moderations"
MODERATION_MODEL = "omni-moderation-latest"

#: Wall-clock ceiling for the whole gate, retries included. Short on purpose:
#: this sits in front of a visitor pressing a button, and a slow safety check
#: that eventually succeeds is worse for them than a fast one that fails closed
#: and lets them press it again.
MODERATION_TIMEOUT_SECONDS = 6.0

#: Attempts, not retries: one initial call plus one retry.
MODERATION_ATTEMPTS = 2

#: Default cap on submitted text. Callers with a different input may pass their
#: own; nothing downstream assumes this number.
MAX_TEXT_CHARS = 500

#: Hard backstop on every visitor-facing string. The constants below are all
#: comfortably inside it -- this exists so a future edit cannot quietly ship a
#: paragraph into a one-line slot.
MAX_VISITOR_MESSAGE_CHARS = 140

# --- Visitor-facing copy -----------------------------------------------------
# One sentence each, second person, no internal policy quoted, and never the
# submitted text. Named constants rather than inline strings so the wording is
# reviewable in one place and testable without rendering.

MESSAGE_OK = "Your question passed the safety check."

# Visitor-facing copy. **App-neutral on purpose.** These were written for the
# orchestrated-subagents app and named its specialists; once the gate went in
# front of six apps, a refused RAG question told the visitor it "can't be sent
# to the specialists" -- naming machinery that app does not have. Caught by a
# live probe across every gated endpoint. Anything app-specific belongs in the
# caller, not here.
MESSAGE_MALFORMED = (
    "Please write that as a sentence or two, so there's something to work with."
)

MESSAGE_UNSAFE = (
    "That can't be sent to the model. Try rephrasing it, or pick one of the "
    "examples on this page."
)

MESSAGE_UNAVAILABLE = (
    "The safety check couldn't run, so nothing was sent and nothing was used "
    "up — try again, or pick one of the examples on this page."
)


class ModerationCategory(StrEnum):
    """How a submission was judged.

    Four values, and the fourth earns its place. `UNSAFE` and `UNAVAILABLE` both
    produce `allowed=False`, but they are different events: one is a decision
    about the text, the other is the absence of a decision. A caller that could
    not tell them apart would either charge a visitor for an outage or let text
    through when the gate was down.
    """

    OK = "ok"
    UNSAFE = "unsafe"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"


class ModerationVerdict(BaseModel):
    """The result of screening one piece of text.

    Attributes:
        allowed: Whether the caller may proceed. False for everything except
            `OK`.
        category: Which kind of outcome this was.
        visitor_message: One sentence to show the visitor. Never contains the
            submitted text.
    """

    allowed: bool
    category: ModerationCategory
    visitor_message: str


class _EndpointResult(BaseModel):
    """One entry of the endpoint's `results` array.

    Modelled explicitly rather than read out of a dict so that a response shape
    we did not expect raises a validation error -- and therefore fails closed --
    instead of being silently misread as "nothing flagged".
    """

    model_config = ConfigDict(extra="ignore")

    flagged: bool
    categories: dict[str, bool]
    category_scores: dict[str, float]


class _EndpointResponse(BaseModel):
    """The documented body of POST /v1/moderations."""

    model_config = ConfigDict(extra="ignore")

    id: str
    model: str
    results: list[_EndpointResult]


#: Used when no salt is configured. Generated once per process, so hashes are
#: comparable within a run and deliberately not across restarts.
_FALLBACK_SALT = secrets.token_hex(16)
_SALT_WARNED = False

_URL_ONLY = re.compile(r"^\s*(?:https?://|www\.)\S+\s*$", re.IGNORECASE)
_VOWELS = set("aeiouyàáâãäåèéêëìíîïòóôõöùúûüαεηιουω")


def _visitor_message(message: str) -> str:
    """Bound a visitor-facing string, logging if the backstop had to fire.

    Args:
        message: The candidate message.

    Returns:
        The message, truncated with an ellipsis if it exceeded the cap.
    """
    if len(message) <= MAX_VISITOR_MESSAGE_CHARS:
        return message

    logger.warning(
        "moderation_message_truncated",
        length=len(message),
        cap=MAX_VISITOR_MESSAGE_CHARS,
    )
    return message[: MAX_VISITOR_MESSAGE_CHARS - 1].rstrip() + "…"


def _verdict(category: ModerationCategory, message: str) -> ModerationVerdict:
    """Build a verdict, applying the message backstop.

    Args:
        category: The outcome.
        message: The visitor-facing sentence.

    Returns:
        The verdict. `allowed` is true only for `OK`.
    """
    return ModerationVerdict(
        allowed=category is ModerationCategory.OK,
        category=category,
        visitor_message=_visitor_message(message),
    )


def _salt() -> str:
    """Return the configured hash salt, or a process-stable substitute.

    Returns:
        The salt. Warns once when falling back, because the consequence --
        hashes not comparable across restarts -- is invisible otherwise.
    """
    global _SALT_WARNED
    configured = get_settings().moderation_hash_salt
    if configured:
        return configured

    if not _SALT_WARNED:
        logger.warning(
            "moderation_salt_unset",
            detail=(
                "using a process-stable salt; hashes will not compare across restarts"
            ),
        )
        _SALT_WARNED = True
    return _FALLBACK_SALT


def hash_question(text: str) -> str:
    """Salted hash of submitted text, for telemetry.

    Salted rather than bare: the space of plausible short questions is small
    enough to enumerate, so an unsalted digest is effectively reversible.

    Args:
        text: The submitted text. Never stored, only hashed.

    Returns:
        A hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(f"{_salt()}:{text}".encode()).hexdigest()


def _is_malformed(text: str, max_chars: int) -> bool:
    """Decide whether text is unusable without asking anyone.

    Deliberately conservative. A false positive here refuses a real question
    with an unhelpful message, which is worse than passing something odd to an
    endpoint that costs nothing -- so each rule below is one a human would agree
    with on sight.

    Args:
        text: The submitted text.
        max_chars: The caller's length cap.

    Returns:
        True when the text cannot be a usable question.
    """
    stripped = text.strip()

    if not stripped or len(stripped) > max_chars:
        return True

    # A pasted link is not a question, and forwarding it to the endpoint would
    # classify the URL rather than anything the visitor meant.
    if _URL_ONLY.match(stripped):
        return True

    letters = [char for char in stripped if unicodedata.category(char).startswith("L")]
    if not letters:
        # Pure punctuation, digits or symbols.
        return True
    if len(letters) / len(stripped) < 0.4:
        return True

    # Gibberish, in the one form that is safe to assert: no vowel anywhere. A
    # keyboard mash has none; essentially every real question in a vowelled
    # script has several. Scripts without vowel letters are excluded from the
    # rule by the check above -- they reach this line only if they also passed
    # the letter-ratio test, and `_VOWELS` is consulted only for texts that
    # contain Latin or Greek letters.
    lowered = stripped.lower()
    if any(char in "abcdefghijklmnopqrstuvwxyz" for char in lowered):
        if not any(char in _VOWELS for char in lowered):
            return True

    return False


async def _classify(text: str, api_key: str) -> _EndpointResponse:
    """Call the moderation endpoint once, with bounded retries.

    Follows the same thin-client shape as `services/web_search.py`: a direct
    `httpx` POST, no SDK, and the provider named in the symbols rather than
    hidden behind a neutral façade.

    Args:
        text: The submitted text.
        api_key: The OpenAI key.

    Returns:
        The parsed response.

    Raises:
        RetryError: If every attempt failed.
        httpx.HTTPError: On a transport failure that exhausted retries.
        pydantic.ValidationError: If the body did not match the documented
            shape -- which the caller treats as a failure, not as "nothing
            flagged".
    """
    async with httpx.AsyncClient(timeout=MODERATION_TIMEOUT_SECONDS) as client:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(MODERATION_ATTEMPTS),
            wait=wait_exponential(multiplier=0.2, max=1.0),
            reraise=True,
        ):
            with attempt:
                response = await client.post(
                    MODERATION_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": MODERATION_MODEL, "input": text},
                )
                response.raise_for_status()
                return _EndpointResponse.model_validate(response.json())

    # Unreachable: `reraise=True` means a failed final attempt propagates from
    # inside the loop. Present so the function has no implicit `None` return.
    raise RuntimeError("moderation retry loop exited without a result")


def _flagged_category(result: _EndpointResult) -> tuple[str | None, float | None]:
    """Pick the flagged category with the highest score, for the log.

    Args:
        result: One endpoint result.

    Returns:
        The category name and its score, or `(None, None)` when nothing was
        flagged. The names carry the endpoint's own spelling, slashes and all
        (`self-harm/intent`), because a renamed copy would stop matching the
        documentation an operator would go and read.
    """
    flagged = [name for name, value in result.categories.items() if value]
    if not flagged:
        return None, None

    top = max(flagged, key=lambda name: result.category_scores.get(name, 0.0))
    return top, result.category_scores.get(top)


async def moderate(
    text: str,
    calling_context: str,
    *,
    session: AsyncSession | None = None,
    max_chars: int = MAX_TEXT_CHARS,
) -> ModerationVerdict:
    """Screen free-form text and return a verdict.

    Google-style docstring per project convention.

    Args:
        text: The visitor's submitted text. Never logged, stored or echoed.
        calling_context: The app asking, for telemetry. Not sent anywhere.
        session: Optional async session for the `moderation_log` row. Optional
            because the verdict is the point and the telemetry is not: a
            caller without a session still gets a correct answer.
        max_chars: The caller's length cap.

    Returns:
        The verdict. `allowed` is true only when the endpoint returned an
        unflagged result -- every other path, including every failure, returns
        false.
    """
    started = time.monotonic()

    # Deterministic checks first: they cost nothing, they are the common
    # rejection, and short-circuiting means obviously-unusable input never
    # leaves the process.
    if _is_malformed(text, max_chars):
        verdict = _verdict(ModerationCategory.MALFORMED, MESSAGE_MALFORMED)
        await _record(
            session,
            text=text,
            calling_context=calling_context,
            category=None,
            confidence=None,
            latency_ms=_elapsed_ms(started),
            verdict=verdict,
            failed_closed=False,
        )
        return verdict

    api_key = get_settings().openai_api_key
    if not api_key:
        # Fail closed, loudly, and at call time rather than at import: a
        # deployment without the key must still start and serve every app whose
        # input is pre-vetted.
        logger.warning("moderation_key_missing", calling_context=calling_context)
        return await _unavailable(session, text, calling_context, started)

    try:
        async with asyncio.timeout(MODERATION_TIMEOUT_SECONDS):
            parsed = await _classify(text, api_key)
    except Exception as exc:  # noqa: BLE001 - every failure mode fails closed alike
        logger.warning(
            "moderation_failed_closed",
            calling_context=calling_context,
            error_type=type(exc).__name__,
        )
        return await _unavailable(session, text, calling_context, started)

    if not parsed.results:
        return await _unavailable(session, text, calling_context, started)

    result = parsed.results[0]
    category_name, confidence = _flagged_category(result)
    verdict = _verdict(
        ModerationCategory.UNSAFE if result.flagged else ModerationCategory.OK,
        MESSAGE_UNSAFE if result.flagged else MESSAGE_OK,
    )

    latency_ms = _elapsed_ms(started)
    await _record(
        session,
        text=text,
        calling_context=calling_context,
        category=category_name,
        confidence=confidence,
        latency_ms=latency_ms,
        verdict=verdict,
        failed_closed=False,
    )
    logger.info(
        "moderation_completed",
        calling_context=calling_context,
        category=verdict.category.value,
        flagged_category=category_name,
        latency_ms=latency_ms,
        failed_closed=False,
    )
    return verdict


async def _unavailable(
    session: AsyncSession | None,
    text: str,
    calling_context: str,
    started: float,
) -> ModerationVerdict:
    """Build, record and log the fail-closed verdict.

    Args:
        session: Optional async session for telemetry.
        text: The submitted text, hashed and then discarded.
        calling_context: The app asking.
        started: Monotonic start time.

    Returns:
        A verdict with `allowed=False` and category `UNAVAILABLE`.
    """
    verdict = _verdict(ModerationCategory.UNAVAILABLE, MESSAGE_UNAVAILABLE)
    latency_ms = _elapsed_ms(started)

    await _record(
        session,
        text=text,
        calling_context=calling_context,
        category=None,
        confidence=None,
        latency_ms=latency_ms,
        verdict=verdict,
        failed_closed=True,
    )
    logger.info(
        "moderation_completed",
        calling_context=calling_context,
        category=verdict.category.value,
        latency_ms=latency_ms,
        failed_closed=True,
    )
    return verdict


def _elapsed_ms(started: float) -> int:
    """Milliseconds since a monotonic start point.

    Args:
        started: The value `time.monotonic()` returned earlier.

    Returns:
        Elapsed milliseconds, rounded.
    """
    return int((time.monotonic() - started) * 1000)


async def _record(
    session: AsyncSession | None,
    *,
    text: str,
    calling_context: str,
    category: str | None,
    confidence: float | None,
    latency_ms: int,
    verdict: ModerationVerdict,
    failed_closed: bool,
) -> None:
    """Write one `moderation_log` row.

    The text is hashed on the way in and never held. The table has no column
    for it, so this is enforced by the schema as well as by this function.

    Args:
        session: Optional async session. No session, no row -- telemetry must
            never be the reason a verdict fails to reach the caller.
        text: The submitted text, used only to compute the hash.
        calling_context: The app asking.
        category: The flagged category name, or None.
        confidence: That category's score, or None.
        latency_ms: How long the gate took.
        verdict: The verdict being recorded.
        failed_closed: Whether this was a refusal to decide rather than a
            decision.
    """
    if session is None:
        return

    session.add(
        ModerationLogEntry(
            question_hash=hash_question(text),
            app_name=calling_context,
            category=category,
            confidence=confidence,
            latency_ms=latency_ms,
            blocked=not verdict.allowed,
            failed_closed=failed_closed,
        )
    )
    await session.commit()


#: What a route receives from `Depends(get_moderator)`: text and a caller label
#: in, a verdict out. A callable rather than a class so a test can substitute a
#: plain function.
Moderator = Callable[[str, str], Awaitable[ModerationVerdict]]


async def get_stateless_moderator() -> Moderator:
    """Provide the moderation service with no database behind it.

    For the one endpoint that deliberately takes no session -- the embeddings
    placement route, which is pure computation and reaches no datastore. The
    cost is the `moderation_log` row: the verdict is still enforced, it is just
    not recorded. A provider rather than a bare callable so a test can replace
    it through `app.dependency_overrides` and stay offline.

    Returns:
        A callable taking text and a caller label and returning a verdict.
    """

    async def _moderate(text: str, calling_context: str) -> ModerationVerdict:
        return await moderate(text, calling_context)

    return _moderate


async def get_moderator(
    session: AsyncSession = Depends(get_db_session),
) -> Moderator:
    """Provide the moderation service, bound to this request's session.

    Mirrors `api/embeddings.get_embedder`: a provider returning the callable
    rather than the callable itself, so a test can replace the whole gate
    through `app.dependency_overrides` without patching a module attribute.

    Args:
        session: The request-scoped session, injected.

    Returns:
        A callable taking text and a caller label and returning a verdict.
    """

    async def _moderate(text: str, calling_context: str) -> ModerationVerdict:
        return await moderate(text, calling_context, session=session)

    return _moderate
