# Built with Spec4 AI - https://spec4.ai
"""Detect a model chain that has quietly stopped serving from its head.

The failure this exists for produces **no error at all**. When the head of a
chain is withdrawn, rate-limited, or has spent a daily allowance, the fallback
machinery walks past it and the next model answers correctly -- so the request
succeeds, Sentry's auto-integrations see a 200, and the only symptom is that
every response now comes from further down a list ordered by preference. Live,
that state persisted long enough to be reported twice as "this is slow", and
both times it took a probe to find out why.

`note_failure` and `note_rate_limit` cover the cases where something *told* us a
slug is unusable. This covers the rest: a head that is simply never chosen, for
whatever reason, including reasons nothing reported.

## What is measured, and what it deliberately is not

Consecutive misses, not a rate and not a clock. A healthy head serves nearly
every request, so a run of `HEAD_MISS_THRESHOLD` consecutive requests served by
anything else is already far outside normal -- while a *proportion* would need a
window to be meaningful and a clock would fire on a quiet night as readily as on
a broken chain.

Two states are excluded before alerting, because neither is rot:

* A head whose provider has no key configured. That is a deployment running on
  fewer providers on purpose, and it would otherwise alert forever.
* A head that is currently benched. Something already reported that, and this
  would be the second alarm for one fault.

State is process-local and resets on restart, which on a free dyno means it
resets on every cold start. That is a real limit and not worth fixing here: the
counter is a live-process smoke detector, not a historical record, and the
events it emits are what persist.
"""

from __future__ import annotations

import time

import structlog

from backend.app.core.observability import report_model_health
from backend.app.services import model_registry

logger = structlog.get_logger()

#: Consecutive requests served by something other than the head before this is
#: treated as rot rather than noise. Ten because an intermittent head still
#: wins most requests -- `groq/llama-3.3-70b-versatile` fails roughly two
#: attempts in three and would not reach this -- while a withdrawn or exhausted
#: one misses every single time and trips it inside a minute of real traffic.
HEAD_MISS_THRESHOLD = 10

#: One alert per chain per hour. The condition stays true for as long as the
#: head is unusable, so without this every subsequent request would re-report a
#: fault the operator has already been told about.
ALERT_COOLDOWN_SECONDS = 60 * 60.0

#: chain name -> consecutive requests not served by that chain's head.
_misses: dict[str, int] = {}

#: chain name -> monotonic timestamp of the last alert emitted for it.
_alerted: dict[str, float] = {}

#: The chains watched, by the name used in logs and Sentry tags.
_WATCHED = {
    "tool": model_registry.TOOL_MODEL_CHAIN,
    "generation": model_registry.GENERATION_MODEL_CHAIN,
}


def note_served(model: str) -> None:
    """Record which slug served a request, and alert if a head has gone quiet.

    Called from both model lanes at the point each already resolves the serving
    slug, so neither has to learn anything new. Cheap and synchronous: two dict
    lookups per request in the common case.

    Args:
        model: The serving slug, already normalized to its registry form. A
            slug belonging to no watched chain is ignored rather than treated
            as a miss -- it says nothing about that chain's head.
    """
    for name, chain in _WATCHED.items():
        if model not in chain:
            continue
        if model == chain[0]:
            _misses[name] = 0
            continue
        _misses[name] = _misses.get(name, 0) + 1
        if _misses[name] >= HEAD_MISS_THRESHOLD:
            _maybe_alert(name, chain, served_by=model)


def _maybe_alert(name: str, chain: list[str], *, served_by: str) -> None:
    """Report a chain serving from its tail, unless it is explained or recent.

    Args:
        name: The chain's name, for the log and the Sentry tag.
        chain: The chain itself, to inspect its head.
        served_by: The slug actually serving, so the report says how far down
            the chain requests have fallen.
    """
    head = chain[0]

    # One check covers both non-rot cases, because `active_chain` already drops
    # a slug whose provider has no key *and* one inside a cooldown. So this is
    # silent when the head belongs to a provider this deployment deliberately
    # does not configure, and silent when something has already benched it --
    # which is the case that would otherwise raise a second alarm for one
    # fault, the noisier of the two. A separate `configured_providers()` test
    # was written first and was pure redundancy; a mutation removing it changed
    # no behaviour, which is how it was caught.
    if head not in model_registry.active_chain(chain):
        return

    now = time.monotonic()
    if now - _alerted.get(name, float("-inf")) < ALERT_COOLDOWN_SECONDS:
        return
    _alerted[name] = now

    position = chain.index(served_by) + 1
    logger.warning(
        "chain_head_not_serving",
        chain=name,
        head=head,
        served_by=served_by,
        position=position,
        consecutive_misses=_misses[name],
    )
    report_model_health(
        "chain_head_not_serving",
        chain=name,
        head=head,
        served_by=served_by,
        position=position,
    )


def reset() -> None:
    """Clear the counters. Test hook -- process-local state must not leak."""
    _misses.clear()
    _alerted.clear()
