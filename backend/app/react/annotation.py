# Built with Spec4 AI - https://spec4.ai
"""Labelling where observation actually did the work — and checking the label.

## The cross-checks are code, and that is the whole feature

The capability's highest-rated failure is **over-crediting**: the model labels a
hop `observation` because a search happened *somewhere* in the trace, not
because any snippet carried the fact. That would make the app's central honesty
claim false in precisely the way this panel exists to prevent — and an
implementation that put the anti-over-crediting rule only in the prompt would
look finished while quietly mislabelling.

So `apply_cross_checks` re-derives, from the trace itself, everything the model
asserted about provenance:

* an annotation whose `cycle_index` is not in the trace is **dropped**, never
  rendered — a badge on the wrong hop is worse than no badge;
* a grounding claim is **downgraded to `model_knowledge`** whenever its cited
  cycle does not exist, did not search, returned no snippets, comes *after* the
  hop it supposedly supports, or was not cited at all.

The model's label is a proposal. What the trace can support is the verdict.

## The all-hops-observed flag is derived, never emitted

`HopAnnotations` has no field for it. Presets 1-3 carry a product criterion that
rests on it — "at least one run in which every hop's fact demonstrably comes
from an observation" — and a flag a model asserts about its own grounding is
exactly as trustworthy as the over-crediting above. It is computed here from the
annotations that survived.

## Annotation is decorative and must stay that way

Every failure resolves to `None`: no annotations, and a trace that renders
exactly as it did before this phase existed. No error, no apology, no banner.
`annotate` never raises, and it is called after the terminal card has already
been streamed — so the visitor has their result before this runs at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import structlog

from backend.app.core import observability
from backend.app.react import schemas
from backend.app.services import agent_runtime
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent / "prompts"

#: The annotation prompt in force.
ANNOTATION_PROMPT_VERSION: Final[str] = "hop_annotation_v1"

#: Attempts at a valid payload: one ask, then one repair. A second failure
#: skips annotation entirely, which costs a decorative panel and nothing else.
ANNOTATION_ATTEMPTS: Final[int] = 2

#: What `react_runs.annotation_outcome` records.
OUTCOME_ANNOTATED: Final[str] = "annotated"
OUTCOME_SKIPPED: Final[str] = "skipped"
OUTCOME_UNAVAILABLE: Final[str] = "unavailable"


def outcome_of(result: schemas.AnnotationResult | None) -> str:
    """Classify an annotation result the one way the whole app classifies it.

    The persisted `react_runs.annotation_outcome` and the per-run telemetry
    summary must agree about what happened, and they will not stay agreed if
    each derives it from the result independently. Three states, because
    "nothing to say" and "the call could not be made" are different operator
    facts: a run whose trace had no searches legitimately annotates nothing,
    while an unavailable chain is a degradation worth watching.

    Args:
        result: What `annotate` returned.

    Returns:
        One of `OUTCOME_ANNOTATED`, `OUTCOME_SKIPPED` or `OUTCOME_UNAVAILABLE`.
    """
    if result is None:
        return OUTCOME_UNAVAILABLE
    return OUTCOME_ANNOTATED if result.hops else OUTCOME_SKIPPED


def render_trace(cycles: list[dict[str, Any]]) -> str:
    """Render the completed trace for the annotation prompt.

    Cycles are **numbered explicitly**, because the specification's index-drift
    mitigation turns on the model using the trace's own numbers rather than
    counting entries itself. Snippets are already truncated by the observation
    builder; the prompt says so, so absence is not read as evidence.

    Args:
        cycles: The persisted cycle trace.

    Returns:
        The trace section of the prompt, snippets inside untrusted delimiters.
    """
    blocks: list[str] = []
    for entry in cycles:
        number = entry.get("cycle")
        action = entry.get("action") or {}
        observation = entry.get("observation")

        lines = [f"CYCLE {number}", f"  thought: {entry.get('thought', '')}"]
        if action.get("kind") == "search":
            lines.append(f"  action: search — query issued: {action.get('query')!r}")
        else:
            lines.append("  action: decided it could answer; no search issued")

        if observation is None:
            lines.append("  observation: none (this cycle issued no search)")
        elif observation.get("status") == "unavailable":
            lines.append("  observation: the search could not be run")
        elif observation.get("is_empty"):
            lines.append("  observation: the search returned no results")
        else:
            body = "\n".join(
                f"  [{result['idx']}] {result['title']}\n      {result['snippet']}"
                for result in observation.get("results", [])
            )
            lines.append(
                "  observation snippets (truncated):\n"
                + untrusted_block(f"cycle {number} snippets", body)
            )
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _searched(entry: dict[str, Any]) -> bool:
    """Whether a cycle actually issued a search."""
    return (entry.get("action") or {}).get("kind") == "search"


def _returned_snippets(entry: dict[str, Any]) -> bool:
    """Whether a cycle's observation actually carried anything."""
    observation = entry.get("observation")
    if not isinstance(observation, dict):
        return False
    return bool(observation.get("results"))


