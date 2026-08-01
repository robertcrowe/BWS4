# Built with Spec4 AI - https://spec4.ai
"""Deterministic plan checking: the functional core of the planning agent.

**Nothing here trusts the model.** The capability's first named failure mode is
a planner that emits an unusable plan -- too many steps, a synthesis step that
is not last, a research step with no query -- and the mitigation is a check in
code, not a firmer instruction in the prompt. Structured output constrains the
plan's *shape*; only this module constrains its *rules*.

Pure functions over Pydantic models: no model calls, no I/O, no clock. That is
what lets the whole of this file be tested exhaustively, and what makes the
replan path a decision the orchestrator takes on evidence rather than a guess.

## Rejecting and trimming are different outcomes

A plan can be *wrong* or merely *too big*, and conflating them would spend a
model call fixing something no model needs to fix:

- **Wrong** -- breaks a rule the executor could not carry out. Reported as
  errors, which the orchestrator injects into exactly one replan attempt.
- **Too big** -- every rule satisfied, but more research steps than this
  deployment's budget allows. Trimmed in code and reported to the visitor with
  a note, because the excess steps are perfectly good ones we simply cannot
  afford. Re-planning here would ask the model to solve a budget problem.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.planning.schemas import KIND_RESEARCH, KIND_SYNTHESIS, Plan, PlanStep

#: The specification's own bounds on a plan the planner may emit.
MIN_STEPS = 2
MAX_STEPS = 5

#: What this deployment will actually execute. Below the specification's ceiling
#: on purpose: the project runs on a shared free-tier budget, so a run is ~1
#: planner call plus 2-3 executor calls. The pattern is not limited to this --
#: the UI says so -- but the wallet is.
MAX_RESEARCH_STEPS = 2


@dataclass(frozen=True)
class PlanCheck:
    """The verdict on one candidate plan.

    Attributes:
        plan: The plan to execute, trimmed and re-indexed, or None if the
            candidate was rejected.
        errors: Why it was rejected, phrased for injection into a replan
            prompt. Empty when the plan is usable.
        trimmed_note: Visitor-facing explanation of what was dropped and why,
            or None if nothing was.
    """

    plan: Plan | None
    errors: list[str]
    trimmed_note: str | None = None

    @property
    def ok(self) -> bool:
        """True when there is a plan to execute."""
        return self.plan is not None


def validate_plan(plan: Plan) -> list[str]:
    """Check a candidate plan against the rules the executor requires.

    Google-style docstring per project convention.

    Args:
        plan: The planner's output, already parsed into the schema.

    Returns:
        Human-readable errors, empty when the plan is valid. Each is phrased as
        an instruction the planner can act on, because that is exactly where
        they are sent -- a message like "expected 2-5 steps" is useless to a
        model being asked to try again.
    """
    errors: list[str] = []
    steps = plan.steps

    if not plan.goal.strip():
        errors.append("The `goal` field was empty. Restate the visitor's goal in your own words.")

    if len(steps) < MIN_STEPS or len(steps) > MAX_STEPS:
        errors.append(
            f"The plan had {len(steps)} steps. A plan must have between {MIN_STEPS} and "
            f"{MAX_STEPS} steps in total."
        )

    synthesis_positions = [i for i, step in enumerate(steps) if step.kind == KIND_SYNTHESIS]

    if not synthesis_positions:
        errors.append(
            "The plan had no `synthesis` step. Every plan must end with exactly one "
            "synthesis step, which composes the itinerary."
        )
    elif len(synthesis_positions) > 1:
        errors.append(
            f"The plan had {len(synthesis_positions)} `synthesis` steps. There must be "
            "exactly one, and it must be the last step."
        )
    elif synthesis_positions[0] != len(steps) - 1:
        errors.append(
            f"The `synthesis` step was at position {synthesis_positions[0] + 1} of "
            f"{len(steps)}. It must be the last step, because it composes the itinerary "
            "from the research steps before it."
        )

    for step in steps:
        if step.kind == KIND_RESEARCH and not (step.search_query or "").strip():
            errors.append(
                f"Research step {step.index} ({step.description!r}) had no `search_query`. "
                "Every research step must carry the literal text to send to a web search."
            )
        if step.kind == KIND_SYNTHESIS and (step.search_query or "").strip():
            errors.append(
                f"The synthesis step carried a `search_query` ({step.search_query!r}). "
                "The synthesis step runs no search; its `search_query` must be null."
            )
        if not step.description.strip():
            errors.append(
                f"Step {step.index} had an empty `description`. Each step's description is "
                "shown to the visitor before the plan runs."
            )

    return errors


def trim_plan(plan: Plan) -> tuple[Plan, str | None]:
    """Cut a valid plan down to what this deployment's budget can execute.

    Keeps the first `MAX_RESEARCH_STEPS` research steps and the synthesis step,
    then re-indexes so the surviving steps are numbered 1..n contiguously.
    Re-indexing matters beyond neatness: `StepResult.step_index` and
    `ItineraryBlock.source_refs` both point at these numbers, so a gap would
    leave the itinerary citing a step the visitor never saw run.

    Keeping the *first* N is deliberate rather than arbitrary -- the planner is
    instructed to order steps as they will run, so the earlier ones are the ones
    it considered foundational.

    Args:
        plan: A plan that has already passed `validate_plan`.

    Returns:
        The plan to execute, and a visitor-facing note naming what was dropped,
        or None when nothing was.
    """
    research = [step for step in plan.steps if step.kind == KIND_RESEARCH]
    synthesis = [step for step in plan.steps if step.kind == KIND_SYNTHESIS]

    if len(research) <= MAX_RESEARCH_STEPS:
        return plan, None

    dropped = len(research) - MAX_RESEARCH_STEPS
    kept = research[:MAX_RESEARCH_STEPS] + synthesis

    renumbered = [
        PlanStep(
            index=position,
            kind=step.kind,
            description=step.description,
            search_query=step.search_query,
        )
        for position, step in enumerate(kept, start=1)
    ]

    note = (
        f"The planner proposed {len(research)} research steps; this demo runs at most "
        f"{MAX_RESEARCH_STEPS}, so {dropped} were dropped before anything ran. That is a "
        "budget limit of this deployment, not of the planning-agent pattern — a real one "
        "would run every step it planned."
    )
    return Plan(goal=plan.goal, steps=renumbered), note


def check_plan(plan: Plan) -> PlanCheck:
    """Validate, then trim: the whole deterministic gate in one call.

    Args:
        plan: The planner's candidate output.

    Returns:
        A `PlanCheck` carrying either an executable plan (possibly trimmed, with
        a note) or the errors to send back to the planner.
    """
    errors = validate_plan(plan)
    if errors:
        return PlanCheck(plan=None, errors=errors)

    trimmed, note = trim_plan(plan)
    return PlanCheck(plan=trimmed, errors=[], trimmed_note=note)
