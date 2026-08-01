# Built with Spec4 AI - https://spec4.ai
"""The shared safety gate every app puts in front of visitor-written text.

`services/moderation.py` decides whether a piece of text is safe. This decides
*when to ask* — and the answer is: whenever the text was written by a visitor,
and never when it is one of the app's own curated examples.

## Curated text is recognised, not claimed

A curated example skips the gate, so "this is a preset" is a statement worth
lying about. Nothing here accepts an id: the app hands over its own canonical
strings and the submitted text has to **byte-match** one of them. There is no
token a caller could attach to arbitrary text to get it past the gate.

The failure mode is deliberately benign. If an app's client-side list ever
drifts from the server's, the effect is that an example stops being recognised
and gets moderated like free text — a lost exemption, never a bypass.

## Every caller must keep the two refusals apart

`BLOCKED` means the text was examined and refused. `UNAVAILABLE` means nothing
examined it. They both stop the request, and telling a visitor their question
was rejected when the checker was simply down is a claim with nothing behind
it. This returns them as distinct codes for the same reason `ModerationCategory`
distinguishes them, and an orchestrated run once flattened them and had to be
fixed.

**With no `OPENAI_API_KEY` configured the gate fails closed**, so every
free-text path in every app is refused with `moderation_unavailable` while
curated examples keep working. That is the designed behaviour of a safety gate
and not a bug — but it is also the state an unconfigured deployment sits in
permanently, so it is worth knowing before wiring this in front of an app.

## Where this goes in an app's request handling

Before anything is spent. The gate costs no model allowance of its own — the
moderation endpoint is free and reaches a different provider — so running it
first means a refused request never touches a quota, and a visitor is never
charged for a question that was never going to run.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services.moderation import (
    ModerationCategory,
    ModerationVerdict,
    Moderator,
    moderate,
)

logger = structlog.get_logger()

#: Returned when the text was examined and refused.
CODE_BLOCKED: Final[str] = "moderation_blocked"

#: Returned when nothing could examine the text.
CODE_UNAVAILABLE: Final[str] = "moderation_unavailable"


@dataclass(frozen=True)
class GateOutcome:
    """Whether a piece of visitor text may proceed.

    Attributes:
        allowed: True when the request may continue.
        code: `moderation_blocked` or `moderation_unavailable`, when refused.
        message: What to show the visitor, when refused.
        curated: True when the text was recognised as one of the app's own
            examples and skipped the gate entirely. Reported so telemetry can
            tell "passed the gate" from "never needed it".
    """

    allowed: bool
    code: str | None = None
    message: str | None = None
    curated: bool = False


def is_curated(text: str, curated: Collection[str]) -> bool:
    """Whether the submitted text is byte-identical to a curated example.

    Args:
        text: The submitted text.
        curated: The app's own canonical example strings.

    Returns:
        True when the text matches one exactly. Whitespace at the ends is
        ignored, because a chip's text can pick up a stray space on its way
        through an input box; nothing else is normalised, so a rewritten
        example is treated as what it is — the visitor's own words.
    """
    stripped = text.strip()
    return any(stripped == example.strip() for example in curated)


async def check_free_text(
    text: str,
    *,
    app_name: str,
    curated: Collection[str] = (),
    session: AsyncSession | None = None,
    moderator: Moderator | None = None,
) -> GateOutcome:
    """Run the safety gate over text a visitor wrote, unless it is curated.

    Google-style docstring per project convention.

    Args:
        text: The submitted text.
        app_name: The calling app, for the moderation log and telemetry.
        curated: The app's canonical example strings, which skip the gate.
        session: An async session, so the verdict is recorded in
            `moderation_log`. Optional: an app that deliberately touches no
            database can omit it and lose only the log row.
        moderator: The gate itself, injected so a caller can substitute it and
            so this module stays testable without a provider. When omitted the
            real gate is used **with the session**, which is what puts a row in
            `moderation_log` -- passing `moderate` directly here would type-check
            and quietly log nothing.

    Returns:
        The outcome. A curated example returns `allowed=True` without any
        network call at all.
    """
    if is_curated(text, curated):
        logger.info("text_gate_skipped", app_name=app_name, reason="curated_example")
        return GateOutcome(allowed=True, curated=True)

    if moderator is None:

        async def moderator(check: str, context: str) -> ModerationVerdict:
            return await moderate(check, context, session=session)

    verdict = await moderator(text, app_name)
    if verdict.allowed:
        return GateOutcome(allowed=True)

    code = (
        CODE_UNAVAILABLE
        if verdict.category is ModerationCategory.UNAVAILABLE
        else CODE_BLOCKED
    )
    logger.info(
        "text_gate_refused",
        app_name=app_name,
        code=code,
        moderation_category=verdict.category.value,
    )
    return GateOutcome(allowed=False, code=code, message=verdict.visitor_message)


#: HTTP status for each refusal. Separate codes because they are different
#: problems: a blocked question is the visitor's to fix by rewording, an
#: unavailable gate is the operator's and retrying may work.
_STATUS: Final[dict[str, int]] = {CODE_BLOCKED: 422, CODE_UNAVAILABLE: 503}


def status_for(code: str) -> int:
    """Return the HTTP status a refusal code should be reported with.

    Kept here rather than in each API so six apps cannot disagree about
    whether a blocked question is a 4xx or a 5xx. Deliberately returns a plain
    `int` so this module stays free of a web framework.

    Args:
        code: `moderation_blocked` or `moderation_unavailable`.

    Returns:
        422 for a refusal the visitor can act on, 503 for one they cannot.
    """
    return _STATUS.get(code, 503)