def apply_cross_checks(
    annotations: schemas.HopAnnotations,
    cycles: list[dict[str, Any]],
    *,
    ending: str,
) -> schemas.AnnotationResult:
    """Re-derive from the trace everything the model claimed about provenance.

    Pure, and deliberately so: this is the honesty mechanism, and it must be
    testable without a model, a database or a network.

    Args:
        annotations: What the model returned.
        cycles: The run's persisted cycle trace.
        ending: `final_answer` or `budget_exhausted`. A budget-exhausted run may
            not carry an annotation claiming the chain was resolved.

    Returns:
        The surviving annotations, the derived flag, and what was dropped or
        downgraded.
    """
    by_index = {entry.get("cycle"): entry for entry in cycles}
    exhausted = ending == schemas.ENDING_BUDGET_EXHAUSTED

    kept: list[schemas.HopAnnotation] = []
    dropped: list[str] = []
    downgraded: list[int] = []

    for hop in annotations.hops:
        # 1. Index drift. A badge on a hop the run never ran is worse than no
        #    badge at all, so this is a drop rather than a repair.
        if hop.cycle_index not in by_index:
            dropped.append(f"cycle {hop.cycle_index} is not in the trace")
            continue

        # 2. A budget-exhausted run has no answer, and its annotations must not
        #    say otherwise -- in the very panel that exists to be honest about
        #    where facts came from.
        if exhausted and schemas.implies_resolution(hop.note):
            dropped.append(
                f"cycle {hop.cycle_index} claimed resolution on an unfinished run"
            )
            continue

        note = hop.note[: schemas.MAX_HOP_NOTE_CHARS]
        source = hop.source
        supporting = hop.supporting_cycle

        if source in ("observation", "mixed"):
            supporting_entry = by_index.get(supporting) if supporting else None
            unsupported = (
                supporting is None
                or supporting_entry is None
                or supporting > hop.cycle_index
                or not _searched(supporting_entry)
                or not _returned_snippets(supporting_entry)
            )
            if unsupported:
                # The claim is refused, not the annotation. The hop still gets a
                # badge -- an honest one.
                source = "model_knowledge"
                supporting = None
                downgraded.append(hop.cycle_index)

        kept.append(
            schemas.HopAnnotation(
                cycle_index=hop.cycle_index,
                fact=hop.fact,
                source=source,
                supporting_cycle=supporting,
                note=note,
            )
        )

    observed = [hop for hop in kept if hop.source in ("observation", "mixed")]
    recalled = [hop for hop in kept if hop.source == "model_knowledge"]

    # **Coverage, not just agreement.** A model that annotates one of three
    # cycles and grounds it well has not shown that *every* hop was observed --
    # it has shown one was, and said nothing about the rest. Measured live: a
    # p1 run annotated only cycle 1 and the flag read true, which is precisely
    # the over-claim this feature exists to prevent, arriving through the gap
    # between "all annotations are grounded" and "all hops are annotated".
    searched_cycles = {entry.get("cycle") for entry in cycles if _searched(entry)}
    annotated_cycles = {hop.cycle_index for hop in kept}
    covered = bool(searched_cycles) and searched_cycles <= annotated_cycles

    return schemas.AnnotationResult(
        hops=kept,
        # **Derived, never emitted.** True only when every cycle that searched
        # has an annotation *and* every surviving annotation kept its grounding
        # claim through the checks above.
        all_hops_observed=bool(kept) and len(observed) == len(kept) and covered,
        observed_count=len(observed),
        recalled_count=len(recalled),
        dropped=dropped,
        downgraded=downgraded,
    )


