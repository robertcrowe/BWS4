# Built with Spec4 AI - https://spec4.ai
"""The two post-award calls: unseal the positions, project the counterfactual.

Calls seven and eight of the eight reserved before the RFQ was composed. **No
new reservation and no per-call allowance check** — the budget was held up
front precisely so these cannot be refused mid-run, which is the whole reason
the hold covers eight rather than six.

## Template first, model second

Every function here renders the deterministic template *before* it calls
anything, and returns the template when the model's answer does not survive
checking. These panels arrive after the visitor has waited through six stages,
so a blank or spinning panel is the worst available outcome; the model call is
an enhancement over something that already works.

A panel is therefore always one of three things, and says which:

- model-written and validated,
- model-written, repaired once, and validated,
- template-rendered, badged `fallback_generated`.

## The gate

`explain_run` refuses to do anything without an award. The reveal payload *is*
the sealed material, so emitting it before the round completes would break the
example's central claim — and a client-side gate would be no gate at all. The
check is on the record, server-side, and a test drives it directly.

## Party-authored text is data, never instruction

Bid notes and counter-offer justifications were written by a model acting for a
party with its own interests. They go into these prompts inside
`services/untrusted.py`'s delimiters, with the system prompt told never to obey
anything inside them — the same boundary this project already uses for web
search results and visitor questions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import structlog
from pydantic_ai.settings import ModelSettings

from backend.app.collab import opacity
from backend.app.collab.counterfactual import Counterfactual, cited_values
from backend.app.collab.explain_schemas import (
    BUYER_CONSTRAINT_IDS,
    SELLER_CONSTRAINT_IDS,
    RevealExplanation,
    build_sensitivity_model,
)
from backend.app.collab.explain_templates import render_reveal, render_sensitivity
from backend.app.collab.explain_validator import (
    AxisFact,
    Findings,
    check_reveal,
    check_sensitivity,
    computed_stance,
    constraint_is_binding,
)
from backend.app.collab.runtime import RunBudget, run_agent_step
from backend.app.collab.scenarios import (
    AxisId,
    PriorityWeighting,
    PrivateConstraint,
    Scenario,
)
from backend.app.collab.schemas import Award, Bid
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR: Final[Path] = Path(__file__).parent / "prompts"
REVEAL_PROMPT_VERSION: Final[str] = "reveal_explanation_v1"
SENSITIVITY_PROMPT_VERSION: Final[str] = "sensitivity_v1"

#: The repair attempt runs at zero temperature: it is being told exactly what
#: was wrong, so there is nothing to gain from sampling variety.
REPAIR_SETTINGS: Final[ModelSettings] = ModelSettings(temperature=0.0)


class AwardNotRecordedError(Exception):
    """Raised when an explanation is requested before the award exists.

    The reveal contains both sellers' sealed constraints. Producing it early
    would be the single worst failure this example could have, so it is an
    exception rather than an empty result — a caller cannot accidentally
    proceed past it.
    """


@dataclass
class ExplanationResult:
    """One explanation panel and how it came to be.

    Attributes:
        payload: The panel's content, serialisable for JSONB and the wire.
        fallback: True when the deterministic template produced it.
        violations: What the checks flagged, for telemetry. Non-empty with
            `fallback=False` means a repair succeeded.
        requests: Provider requests this panel actually cost.
    """

    payload: dict[str, Any]
    fallback: bool
    violations: list[str]
    requests: int


def _party_facts(
    scenario: Scenario,
    constraints: PrivateConstraint,
    opening: Bid,
    final: Bid,
) -> dict[AxisId, AxisFact]:
    """Recompute the truth about one seller, axis by axis.

    The facts every check is measured against and every template sentence is
    built from. Derived from the recorded bids and the party's own sealed
    limits — nothing here asks a model anything.

    Args:
        scenario: The scenario being negotiated.
        constraints: This seller's own sealed position.
        opening: Its opening bid.
        final: Its best-and-final bid.

    Returns:
        One `AxisFact` per axis.
    """
    limits: dict[AxisId, tuple[str, float]] = {
        AxisId.PRICE: ("cost_floor", constraints.cost_floor),
        AxisId.QUANTITY: ("capacity_ceiling", float(constraints.capacity_ceiling)),
        AxisId.DELIVERY: (
            "delivery_capability",
            float(constraints.delivery_capability_days),
        ),
        AxisId.WARRANTY: (
            "warranty_liability_limit",
            float(constraints.warranty_liability_limit_months),
        ),
    }
    values: dict[AxisId, tuple[float, float]] = {
        AxisId.PRICE: (opening.unit_price, final.unit_price),
        AxisId.QUANTITY: (opening.quantity, final.quantity),
        AxisId.DELIVERY: (opening.delivery_days, final.delivery_days),
        AxisId.WARRANTY: (opening.warranty_months, final.warranty_months),
    }

    facts: dict[AxisId, AxisFact] = {}
    for axis, (open_value, final_value) in values.items():
        constraint_id, limit = limits[axis]
        facts[axis] = AxisFact(
            axis=axis,
            opening=open_value,
            final=final_value,
            stance=computed_stance(scenario, axis, open_value, final_value),
            binding=(
                constraint_id
                if constraint_is_binding(scenario, axis, final_value, limit)
                else None
            ),
        )
    return facts


def _allowed_numbers(
    facts_by_party: dict[str, dict[AxisId, AxisFact]],
) -> frozenset[str]:
    """Build the whitelist of figures the reveal narration may use.

    Args:
        facts_by_party: The recomputed truth for every party.

    Returns:
        Every value the model was shown, in the renderings it might use.
    """
    allowed: set[str] = set()
    for facts in facts_by_party.values():
        for fact in facts.values():
            for value in (fact.opening, fact.final):
                allowed.update({f"{value:g}", f"{value:.1f}", f"{value:.2f}"})
                if float(value).is_integer():
                    allowed.add(str(int(value)))
    return frozenset(allowed)


def _reveal_prompt(
    scenario: Scenario,
    weighting: PriorityWeighting,
    award: Award,
    facts_by_party: dict[str, dict[AxisId, AxisFact]],
    notes: dict[str, str],
) -> str:
    """Build the reveal's user prompt from the completed run.

    Party-authored prose goes inside untrusted delimiters: it was written by a
    model acting for a party with its own interests, so it is data to summarise
    and never instruction to follow.

    Args:
        scenario: The scenario negotiated.
        weighting: The visitor's stated priorities.
        award: The award that was made.
        facts_by_party: The recomputed truth for every party.
        notes: Each party's own bid notes, keyed by party id.

    Returns:
        The prompt.
    """
    lines = [
        f"Scenario: {scenario.goods}",
        f"Priority weighting applied: {weighting.label}",
        f"Award went to: {award.winner_id}",
        "",
        "## The recorded facts. Echo these values exactly; do not compute new ones.",
    ]
    for party_id, facts in facts_by_party.items():
        lines.append(f"\n### {party_id}")
        for axis in AxisId:
            fact = facts.get(axis)
            if fact is None:
                continue
            lines.append(
                f"- {axis.value}: opened at {fact.opening}, finished at {fact.final} "
                f"({fact.stance.value}); "
                + (
                    f"its own {fact.binding} is what it is sitting against"
                    if fact.binding
                    else "no sealed limit of its own is binding here"
                )
            )
        if notes.get(party_id):
            lines.append(untrusted_block(f"{party_id}'s own notes", notes[party_id]))

    lines.append(
        "\nWrite one block per party above, one entry per axis, using only the "
        "constraint ids listed for that party and null where none is binding."
    )
    return "\n".join(lines)


async def explain_reveal(
    *,
    scenario: Scenario,
    weighting: PriorityWeighting,
    award: Award,
    facts_by_party: dict[str, dict[AxisId, AxisFact]],
    notes: dict[str, str],
    budget: RunBudget,
    run_id: str,
) -> ExplanationResult:
    """Produce the private-position reveal. Template first, model as enhancement.

    Args:
        scenario: The scenario negotiated.
        weighting: The visitor's stated priorities.
        award: The award that was made.
        facts_by_party: The recomputed truth for every party.
        notes: Each party's own bid notes.
        budget: The run's counters.
        run_id: The run's identifier, for the log line a fallback fires.

    Returns:
        The panel, badged as model-written or template-rendered.
    """
    template = render_reveal(scenario, facts_by_party)
    instructions = load_prompt(PROMPTS_DIR, REVEAL_PROMPT_VERSION)
    prompt = _reveal_prompt(scenario, weighting, award, facts_by_party, notes)

    spent = 0
    findings = Findings()
    for attempt in (0, 1):
        try:
            step = await run_agent_step(
                label=f"collab_reveal:{run_id}",
                instructions=instructions,
                user_prompt=(
                    prompt
                    if attempt == 0
                    else f"{prompt}\n\n## Your previous answer was rejected\n"
                    f"{findings.as_prompt()}\nCorrect exactly these and reply again."
                ),
                output_type=RevealExplanation,
                budget=budget,
                model_settings=REPAIR_SETTINGS if attempt else None,
            )
        except Exception as exc:  # noqa: BLE001 - see below
            # Deliberately broad: the run's *last* two calls must never take the
            # page down. Anything from the lane -- a budget ceiling, an
            # exhausted chain, a validation error inside PydanticAI -- degrades
            # to the template rather than propagating.
            logger.warning(
                "collab_reveal_fallback",
                run_id=run_id,
                reason=type(exc).__name__,
                violation_codes=[],
            )
            return ExplanationResult(
                payload=template.model_dump(),
                fallback=True,
                violations=["call_failed"],
                requests=spent,
            )

        spent += step.requests
        findings = _check_all_parties(
            step.output, scenario=scenario, facts_by_party=facts_by_party
        )
        if findings.ok:
            return ExplanationResult(
                payload=step.output.model_dump(),
                fallback=False,
                violations=[] if attempt == 0 else ["repaired"],
                requests=spent,
            )

    logger.warning(
        "collab_reveal_fallback",
        run_id=run_id,
        reason="validation_failed",
        violation_codes=findings.violations,
    )
    return ExplanationResult(
        payload=template.model_dump(),
        fallback=True,
        violations=findings.violations,
        requests=spent,
    )


def _check_all_parties(
    output: RevealExplanation,
    *,
    scenario: Scenario,
    facts_by_party: dict[str, dict[AxisId, AxisFact]],
) -> Findings:
    """Check every party block, accumulating findings across all of them."""
    allowed = _allowed_numbers(facts_by_party)
    combined = Findings()
    seen: set[str] = set()

    for block in output.parties:
        facts = facts_by_party.get(block.party_id)
        if facts is None:
            combined.add(
                "unknown_party",
                f"{block.party_id!r} did not take part in this run.",
            )
            continue
        seen.add(block.party_id)

        is_seller = block.party_id in opacity.SELLER_IDS_SET
        rival = opacity.rival_of(block.party_id) if is_seller else None
        rival_corpus = (
            opacity.constraint_corpus(rival, scenario.id)
            if rival is not None
            else frozenset()
        )
        found = check_reveal(
            block,
            facts=facts,
            allowed_numbers=allowed,
            allowed_constraints=(
                SELLER_CONSTRAINT_IDS if is_seller else BUYER_CONSTRAINT_IDS
            ),
            rival_id=rival,
            rival_corpus=rival_corpus,
        )
        combined.violations.extend(found.violations)
        combined.detail.extend(found.detail)

    missing = sorted(set(facts_by_party) - seen)
    if missing:
        combined.add(
            "missing_party", f"No block was written for: {', '.join(missing)}."
        )
    return combined


async def explain_sensitivity(
    *,
    counterfactual: Counterfactual,
    scenario: Scenario,
    budget: RunBudget,
    run_id: str,
) -> ExplanationResult:
    """Narrate the computed counterfactual. Template first, model as enhancement.

    The flip is arithmetic done in `counterfactual.py` and handed over as a
    given fact. The model explains it; a validator checks it did not contradict
    it.

    Args:
        counterfactual: The computed projection.
        scenario: The scenario negotiated.
        budget: The run's counters.
        run_id: The run's identifier.

    Returns:
        The panel, badged as model-written or template-rendered.
    """
    template = render_sensitivity(counterfactual)
    allowed = cited_values(counterfactual)
    computed_winner = (
        "too_close"
        if counterfactual.outcome == "too_close"
        else counterfactual.alternative_winner
    )
    output_type = build_sensitivity_model(
        seller_ids=sorted(
            {score.seller_id for score in counterfactual.original_scores}
        ),
        axis_ids=[axis.id.value for axis in scenario.axes],
    )
    instructions = load_prompt(PROMPTS_DIR, SENSITIVITY_PROMPT_VERSION)
    prompt = _sensitivity_prompt(counterfactual, computed_winner)

    spent = 0
    findings = Findings()
    for attempt in (0, 1):
        try:
            step = await run_agent_step(
                label=f"collab_sensitivity:{run_id}",
                instructions=instructions,
                user_prompt=(
                    prompt
                    if attempt == 0
                    else f"{prompt}\n\n## Your previous answer was rejected\n"
                    f"{findings.as_prompt()}\nCorrect exactly these and reply again."
                ),
                output_type=output_type,
                budget=budget,
                model_settings=REPAIR_SETTINGS if attempt else None,
            )
        except Exception as exc:  # noqa: BLE001 - same reason as the reveal
            logger.warning(
                "collab_sensitivity_fallback",
                run_id=run_id,
                reason=type(exc).__name__,
                violation_codes=[],
            )
            return ExplanationResult(
                payload=template.model_dump(),
                fallback=True,
                violations=["call_failed"],
                requests=spent,
            )

        spent += step.requests
        findings = check_sensitivity(
            step.output, computed_winner=computed_winner, allowed_numbers=allowed
        )
        if findings.ok:
            return ExplanationResult(
                payload=step.output.model_dump(),
                fallback=False,
                violations=[] if attempt == 0 else ["repaired"],
                requests=spent,
            )

    logger.warning(
        "collab_sensitivity_fallback",
        run_id=run_id,
        reason="validation_failed",
        violation_codes=findings.violations,
    )
    return ExplanationResult(
        payload=template.model_dump(),
        fallback=True,
        violations=findings.violations,
        requests=spent,
    )


def _sensitivity_prompt(counterfactual: Counterfactual, computed_winner: str) -> str:
    """Build the sensitivity prompt, stating the computed result as a fact."""
    return "\n".join(
        [
            "## The re-scoring has already been computed.",
            "## Narrate it; do not re-derive it.",
            "",
            f"Weighting actually used: {counterfactual.original_weights}",
            f"Alternative tested: {counterfactual.alternative_weights}"
            f" ({counterfactual.alternative_label})",
            f"Promoted: {counterfactual.promoted_axis.value}."
            f" Demoted: {counterfactual.demoted_axis.value}.",
            "",
            f"Winner as run: {counterfactual.original_winner}",
            f"Winner under the alternative: {computed_winner}",
            f"Outcome: {counterfactual.outcome}",
            f"Terms that moved it most: "
            f"{[axis.value for axis in counterfactual.decisive_axes]}",
            "",
            "Explain why the shift does or does not happen. Use only the figures "
            "above. Write it as a projection, never as something settled.",
        ]
    )


async def explain_run(
    *,
    scenario: Scenario,
    weighting: PriorityWeighting,
    award: Award | None,
    opening_bids: list[Bid],
    final_bids: list[Bid],
    counterfactual: Counterfactual | None,
    budget: RunBudget,
    run_id: str,
) -> tuple[ExplanationResult | None, ExplanationResult | None]:
    """Run both explanations concurrently, after the award and never before.

    **The gate is here and it is server-side.** No award means no reveal: the
    payload is the sealed material, and a client-side check would be no check
    at all.

    `return_exceptions=True` for the same reason the bid rounds use it — a
    failure in one panel must not cancel the other, and these are the last two
    calls of a run the visitor has already waited through.

    Args:
        scenario: The scenario negotiated.
        weighting: The visitor's stated priorities.
        award: The award. **Required** — `None` raises.
        opening_bids: The opening bids, for the reveal's deltas.
        final_bids: The best-and-final bids.
        counterfactual: The computed projection, or None when a degraded run
            left fewer than two bids to compare.
        budget: The run's counters.
        run_id: The run's identifier.

    Returns:
        The reveal and the sensitivity panels. Either may be None when the run
        was too degraded to produce it.

    Raises:
        AwardNotRecordedError: If no award has been recorded.
    """
    if award is None:
        raise AwardNotRecordedError(
            "The reveal unseals both sellers' private positions and may not be "
            "produced before the award is recorded."
        )

    facts_by_party = _facts_for_run(scenario, opening_bids, final_bids)
    notes = {bid.seller_id: bid.notes for bid in final_bids}

    reveal_task = (
        explain_reveal(
            scenario=scenario,
            weighting=weighting,
            award=award,
            facts_by_party=facts_by_party,
            notes=notes,
            budget=budget,
            run_id=run_id,
        )
        if facts_by_party
        else None
    )
    sensitivity_task = (
        explain_sensitivity(
            counterfactual=counterfactual,
            scenario=scenario,
            budget=budget,
            run_id=run_id,
        )
        if counterfactual is not None
        else None
    )

    if reveal_task is None and sensitivity_task is None:
        return None, None

    results = await asyncio.gather(
        *(task for task in (reveal_task, sensitivity_task) if task is not None),
        return_exceptions=True,
    )

    outcomes: list[ExplanationResult | None] = []
    index = 0
    for task in (reveal_task, sensitivity_task):
        if task is None:
            outcomes.append(None)
            continue
        result = results[index]
        index += 1
        if isinstance(result, BaseException):
            logger.warning(
                "collab_explanation_failed",
                run_id=run_id,
                reason=type(result).__name__,
            )
            outcomes.append(None)
        else:
            outcomes.append(result)

    return outcomes[0], outcomes[1]


def _facts_for_run(
    scenario: Scenario, opening_bids: list[Bid], final_bids: list[Bid]
) -> dict[str, dict[AxisId, AxisFact]]:
    """Recompute every seller's facts, for the sellers that bid in both rounds."""
    openings = {bid.seller_id: bid for bid in opening_bids}
    facts: dict[str, dict[AxisId, AxisFact]] = {}
    for final in final_bids:
        opening = openings.get(final.seller_id)
        if opening is None:
            continue
        position = opacity.constraints_for(final.seller_id, scenario.id)
        if not isinstance(position, PrivateConstraint):
            continue
        facts[final.seller_id] = _party_facts(scenario, position, opening, final)
    return facts
