# Built with Spec4 AI - https://spec4.ai
"""Checking the explanations against the arithmetic. Pure, deterministic, blocking.

The signature failure this module exists for is **post-hoc rationalisation**:
a model asserting that a concession was forced by a constraint that was not
actually binding. That falsehood is invisible without recomputing slack, and
the narrative shape is so plausible that it reads as the most authoritative
thing on the page — it arrives last, framed as the explanation of everything
before it.

So the model's claims are treated as **hypotheses the code checks**, never as
findings. Four checks, all recomputed from the recorded run:

1. `computed_stance` — what the party actually did on each axis, from the
   opening-to-final delta. A claimed stance that contradicts it is flagged.
2. `no_invented_numbers` — every numeral in the generated text must appear in
   the input payload. Numeric fields are echo-only; a rounded price or an
   off-by-one delivery figure reads as authoritative and is not checkable by
   eye.
3. `constraint_slack` — "held firm because X" is only true if the final value
   sits *at* X. A claim cited against a constraint the bid is well clear of is
   the rationalisation, named.
4. `mentions_rival` — no party's block may name the other seller or carry its
   sealed values. The reveal is the one panel that unseals anything, so it is
   the one place a leak would be least surprising and most damaging.

Nothing here calls a model, touches a database, or reads a clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from backend.app.collab.explain_schemas import (
    AxisStance,
    PartyReveal,
    SensitivityExplanation,
)
from backend.app.collab.scenarios import AxisDirection, AxisId, Scenario

#: Fraction of an axis's declared range within which a final value counts as
#: sitting *at* a constraint.
#:
#: Five per cent. Tight enough that "held firm because of my cost floor" has to
#: mean the bid is genuinely against the floor, loose enough that a seller
#: quoting a round number just above its floor is not called a liar.
SLACK_TOLERANCE: Final[float] = 0.05

#: Verbs that would claim the projection settles what only a re-run can.
#:
#: The teaching point of the sensitivity panel is that it is a *projection from
#: recorded bids*. "Would have won" states a fact about a world that does not
#: exist; "would likely have won" states a projection. The difference is the
#: whole honesty of the panel.
OVERCLAIMING_PHRASES: Final[tuple[str, ...]] = (
    "would have won",
    "would have chosen",
    "definitely",
    "certainly",
    "guaranteed",
    "proves",
    "confirms that",
)

_NUMERAL = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Findings:
    """What the checks found. Empty means the model's output stands as written.

    Attributes:
        violations: Machine-readable codes, for the repair prompt and the log.
        detail: One human-readable line per violation, for the repair prompt.
    """

    violations: list[str] = field(default_factory=list)
    detail: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing was flagged."""
        return not self.violations

    def add(self, code: str, message: str) -> None:
        """Record one violation.

        Args:
            code: A short machine-readable code.
            message: What went wrong, phrased for the repair prompt.
        """
        self.violations.append(code)
        self.detail.append(message)

    def as_prompt(self) -> str:
        """Render the findings as the instruction for the one repair attempt."""
        return "\n".join(f"- {line}" for line in self.detail)


def computed_stance(
    scenario: Scenario, axis: AxisId, opening: float, final: float
) -> AxisStance:
    """Recompute what a party did on one axis, from the values it actually bid.

    The fact the model's claim is checked against. "Conceded" means the final
    value is better *for the buyer* than the opening one — which depends on the
    axis's direction, so this cannot be a simple comparison.

    Args:
        scenario: The scenario, supplying each axis's direction.
        axis: The axis in question.
        opening: The opening bid's value.
        final: The best-and-final value.

    Returns:
        `CONCEDED` when the party moved in the buyer's favour, `HELD_FIRM`
        otherwise. No movement is holding firm, not conceding nothing.
    """
    direction = scenario.axis(axis).direction
    improved = (
        final < opening
        if direction is AxisDirection.LOWER_IS_BETTER
        else final > opening
    )
    return AxisStance.CONCEDED if improved else AxisStance.HELD_FIRM


def constraint_is_binding(
    scenario: Scenario, axis: AxisId, final: float, limit: float
) -> bool:
    """Whether a final value actually sits against a constraint.

    Recomputed slack, which is the only way to tell a real "I could not move"
    from a plausible one. A bid well clear of the limit it cites did not hold
    firm *because* of it.

    Args:
        scenario: The scenario, supplying the axis's range.
        axis: The axis in question.
        final: The value the party ended on.
        limit: The sealed constraint's value.

    Returns:
        True when the gap is within `SLACK_TOLERANCE` of the axis's range.
    """
    term = scenario.axis(axis)
    span = abs(term.best - term.worst)
    if span == 0:
        return True
    return abs(final - limit) / span <= SLACK_TOLERANCE


def numeric_tokens(text: str) -> set[str]:
    """Extract every numeral appearing in text.

    Args:
        text: The generated prose.

    Returns:
        Each numeral as it was written.
    """
    return set(_NUMERAL.findall(text))


def no_invented_numbers(text: str, allowed: frozenset[str]) -> set[str]:
    """Return numerals in the text that were not in the input payload.

    Numeric fields are echo-only. A model that computes a figure — a rounded
    price, a percentage, a difference — has produced something the visitor
    cannot check and the run cannot vouch for.

    Args:
        text: The generated prose.
        allowed: Every figure the model was given, in every rendering it might
            reasonably use.

    Returns:
        The invented numerals, empty when the text stayed within its whitelist.
    """
    return {token for token in numeric_tokens(text) if token not in allowed}


