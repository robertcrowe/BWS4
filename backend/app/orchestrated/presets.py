# Built with Spec4 AI - https://spec4.ai
"""Curated preset questions, chosen to produce visibly different pairings.

Two jobs, and the second is the one that makes this file worth writing
carefully.

The first is ordinary: presets give a visitor something to click, and because
they are pre-vetted they skip the moderation gate that free-form input passes
through -- so the common path costs nothing in latency or in a dependency on the
moderation service being reachable.

The second is evaluative. `expected_pairing` is a **human label**, not a
prediction the running app checks. It is the offline key for asking whether the
coordinator is actually reading the question: a coordinator that returned the
same two specialists every time would still satisfy every runtime constraint --
exactly two, both on the roster, distinct briefs -- and would have stopped
demonstrating delegation entirely. The capability names this as a seam to watch,
and a preset set spanning several pairings is what makes the check possible.

Six presets over five distinct pairings. Every roster member appears in at least
two, so a coordinator that quietly ignored one specialist would show up as a
pattern rather than as a single miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.app.orchestrated.schemas import Question


@dataclass(frozen=True)
class Preset:
    """One curated question and the pairing a person would expect for it.

    Attributes:
        preset_id: Stable identifier.
        question: The wording shown on the chip and sent as the question.
        expected_pairing: The two roster ids a human labelled this question
            with. Order is not meaningful; the pair is a set.
        rationale: Why those two, in one line. Kept beside the label so a later
            disagreement with the coordinator can be judged rather than just
            counted.
    """

    preset_id: str
    question: str
    expected_pairing: tuple[str, str]
    rationale: str

    def public(self) -> Question:
        """Project to the wire shape.

        Returns:
            The preset as the frontend receives it.
        """
        return Question(
            id=self.preset_id,
            text=self.question,
            expectedPairing=list(self.expected_pairing),
        )


CURATED_PRESETS: Final[tuple[Preset, ...]] = (
    Preset(
        preset_id="self-host-database",
        question="Should a small team self-host its own database?",
        expected_pairing=("technical", "financial"),
        rationale=(
            "Turns on operational mechanism and on what managed hosting costs "
            "against the engineering time self-hosting consumes."
        ),
    ),
    Preset(
        preset_id="second-language-mid-career",
        question="Is learning a second programming language worth it mid-career?",
        expected_pairing=("practical", "financial"),
        rationale=(
            "A question about effort and payoff: what learning it actually "
            "takes, and whether the return justifies the hours."
        ),
    ),
    Preset(
        preset_id="microservices-popularity",
        question="Why did microservices become so popular, and are they worth it?",
        expected_pairing=("historical", "technical"),
        rationale=(
            "Explicitly asks how the situation arose, and cannot be answered "
            "without the architectural trade-offs that drove it."
        ),
    ),
    Preset(
        preset_id="apartment-composting",
        question="How should I start composting in a small apartment?",
        expected_pairing=("practical", "technical"),
        rationale=(
            "A hands-on how-to whose failure modes -- smell, pests, moisture -- "
            "are mechanism questions underneath."
        ),
    ),
    Preset(
        preset_id="rooftop-solar",
        question="Is putting solar panels on my roof a good idea?",
        expected_pairing=("financial", "practical"),
        rationale=(
            "Dominated by payback period and by what installing and maintaining "
            "the panels actually involves."
        ),
    ),
    Preset(
        preset_id="office-return",
        question=(
            "Why are companies calling people back to the office, and will it last?"
        ),
        expected_pairing=("historical", "financial"),
        rationale=(
            "A precedent question with a cost argument underneath it -- office "
            "leases and productivity claims."
        ),
    ),
)

#: The distinct pairings the preset set covers, as frozensets so ordering never
#: makes two identical pairings look different.
DISTINCT_PAIRINGS: Final[frozenset[frozenset[str]]] = frozenset(
    frozenset(preset.expected_pairing) for preset in CURATED_PRESETS
)


def public_presets() -> list[Question]:
    """Return the presets as the frontend receives them.

    Returns:
        One `Question` per preset, in curated order.
    """
    return [preset.public() for preset in CURATED_PRESETS]
