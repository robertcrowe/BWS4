# Built with Spec4 AI - https://spec4.ai
"""The fixed roster of four knowledge-only specialists.

**The four are different modes of reasoning, not four topics.** That distinction
is the whole reason this demonstrates orchestration rather than routing. A roster
split by subject -- databases, gardening, finance -- would make the coordinator's
job a lookup, and two specialists asked about the same question would return
overlapping answers that a merge step has nothing to reconcile. Split by *mode*,
the same question genuinely yields different material: how a thing works, what it
costs, how it came to be, and what to actually do on Monday.

Each entry carries more than the frontend sees. `system_prompt_fragment` is how a
specialist is instructed; `angle_exclusion` is the clause that keeps it in its
lane, which is what stops two columns converging into the same essay; and
`keyword_affinities` back the rules-based fallback pairing used when the
coordinator's own choice cannot be trusted.

The roster is a module-level constant rather than a database table on purpose:
it is the closed set the coordinator's delegation is validated against, and a
redeploy replaces it without a migration or a moment of the showcase being down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.app.orchestrated.schemas import Specialist


@dataclass(frozen=True)
class RosterEntry:
    """One specialist, including the parts that never leave the server.

    Attributes:
        id: Stable identifier. The coordinator must return exactly two of these.
        display_name: Column heading the visitor reads.
        scope: One line saying what this specialist covers.
        color: Column accent, from the design mock's palette.
        system_prompt_fragment: The cognitive mode, written as the instruction
            the specialist actually receives.
        angle_exclusion: What this specialist must leave to the others. Without
            it a specialist drifts into covering everything and the two columns
            stop being visibly different.
        keyword_affinities: Signals for the rules-based fallback pairing. A
            weak signal, used only when the coordinator's own choice is
            unusable -- never to override a valid one.
    """

    id: str
    display_name: str
    scope: str
    color: str
    system_prompt_fragment: str
    angle_exclusion: str
    keyword_affinities: tuple[str, ...]

    def public(self) -> Specialist:
        """Project to the four fields that cross the wire.

        Returns:
            The presentational view of this entry. The prompt fragment and the
            exclusion clause are deliberately not included: they are how this
            specialist is governed, and publishing them would hand anyone
            shaping a question the text they need to work around.
        """
        return Specialist(
            id=self.id,
            displayName=self.display_name,
            scope=self.scope,
            color=self.color,
        )


SPECIALIST_ROSTER_CONFIG: Final[tuple[RosterEntry, ...]] = (
    RosterEntry(
        id="technical",
        display_name="Technical Analyst",
        scope=(
            "Mechanism and trade-offs — how the thing actually works, and what "
            "it costs you in complexity."
        ),
        color="#4ea1ff",
        system_prompt_fragment=(
            "You reason about mechanism and trade-offs. Explain how the thing "
            "works, what it is made of, and what breaks when it is pushed. Every "
            "claim you make should name the trade being made: choosing this "
            "gives up that. Where a decision has a genuine engineering tension, "
            "say what sits on each side of it rather than declaring a winner."
        ),
        angle_exclusion=(
            "Do not price anything, do not recount how the technology came to "
            "exist, and do not give step-by-step instructions. Other "
            "specialists cover cost, history and execution."
        ),
        keyword_affinities=(
            "how",
            "architecture",
            "performance",
            "scale",
            "database",
            "protocol",
            "trade-off",
            "design",
            "latency",
            "security",
        ),
    ),
    RosterEntry(
        id="financial",
        display_name="Financial Analyst",
        scope=(
            "Cost and quantitative framing — what it costs, what it saves, and "
            "what the numbers have to be for it to pay."
        ),
        color="#f6b93b",
        system_prompt_fragment=(
            "You reason in costs and quantities. Put numbers on the question: "
            "what is spent, what is saved, over what period, and what the "
            "break-even looks like. Where you do not have real figures, say "
            "what would have to be true for the decision to pay off, and name "
            "the quantity a reader should go and measure."
        ),
        angle_exclusion=(
            "Do not explain the underlying mechanism, do not recount history, "
            "and do not give hands-on instructions. Other specialists cover "
            "those."
        ),
        keyword_affinities=(
            "cost",
            "worth",
            "budget",
            "price",
            "cheaper",
            "expensive",
            "invest",
            "roi",
            "save",
            "afford",
        ),
    ),
    RosterEntry(
        id="historical",
        display_name="Historical Contextualiser",
        scope=(
            "Precedent and context — how the situation arose, what was tried "
            "before, and what has changed since."
        ),
        color="#7c5cff",
        system_prompt_fragment=(
            "You reason from precedent. Explain how the present situation came "
            "about: what was tried before, why it was adopted or abandoned, and "
            "what has changed since that makes the question live again. Use the "
            "past to say which parts of the question are genuinely new and which "
            "are a repeat of something already settled."
        ),
        angle_exclusion=(
            "Do not explain current mechanism in depth, do not price anything, "
            "and do not give instructions for today. Your contribution is why "
            "the question looks the way it does."
        ),
        keyword_affinities=(
            "why",
            "history",
            "became",
            "originally",
            "used to",
            "traditionally",
            "evolved",
            "popular",
            "legacy",
            "changed",
        ),
    ),
    RosterEntry(
        id="practical",
        display_name="Practical Practitioner",
        scope="Concrete steps — what to do, in what order, and at what effort.",
        color="#34d399",
        system_prompt_fragment=(
            "You reason in concrete actions. Say what to do, in what order, and "
            "roughly what each step costs in effort and elapsed time. Be "
            "specific enough that a reader could start this afternoon, and name "
            "the step where people most often get stuck."
        ),
        angle_exclusion=(
            "Do not explain underlying mechanism, do not build a financial "
            "case, and do not recount history. Assume the decision is made and "
            "say how to carry it out."
        ),
        keyword_affinities=(
            "how do i",
            "start",
            "steps",
            "setup",
            "install",
            "beginner",
            "practice",
            "maintain",
            "workflow",
            "checklist",
        ),
    ),
)

#: Ids the coordinator's delegation decision is validated against. Derived from
#: the roster rather than restated, so the two can never disagree.
ROSTER_IDS: Final[frozenset[str]] = frozenset(
    entry.id for entry in SPECIALIST_ROSTER_CONFIG
)

#: How many specialists a single run dispatches. Fixed at two: the pattern's
#: point is a visible fan-out and fan-in, and two columns is the smallest number
#: that shows both while keeping the run inside its three-call budget.
SPECIALISTS_PER_RUN: Final[int] = 2


def public_roster() -> list[Specialist]:
    """Return the roster as the frontend receives it.

    Returns:
        One `Specialist` per entry, in roster order.
    """
    return [entry.public() for entry in SPECIALIST_ROSTER_CONFIG]


def find(specialist_id: str) -> RosterEntry | None:
    """Look up a roster entry by id.

    Args:
        specialist_id: The id to find.

    Returns:
        The entry, or None if the id is not on the roster. None rather than a
        raise because the caller checking a model's delegation decision needs to
        *report* an off-roster name, not crash on it.
    """
    for entry in SPECIALIST_ROSTER_CONFIG:
        if entry.id == specialist_id:
            return entry
    return None