async def annotate(
    *,
    run_id: str,
    question: str,
    cycles: list[dict[str, Any]],
    ending: str,
    affordable: bool = True,
) -> schemas.AnnotationResult | None:
    """Label each hop, or return nothing at all.

    **Never raises, and never blocks the trace.** Called after the terminal card
    has been streamed, so the visitor already has their result; every failure
    path -- an unaffordable call, a dead chain, a twice-invalid payload -- ends
    in `None`, which the frontend renders as an unlabelled trace with no error
    and no apology.

    Args:
        run_id: For telemetry. No prompt or trace content is reported.
        question: The question the run answered.
        cycles: The persisted cycle trace.
        ending: How the run ended.
        affordable: Whether the run's reservation still covers this call. False
            skips it -- annotation is decorative and must never be the reason a
            run's budget is overspent.

    Returns:
        The cross-checked annotations, or None.
    """
    if not affordable or not cycles:
        logger.info("react_annotation_skipped", run_id=run_id, reason="not_affordable")
        return None

    try:
        return await _annotate(
            run_id=run_id, question=question, cycles=cycles, ending=ending
        )
    except Exception:  # noqa: BLE001 - decorative; nothing here may fail a run
        # **Everything, not just the lane.** A missing prompt file, a trace
        # shape `render_trace` cannot walk, an unexpected framework error --
        # each would otherwise propagate into a run that has already streamed
        # its terminal card and been persisted, turning a completed run into a
        # 500. Verified by pointing the prompt version at a file that does not
        # exist: before this, `FileNotFoundError` reached the stream.
        logger.exception("react_annotation_failed", run_id=run_id)
        observability.report_abort("react_annotation_failed", run_id=run_id)
        return None


async def _annotate(
    *,
    run_id: str,
    question: str,
    cycles: list[dict[str, Any]],
    ending: str,
) -> schemas.AnnotationResult | None:
    """Make the annotation call. Wrapped by `annotate`, which swallows failures.

    Args:
        run_id: For telemetry.
        question: The question the run answered.
        cycles: The persisted cycle trace.
        ending: How the run ended.

    Returns:
        The cross-checked annotations, or None after the retry also failed.
    """
    instructions = load_prompt(PROMPTS_DIR, ANNOTATION_PROMPT_VERSION)
    base = (
        f"{untrusted_block('question', question)}\n\n"
        f"The run ended as: {ending}.\n\n{render_trace(cycles)}"
    )
    validation_error: str | None = None

    for attempt in range(1, ANNOTATION_ATTEMPTS + 1):
        prompt = base
        if validation_error:
            prompt += (
                "\n\nYour previous response was rejected. The system reported: "
                f"{validation_error}. Return one entry per numbered cycle."
            )
        try:
            with observability.span(
                "react.annotation", "react hop annotation", cycles=len(cycles)
            ):
                result = await agent_runtime.run_typed_step(
                    label="react-hop-annotation",
                    instructions=instructions,
                    user_prompt=prompt,
                    output_type=schemas.HopAnnotations,
                    request_limit=1,
                )
        except agent_runtime.AgentLaneError as exc:
            validation_error = str(exc)
            logger.warning(
                "react_annotation_rejected",
                run_id=run_id,
                attempt=attempt,
                error_type=type(exc).__name__,
            )
            if attempt == ANNOTATION_ATTEMPTS:
                # Reported explicitly: the auto-integrations see nothing here,
                # because a failed annotation is caught and turned into an
                # absence rather than raised through the request.
                observability.report_abort(
                    "react_annotation_failed", run_id=run_id, attempts=attempt
                )
                return None
            continue

        checked = apply_cross_checks(result.output, cycles, ending=ending)
        logger.info(
            "react_annotation_completed",
            run_id=run_id,
            hops=len(checked.hops),
            observed=checked.observed_count,
            recalled=checked.recalled_count,
            dropped=len(checked.dropped),
            downgraded=len(checked.downgraded),
            all_hops_observed=checked.all_hops_observed,
            # The retry rate the stack spec asks for is this field aggregated
            # over runs: `attempts > 1` is a repair, and the paired
            # `react_annotation_rejected` says what was wrong with the first ask.
            attempts=attempt,
        )
        return checked

    return None
