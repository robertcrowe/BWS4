# Built with Spec4 AI - https://spec4.ai
"""The six curated Router requests, as typed Python literals.

Following `react/presets.py`: frozen dataclasses rather than a YAML or JSON
fixture, so mypy checks them, a redeploy replaces them with no migration, and
there is no serialisation dependency to add.

## THIS CATALOGUE STORES REQUESTS ONLY. IT NEVER STORES AN ANSWER.

Two of the six turn on facts that move (the most recent Formula 1 race, the
next crewed launch to the ISS). A stored answer would be stale within weeks and
then wrong on screen while looking authoritative. Every answer comes from the
dispatched route on every run.

## What the expected route and reason are for

Each preset carries the route that is the right home for it and one line
saying why, so a later reader can judge whether a disagreement is the router's
fault or the preset's. The expected route is what agreement is measured
against; the visitor UI does not show it before a run, but the API carries it
so agreement can be computed and explained.

## The two control/near-miss pairs

- **Conversion**: p1 is a real unit conversion (control); p6 looks like one but
  asks for an explanation (near-miss), so its home is a single call.
- **Space**: p3 is answerable from the Apollo 11 document in the RAG dataset
  (control); p5 names the ISS, which is in the dataset, but asks a time-variable
  question (near-miss), so its home is search plus generation.

A pair is what makes the agreement history informative: a router that matches
on surface words gets the control right and the near-miss wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from backend.app.router.constants import (
    DETERMINISTIC_EVALUATOR,
    RETRIEVAL,
    SEARCH_GENERATION,
    SINGLE_CALL,
    RouteId,
)

#: Bumped by adding a new catalogue alongside this one, never by editing a
#: shipped entry in place. Agreement history rows are keyed by preset id, and an
#: id whose wording changed underneath it would merge two questions' records.
PRESET_SET_VERSION: Final[str] = "v1"


class PairName(StrEnum):
    """Which control/near-miss pair a preset belongs to."""

    CONVERSION = "conversion"
    SPACE = "space"


class PairRole(StrEnum):
    """A preset's role within its pair."""

    #: The request whose surface wording and expected route agree.
    CONTROL = "control"
    #: Shares the control's surface wording but belongs on a different route.
    NEAR_MISS = "near_miss"


@dataclass(frozen=True)
class PairMembership:
    """A preset's place in one of the two control/near-miss pairs.

    Attributes:
        pair: Which pair.
        role: Control or near-miss.
    """

    pair: PairName
    role: PairRole


@dataclass(frozen=True)
class RouterPreset:
    """One curated request and the route it belongs on.

    Attributes:
        id: Stable identifier, `p1`..`p6`. Keys the agreement history, so it
            must never be reused for different wording.
        request: The request put to the router, verbatim.
        expected_route: The route that is the right home for this request.
        reason: One line on why that route is the right home.
        pairing: The control/near-miss pair this preset belongs to, if any.
        evaluator_expression: For a preset whose expected route is the
            deterministic evaluator, the request rewritten in the evaluator's
            grammar. Not an answer -- the evaluator computes that -- but the
            input a forced comparison re-run needs, since the re-run does not
            call the router that would otherwise write it. Never shown to the
            router.
    """

    id: str
    request: str
    expected_route: RouteId
    reason: str
    pairing: PairMembership | None = None
    evaluator_expression: str | None = None


PRESETS: Final[tuple[RouterPreset, ...]] = (
    RouterPreset(
        id="p1",
        request="Convert 72 km/h to metres per second.",
        expected_route=DETERMINISTIC_EVALUATOR,
        reason=(
            "A pure calculation within the evaluator's scope that needs no "
            "model; control for the conversion pair."
        ),
        pairing=PairMembership(PairName.CONVERSION, PairRole.CONTROL),
        evaluator_expression="72 km/h to m/s",
    ),
    RouterPreset(
        id="p2",
        request=(
            'Rewrite "hey, can u send me the report asap" so it sounds professional.'
        ),
        expected_route=SINGLE_CALL,
        reason="Needs language generation but no outside facts.",
    ),
    RouterPreset(
        id="p3",
        request=(
            "How long did Apollo 11 spend on the lunar surface, and who stayed "
            "in orbit?"
        ),
        expected_route=RETRIEVAL,
        reason=(
            "Answerable from the Apollo 11 document in the dataset; control for "
            "the space pair."
        ),
        pairing=PairMembership(PairName.SPACE, PairRole.CONTROL),
    ),
    RouterPreset(
        id="p4",
        request="Who won the most recent Formula 1 race?",
        expected_route=SEARCH_GENERATION,
        reason=(
            "A time-variable fact that neither the model's memory nor the "
            "dataset can be trusted to hold."
        ),
    ),
    RouterPreset(
        id="p5",
        request="When is the next crewed launch to the International Space Station?",
        expected_route=SEARCH_GENERATION,
        reason=(
            "Near-miss: the subject is in the dataset but the answer is time-variable."
        ),
        pairing=PairMembership(PairName.SPACE, PairRole.NEAR_MISS),
    ),
    RouterPreset(
        id="p6",
        request="Explain why 1 mile is about 1.609 kilometres.",
        expected_route=SINGLE_CALL,
        reason=(
            "Near-miss: it looks like a unit conversion but asks for an "
            "explanation, not a calculation."
        ),
        pairing=PairMembership(PairName.CONVERSION, PairRole.NEAR_MISS),
    ),
)

#: Preset ids, for cheap membership checks at the request boundary.
PRESET_IDS: Final[frozenset[str]] = frozenset(preset.id for preset in PRESETS)

#: The canonical request strings, byte for byte. The shared moderation gate
#: recognises curated text by matching against these rather than trusting an
#: id, following `react/presets.py`.
PRESET_REQUESTS: Final[frozenset[str]] = frozenset(preset.request for preset in PRESETS)


def get_preset(preset_id: str) -> RouterPreset | None:
    """Look up one preset by id.

    Args:
        preset_id: The id from the request, unvalidated.

    Returns:
        The preset, or None when no preset carries that id.
    """
    for preset in PRESETS:
        if preset.id == preset_id:
            return preset
    return None
