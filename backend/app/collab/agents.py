# Built with Spec4 AI - https://spec4.ai
"""The three peer agents: two sellers and a buyer. Knowledge-only, no tools.

Each function here is one turn: build the prompt from what the agent is
entitled to see, run one typed step, and return the validated object. Nothing
in this module decides what happens next -- that is the sequencer's job, and
keeping the two apart is what stops the sequencer becoming a coordinator that
reasons about the negotiation.

## A seller's prompt is built from `assemble_context` and nothing else

Every seller turn takes a `TurnContext` from `opacity.assemble_context`, which
is handed only that seller's own sealed position, the public RFQ, and the
messages addressed to it. The rival's bid, constraints and identity are never
passed to these functions, so a prompt built here **cannot** contain them --
which holds even when a model reasons its way toward asking, because asking is
not a channel.

There is deliberately no debug or convenience parameter that would widen it.

## `seller_id` is stamped by the server, never trusted from the model

`Bid.seller_id` is overwritten with the agent that was actually asked. A model
asserting which supplier it is would be a claim with nothing behind it -- the
same defect class as the pre-audit "grounded" label in the RAG app and the
`role` field in chained calls. The schema carries the field because the wire
needs it, not because the model is the authority on it.

## No tools, and no way to add one

`run_agent_step` has no `tools` parameter. That is arithmetic as much as
privacy: a tool-using step takes an unpredictable number of provider requests
and this run allows exactly one per step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from backend.app.collab.opacity import TurnContext
from backend.app.collab.rfq import QuotationRequest
from backend.app.collab.runtime import RunBudget, run_agent_step
from backend.app.collab.scenarios import (
    AxisId,
    PriorityWeighting,
    PrivateConstraint,
)
from backend.app.collab.schemas import (
    Award,
    Bid,
    CounterOffer,
    CounterOfferSet,
    NegotiationStage,
)
from backend.app.services.agent_runtime import StepResult
from backend.app.services.prompt_loader import load_prompt

PROMPTS_DIR: Final[Path] = Path(__file__).parent / "prompts"

SELLER_BID_PROMPT_VERSION: Final[str] = "seller_bid_v1"
SELLER_FINAL_PROMPT_VERSION: Final[str] = "seller_final_v1"
BUYER_COUNTER_PROMPT_VERSION: Final[str] = "buyer_counter_v1"
BUYER_AWARD_PROMPT_VERSION: Final[str] = "buyer_award_v1"

#: Wired now so the prompt set is versioned as one unit; not called until the
#: reveal and sensitivity panels land in v6 Phase 5.
REVEAL_PROMPT_VERSION: Final[str] = "reveal_explanation_v1"
SENSITIVITY_PROMPT_VERSION: Final[str] = "sensitivity_v1"


def _own_position_block(constraints: PrivateConstraint) -> str:
    """Render a seller's own sealed position for its own prompt.

    Only ever called with the constraints `opacity.constraints_for` returned
    for this same agent, so there is no path here that could render a rival's.

    Args:
        constraints: This seller's own sealed position.

    Returns:
        The block to place in its system prompt.
    """
    return (
        "## Your sealed position (yours alone; never disclosed)\n"
        f"- Cost floor: {constraints.cost_floor}\n"
        f"- Capacity ceiling: {constraints.capacity_ceiling}\n"
        f"- Fastest delivery you can commit: "
        f"{constraints.delivery_capability_days} days\n"
        f"- Longest warranty you will carry: "
        f"{constraints.warranty_liability_limit_months} months\n"
    )


def _bid_block(bid: Bid, *, label: str) -> str:
    """Render a bid as the buyer sees it.

    Args:
        bid: The bid to render.
        label: How to head the block.

    Returns:
        The rendered block.
    """
    return (
        f"### {label}\n"
        f"- Unit price: {bid.unit_price}\n"
        f"- Quantity: {bid.quantity}\n"
        f"- Delivery: {bid.delivery_days} days\n"
        f"- Warranty: {bid.warranty_months} months\n"
        f"- Notes: {bid.notes}\n"
        + (
            f"- Conceded: {', '.join(bid.concessions_made)}\n"
            if bid.concessions_made
            else ""
        )
    )


async def seller_opening_bid(
    context: TurnContext, *, budget: RunBudget, nudge: str = ""
) -> StepResult[Bid]:
    """Run one seller's opening bid. One model call.

    Args:
        context: This seller's turn context, from `assemble_context`. Carries
            its own constraints and nothing of the rival's.
        budget: The run's counters.
        nudge: An optional constraint-salience line appended when the
            differentiation check re-issues this call. Empty on the first
            attempt.

    Returns:
        The validated bid, with `seller_id` stamped server-side.

    Raises:
        RunBudgetExceededError: If the run has no requests left.
        AgentLaneError: If every model in the chain failed.
    """
    constraints = context.own_constraints
    assert isinstance(constraints, PrivateConstraint)  # noqa: S101 - buyer never bids

    instructions = (
        f"{load_prompt(PROMPTS_DIR, SELLER_BID_PROMPT_VERSION)}\n\n"
        f"{_own_position_block(constraints)}"
    )
    prompt = f"{context.rfq_text}\n\n{nudge}".strip()

    result = await run_agent_step(
        label=f"collab_opening_bid:{context.agent_id}",
        instructions=instructions,
        user_prompt=prompt,
        output_type=Bid,
        budget=budget,
    )
    return _stamp(
        result, seller_id=context.agent_id, stage=NegotiationStage.OPENING_BIDS
    )


async def seller_final_bid(
    context: TurnContext, *, counter: CounterOffer, budget: RunBudget
) -> StepResult[Bid]:
    """Run one seller's best-and-final bid. One model call.

    Args:
        context: This seller's turn context.
        counter: The counter-offer addressed to *this* seller. The buyer's
            other counter is never passed here.
        budget: The run's counters.

    Returns:
        The validated final bid, with `seller_id` stamped server-side.

    Raises:
        RunBudgetExceededError: If the run has no requests left.
        AgentLaneError: If every model in the chain failed.
    """
    constraints = context.own_constraints
    assert isinstance(constraints, PrivateConstraint)  # noqa: S101 - buyer never bids

    instructions = (
        f"{load_prompt(PROMPTS_DIR, SELLER_FINAL_PROMPT_VERSION)}\n\n"
        f"{_own_position_block(constraints)}"
    )
    prompt = (
        f"{context.rfq_text}\n\n"
        "## The buyer's counter-offer to you\n"
        f"- Term pressed: {counter.targeted_term}\n"
        f"- Ask: {counter.ask}\n"
        f"- Reasoning given: {counter.justification}\n"
    )

    result = await run_agent_step(
        label=f"collab_final_bid:{context.agent_id}",
        instructions=instructions,
        user_prompt=prompt,
        output_type=Bid,
        budget=budget,
    )
    return _stamp(result, seller_id=context.agent_id, stage=NegotiationStage.FINAL_BIDS)


async def buyer_counter_offers(
    *,
    request: QuotationRequest,
    weighting: PriorityWeighting,
    bids: list[Bid],
    budget: RunBudget,
) -> StepResult[CounterOfferSet]:
    """Run the buyer's counter-offer turn. **One model call for both counters.**

    One call rather than two: the buyer is making a single comparison across
    both bids and dividing its pressure between them. Splitting it would double
    the cost and lose the comparison that makes the targeting sensible.

    This is the one turn that legitimately sees both bids -- the buyer is the
    counterparty to both, which is exactly why the leak lint runs on what it
    produces before either counter is delivered.

    Args:
        request: The public RFQ.
        weighting: The visitor's stated priorities.
        bids: The opening bids received. One entry when a seller failed.
        budget: The run's counters.

    Returns:
        The validated counter-offers, unrepaired.

    Raises:
        RunBudgetExceededError: If the run has no requests left.
        AgentLaneError: If every model in the chain failed.
    """
    weights = ", ".join(
        f"{axis.value} {weighting.weights[axis]}/100" for axis in AxisId
    )
    prompt = (
        f"{request.text}\n\n"
        f"## The buyer's priority weighting\n{weighting.label}: {weights}\n\n"
        "## Opening bids received\n"
        + "\n".join(_bid_block(bid, label=bid.seller_id) for bid in bids)
        + "\nWrite one counter-offer per supplier listed above."
    )

    return await run_agent_step(
        label="collab_counter_offers",
        instructions=load_prompt(PROMPTS_DIR, BUYER_COUNTER_PROMPT_VERSION),
        user_prompt=prompt,
        output_type=CounterOfferSet,
        budget=budget,
    )


async def buyer_award(
    *,
    request: QuotationRequest,
    weighting: PriorityWeighting,
    final_bids: list[Bid],
    budget: RunBudget,
    inconsistency: str = "",
) -> StepResult[Award]:
    """Run the buyer's award turn. One model call.

    Args:
        request: The public RFQ.
        weighting: The visitor's stated priorities.
        final_bids: The best-and-final bids received.
        budget: The run's counters.
        inconsistency: Named when the reconciliation check is asking for one
            regeneration. Empty on the first attempt.

    Returns:
        The validated award.

    Raises:
        RunBudgetExceededError: If the run has no requests left.
        AgentLaneError: If every model in the chain failed.
    """
    weights = ", ".join(
        f"{axis.value} {weighting.weights[axis]}/100" for axis in AxisId
    )
    prompt = (
        f"{request.text}\n\n"
        f"## The buyer's priority weighting\n{weighting.label}: {weights}\n\n"
        "## Best-and-final bids\n"
        + "\n".join(_bid_block(bid, label=bid.seller_id) for bid in final_bids)
    )
    if inconsistency:
        prompt += (
            "\n## Your previous answer did not reconcile\n"
            f"{inconsistency}\n"
            "Score again, then declare the winner your own scores support.\n"
        )

    return await run_agent_step(
        label="collab_award",
        instructions=load_prompt(PROMPTS_DIR, BUYER_AWARD_PROMPT_VERSION),
        user_prompt=prompt,
        output_type=Award,
        budget=budget,
    )


def _stamp(
    result: StepResult[Bid], *, seller_id: str, stage: NegotiationStage
) -> StepResult[Bid]:
    """Overwrite a bid's identity fields with what the server knows.

    The model is not the authority on which supplier it is or which round this
    was. Both are facts the sequencer already holds, so taking them from the
    response would be recording a claim rather than a fact.

    Args:
        result: The step result to stamp.
        seller_id: The agent that was actually asked.
        stage: The round this bid belongs to.

    Returns:
        The same result, carrying a stamped copy of the bid.
    """
    stamped = result.output.model_copy(
        update={"seller_id": seller_id, "stage": stage.value}
    )
    return StepResult(output=stamped, model=result.model, requests=result.requests)