def mentions_rival(block: str, rival_id: str, rival_corpus: frozenset[str]) -> bool:
    """Whether a party's block names the rival or carries its sealed values.

    Args:
        block: The rendered text of one party's reveal.
        rival_id: The other seller's id.
        rival_corpus: The rival's sealed values, as rendered strings.

    Returns:
        True when the block leaks.
    """
    lowered = block.lower()
    if rival_id.lower() in lowered:
        return True
    return any(value in block for value in rival_corpus)


def overclaiming_phrases(text: str) -> list[str]:
    """Return deterministic verbs that overclaim what a projection can settle.

    Args:
        text: The narration.

    Returns:
        The offending phrases, in the order they appear in the banned list.
    """
    lowered = text.lower()
    return [phrase for phrase in OVERCLAIMING_PHRASES if phrase in lowered]


@dataclass(frozen=True)
class AxisFact:
    """The recorded truth about one party on one axis.

    Attributes:
        axis: Which term.
        opening: The opening bid's value.
        final: The best-and-final value.
        stance: What the party actually did, recomputed.
        binding: Which of the party's own constraints the final value sits
            against, or None when none does.
    """

    axis: AxisId
    opening: float
    final: float
    stance: AxisStance
    binding: str | None


def check_reveal(
    block: PartyReveal,
    *,
    facts: dict[AxisId, AxisFact],
    allowed_numbers: frozenset[str],
    allowed_constraints: tuple[str, ...],
    rival_id: str | None,
    rival_corpus: frozenset[str],
) -> Findings:
    """Check one party's reveal block against the recorded run.

    Args:
        block: What the model produced for this party.
        facts: The recomputed truth, per axis.
        allowed_numbers: Every figure the model was given.
        allowed_constraints: The constraint ids this party may cite — its own.
        rival_id: The other seller's id, or None for the buyer.
        rival_corpus: The rival's sealed values, as rendered strings.

    Returns:
        Everything that did not check out.
    """
    findings = Findings()

    if rival_id is not None:
        rendered = f"{block.headline} " + " ".join(
            axis.explanation for axis in block.axes
        )
        if mentions_rival(rendered, rival_id, rival_corpus):
            findings.add(
                "rival_mentioned",
                f"The block for {block.party_id} refers to the other supplier or "
                "quotes one of its sealed values. Each party's reveal must speak "
                "only about that party.",
            )

    seen: set[AxisId] = set()
    for entry in block.axes:
        try:
            axis = AxisId(entry.axis.lower())
        except ValueError:
            findings.add(
                "unknown_axis",
                f"{entry.axis!r} is not one of this scenario's terms.",
            )
            continue
        seen.add(axis)

        fact = facts.get(axis)
        if fact is None:
            continue

        if entry.stance != fact.stance.value:
            findings.add(
                "stance_mismatch",
                f"You said {block.party_id} {entry.stance} on {axis.value}, but its "
                f"bid moved from {fact.opening} to {fact.final}, which is "
                f"{fact.stance.value}.",
            )

        if entry.opening_value != fact.opening or entry.final_value != fact.final:
            findings.add(
                "value_mismatch",
                f"The {axis.value} values for {block.party_id} must be echoed "
                f"exactly: opening {fact.opening}, final {fact.final}.",
            )

        cited = entry.binding_constraint
        if cited is not None and cited not in allowed_constraints:
            findings.add(
                "foreign_constraint",
                f"{cited!r} is not one of {block.party_id}'s own constraints.",
            )
        elif cited is not None and cited != fact.binding:
            findings.add(
                "constraint_not_binding",
                f"You said {block.party_id}'s {axis.value} was bound by {cited}, "
                f"but its final value of {fact.final} is not against that limit. "
                "Use null if no constraint forced the move.",
            )

        invented = no_invented_numbers(entry.explanation, allowed_numbers)
        if invented:
            findings.add(
                "invented_number",
                f"The {axis.value} explanation for {block.party_id} contains "
                f"{sorted(invented)}, which appear nowhere in the record. Only "
                "repeat figures you were given.",
            )

    missing = sorted(axis.value for axis in facts if axis not in seen)
    if missing:
        findings.add(
            "missing_axis",
            f"{block.party_id} has no explanation for: {', '.join(missing)}.",
        )

    return findings


def check_sensitivity(
    output: SensitivityExplanation,
    *,
    computed_winner: str,
    allowed_numbers: frozenset[str],
) -> Findings:
    """Check the sensitivity narration against the computed projection.

    The model narrates arithmetic it was given. It may not contradict it, and
    it may not phrase a projection as a settled fact.

    Args:
        output: What the model produced.
        computed_winner: Who the code's re-scoring favours, or `too_close`.
        allowed_numbers: Every figure the model was given.

    Returns:
        Everything that did not check out.
    """
    findings = Findings()

    if output.likely_winner != computed_winner:
        findings.add(
            "contradicts_computation",
            f"The re-scoring was computed before you were asked, and it gives "
            f"{computed_winner!r}. You said {output.likely_winner!r}. Narrate the "
            "computed result; do not re-derive it.",
        )

    invented = no_invented_numbers(
        f"{output.narration} {output.caveat}", allowed_numbers
    )
    if invented:
        findings.add(
            "invented_number",
            f"Your narration contains {sorted(invented)}, which appear nowhere in "
            "the record. Only repeat figures you were given.",
        )

    overclaims = overclaiming_phrases(output.narration)
    if overclaims:
        findings.add(
            "overclaims",
            f"{overclaims} states the projection as settled fact. Only an actual "
            "re-run would settle it — write it as a projection.",
        )

    if not output.caveat.strip():
        findings.add(
            "missing_caveat",
            "The caveat is required: this is a projection from the recorded bids, "
            "not a re-run.",
        )

    return findings
