# Built with Spec4 AI - https://spec4.ai
"""The Router run: admission, then a staged stream. The order is fixed here.

## Admission (an ordinary request; nothing streams yet)

1. **Resolve the preset**, if one is named. The server routes its own copy of
   the preset's text; a client text that does not match is refused.
2. **Moderation, for free text only.** Presets skip it -- the gate byte-matches
   the app's own canonical strings. It fails closed, and it costs no model
   allowance, which is what lets it run before anything is held.
3. **Route descriptions ready.** The router cannot be told the routes without
   them, and a run must not be started that cannot be classified.
4. **Hold two units** against the shared generation cap: charged to the hourly
   gate with `reserve_capability` and promised with `allowance_holds.reserve`,
   so a run that cannot finish is never started.

Any refusal here is a `RunRefusedError` the API turns into an HTTP error: no
stream, no run, no hold, no history. Moderation runs before the hold, so a
refused request never touches a quota.

## The stream

`run_started`, `stage(classifying)`, the one classification call, `decision`,
`stage(dispatching)`, dispatch, `run_end`. A shielded settle in `finally`
releases every unit the run did not spend and redeems or refunds the hold --
including when the visitor disconnects mid-run.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from backend.app.db.session import async_session_factory
from backend.app.router import classifier, dispatch, history, rerun
from backend.app.router.constants import (
    DECISION_MARGIN,
    DETERMINISTIC_EVALUATOR,
    ROUTE_LABELS,
    RouteId,
)
from backend.app.router.cost_strip import build_cost_strip
from backend.app.router.decision import (
    LowConfidence,
    Malformed,
    Outcome,
    agreement,
    decide,
)
from backend.app.router.evaluator import Accepted, evaluate
from backend.app.router.presets import PRESET_REQUESTS, RouterPreset, get_preset
from backend.app.router.run_schemas import (
    EVENT_ANSWER,
    EVENT_DECISION,
    EVENT_RUN_END,
    EVENT_RUN_STARTED,
    EVENT_STAGE,
    AnswerEvent,
    DecisionEvent,
    LowConfidenceCard,
    PassageOut,
    RerunRequest,
    RunEnd,
    RunRequest,
    RunStarted,
    SnippetOut,
    Stage,
    UnitAccount,
)
from backend.app.router.state import ensure_route_descriptions
from backend.app.services import allowance_holds, shared, text_gate
from backend.app.services.moderation import Moderator

logger = structlog.get_logger()

#: The app name on holds, moderation and service logs.
ROUTER_APP_NAME: Final[str] = "router_example_app"
#: Model-call units held before the router runs: the router's call and the
#: dispatched route's generation call.
UNITS_PER_RUN: Final[int] = 2

CODE_SHARED_CAP: Final[str] = "shared_cap_reached"
CODE_NOT_READY: Final[str] = "descriptions_not_ready"
CODE_PRESET_MISMATCH: Final[str] = "preset_mismatch"
CODE_UNKNOWN_PRESET: Final[str] = "unknown_preset"
CODE_ALREADY_STARTED: Final[str] = "run_already_started"

SHARED_CAP_MESSAGE: Final[str] = (
    "The showcase's shared hourly allowance for model calls, used by every "
    "example app, is too close to its cap for a complete Router run. This is "
    "the gallery-wide cap, not this app's 5-run limit: no run was used, nothing "
    "was held, and it resets at the top of the hour."
)
NOT_READY_MESSAGE: Final[str] = (
    "The Router's route descriptions are not ready, so the router cannot be told "
    "its routes. No run was used. Try again shortly."
)
MALFORMED_NOTE: Final[str] = (
    "The router's decision could not be read -- it was incomplete or did not "
    "match the expected shape -- so code sent the request to the single-call "
    "route. This run does not count in the agreement history."
)


class RunRefusedError(Exception):
    """A run refused before it started. Becomes an HTTP error; no stream.

    Attributes:
        status: The HTTP status.
        code: Machine-readable cause.
        message: What to show the visitor.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StreamEvent:
    """One event on its way to the wire.

    Attributes:
        name: The SSE event name.
        payload: The envelope, dumped from its Pydantic model.
    """

    name: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdmittedRun:
    """A run that passed admission and holds its units.

    Attributes:
        run_id: The run's id; also its hold key.
        request: The text to route: the preset's canonical text, or the
            visitor's moderated free text.
        preset: The preset, or None for free text.
        visit_id: The browser visit.
    """

    run_id: uuid.UUID
    request: str
    preset: RouterPreset | None
    visit_id: str


@dataclass
class RunLedger:
    """What the run held, has spent, and has already given back.

    Attributes:
        reserved: Units held at admission.
        spent: Units spent on model calls so far.
        released: Units given back mid-run, e.g. the deterministic route's
            second unit once the evaluator accepts.
    """

    reserved: int
    spent: int = 0
    released: int = 0

    def charge(self, units: int = 1) -> None:
        """Record units spent, never beyond what is still held.

        Args:
            units: Units to charge.
        """
        self.spent = min(self.reserved - self.released, self.spent + units)

    @property
    def unspent(self) -> int:
        """Units still held and not spent."""
        return self.reserved - self.spent - self.released

    def account(self) -> UnitAccount:
        """The accounting as the run will have settled it.

        Returns:
            Reserved, used, and released (early plus at settle).
        """
        return UnitAccount(
            reserved=self.reserved,
            used=self.spent,
            released=self.released + self.unspent,
        )


def _resolve(payload: RunRequest) -> RouterPreset | None:
    """Resolve the named preset, refusing a mismatched or unknown one.

    Args:
        payload: The request body.

    Returns:
        The preset, or None for free text.

    Raises:
        RunRefusedError: 422 for an unknown preset or mismatched text.
    """
    if payload.preset_id is None:
        return None
    preset = get_preset(payload.preset_id)
    if preset is None:
        raise RunRefusedError(
            422, CODE_UNKNOWN_PRESET, "That preset is not in the curated set."
        )
    if payload.request != preset.request:
        raise RunRefusedError(
            422,
            CODE_PRESET_MISMATCH,
            "The request text does not match the named preset.",
        )
    return preset


async def admit(payload: RunRequest, moderator: Moderator) -> AdmittedRun:
    """Admit a run: moderation for free text, then the two-unit hold.

    Args:
        payload: The validated request body.
        moderator: The shared safety gate.

    Returns:
        The admitted run, holding its units.

    Raises:
        RunRefusedError: When the run must not start. Nothing is held.
    """
    preset = _resolve(payload)
    run_id = uuid.uuid4()

    if preset is None:
        async with async_session_factory() as gate_session:
            gate = await text_gate.check_free_text(
                payload.request,
                app_name=ROUTER_APP_NAME,
                curated=PRESET_REQUESTS,
                session=gate_session,
                moderator=moderator,
            )
        if not gate.allowed and gate.code is not None:
            logger.info("router_run_refused", run_id=str(run_id), reason=gate.code)
            raise RunRefusedError(
                text_gate.status_for(gate.code), gate.code, gate.message or ""
            )

    if await ensure_route_descriptions() is None:
        logger.info("router_run_refused", run_id=str(run_id), reason=CODE_NOT_READY)
        raise RunRefusedError(503, CODE_NOT_READY, NOT_READY_MESSAGE)

    async with async_session_factory() as session:
        try:
            await shared.reserve_capability(
                session,
                shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=UNITS_PER_RUN,
            )
        except shared.ServiceUnavailableError:
            logger.info("router_run_refused", run_id=str(run_id), reason="shared_cap")
            raise RunRefusedError(429, CODE_SHARED_CAP, SHARED_CAP_MESSAGE) from None
        try:
            await allowance_holds.reserve(
                session,
                hold_key=str(run_id),
                capability=shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=UNITS_PER_RUN,
            )
        except allowance_holds.HoldStateError:
            await shared.release_capability(
                session,
                shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=UNITS_PER_RUN,
            )
            raise RunRefusedError(
                409, CODE_ALREADY_STARTED, "That run has already been started."
            ) from None

    logger.info(
        "router_run_admitted",
        run_id=str(run_id),
        preset_id=preset.id if preset else None,
        visit_id=payload.visit_id,
        units=UNITS_PER_RUN,
    )
    return AdmittedRun(
        run_id=run_id,
        request=preset.request if preset else payload.request,
        preset=preset,
        visit_id=payload.visit_id,
    )


def low_confidence_caveat(outcome: LowConfidence) -> str:
    """The plain caveat the low-confidence card shows.

    Args:
        outcome: The low-confidence outcome.

    Returns:
        One or two sentences naming both routes and the cost-order rule.
    """
    cheap, dear = (ROUTE_LABELS[route] for route in outcome.torn)
    return (
        f"The router was torn between {cheap} and {dear}: their scores were "
        f"within the {DECISION_MARGIN} decision margin, so the router did not "
        f"choose. The cheaper of the two, {cheap}, was dispatched per the fixed "
        "cost order."
    )


def decision_event(
    outcome: Outcome,
    classification: classifier.Classification,
    preset: RouterPreset | None,
    plan: dispatch.DispatchPlan,
) -> DecisionEvent:
    """Build the decision card from the outcome and the dispatch plan.

    Args:
        outcome: Routed, low-confidence or malformed.
        classification: The classification call's result.
        preset: The preset, or None for free text.
        plan: Where code is sending the request, after the evaluator gate.

    Returns:
        The decision event.
    """
    expected: RouteId | None = preset.expected_route if preset else None
    common: dict[str, Any] = {
        "dispatched_route": plan.route,
        "agreement": agreement(outcome, expected, plan.route),
        "expected_route": expected,
        "expected_reason": preset.reason if preset else None,
        "evaluator_fallback_note": plan.fallback_note,
        "classifier_ms": classification.elapsed_ms,
        "model": classification.model,
    }
    if isinstance(outcome, Malformed):
        return DecisionEvent(
            kind="malformed",
            chosen_route=None,
            scores=None,
            rationale=None,
            expression=None,
            low_confidence=None,
            malformed_note=MALFORMED_NOTE,
            **common,
        )
    if isinstance(outcome, LowConfidence):
        return DecisionEvent(
            kind="low_confidence",
            chosen_route=None,
            scores=outcome.scores,
            rationale=outcome.rationale,
            expression=outcome.expression,
            low_confidence=LowConfidenceCard(
                torn=outcome.torn,
                dispatched=outcome.dispatched,
                caveat=low_confidence_caveat(outcome),
            ),
            malformed_note=None,
            **common,
        )
    return DecisionEvent(
        kind="routed",
        chosen_route=outcome.route,
        scores=outcome.scores,
        rationale=outcome.rationale,
        expression=outcome.expression,
        low_confidence=None,
        malformed_note=None,
        **common,
    )


def answer_event(
    plan: dispatch.DispatchPlan, answer: dispatch.RouteAnswer
) -> AnswerEvent:
    """Build the answer event, labelled with the path that produced it.

    Args:
        plan: The dispatch plan.
        answer: What the route produced.

    Returns:
        The answer event.
    """
    common: dict[str, Any] = {
        "route": plan.route,
        "route_label": ROUTE_LABELS[plan.route],
        "elapsed_ms": answer.elapsed_ms,
        "model_calls": answer.units_used,
        "searches": answer.searches,
        "retrievals": answer.retrievals,
    }
    if isinstance(answer, dispatch.DeterministicAnswer):
        return AnswerEvent(
            kind="deterministic",
            expression=answer.expression,
            evaluator_verdict="accepted",
            value_display=answer.display,
            **common,
        )
    sources: dict[str, Any] = {
        "query": answer.query,
        "snippets": [SnippetOut(**vars(snippet)) for snippet in answer.snippets],
        "passages": [PassageOut(**vars(passage)) for passage in answer.passages],
    }
    if isinstance(answer, dispatch.TextAnswer):
        return AnswerEvent(
            kind="text",
            text=answer.text,
            model=answer.model,
            truncated=answer.truncated,
            invalid_citations=list(answer.invalid_citations),
            removed_urls=list(answer.removed_urls),
            grounding=answer.grounding,
            **sources,
            **common,
        )
    return AnswerEvent(kind=answer.kind, error=answer.message, **sources, **common)


async def _release_now(run_id: uuid.UUID, ledger: RunLedger, units: int) -> None:
    """Give units back to the shared gate mid-run.

    The deterministic route's second unit is released the moment the evaluator
    accepts, not at the end of the run. Never raises: a failed early release
    leaves the units held, and the settle releases them instead.

    Args:
        run_id: The run.
        ledger: The run's ledger.
        units: Units to release.
    """
    units = min(units, ledger.unspent)
    if units <= 0:
        return
    try:
        async with async_session_factory() as session:
            await shared.release_capability(
                session,
                shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=units,
            )
    except Exception:  # noqa: BLE001 - the settle releases whatever this could not
        logger.exception("router_early_release_failed", run_id=str(run_id))
        return
    ledger.released += units
    logger.info("router_unit_released", run_id=str(run_id), units=units)


async def _log_generation(run_id: uuid.UUID, answer: dispatch.TextAnswer) -> None:
    """Write the shared service log row for a generation call. Never raises.

    The row carries the route and model only, never the request text.

    Args:
        run_id: The run.
        answer: The generated answer.
    """
    try:
        async with async_session_factory() as session:
            await shared.log_invocation(
                session,
                app_name=ROUTER_APP_NAME,
                capability=shared.CAPABILITY_GENERATION,
                summary=f"Router route answer via {answer.model}",
            )
    except Exception:  # noqa: BLE001 - logging must not fail a run
        logger.exception("router_service_log_failed", run_id=str(run_id))


async def _settle(hold_key: str, ledger: RunLedger) -> None:
    """Release everything unspent and close the hold. Never raises.

    Opens its own session: the common reason this runs is a closing stream,
    and committing through a session being torn down is a race the refund
    loses (`react/service.py` records the measurement).

    Args:
        hold_key: The run's allowance-hold key: its run id, or the original
            run's re-run key.
        ledger: What was held and spent.
    """
    try:
        async with async_session_factory() as session:
            if ledger.unspent:
                await shared.release_capability(
                    session,
                    shared.CAPABILITY_GENERATION,
                    app_name=ROUTER_APP_NAME,
                    units=ledger.unspent,
                )
            if ledger.spent:
                await allowance_holds.redeem(session, hold_key)
            else:
                await allowance_holds.refund(session, hold_key)
    except Exception:  # noqa: BLE001 - teardown must not raise over a failing run
        logger.exception("router_settle_failed", hold_key=hold_key)
    else:
        logger.info(
            "router_run_settled",
            hold_key=hold_key,
            reserved=ledger.reserved,
            spent=ledger.spent,
            released=ledger.released + ledger.unspent,
        )


async def _record_and_read_history(
    run: AdmittedRun,
    outcome: Outcome,
    plan: dispatch.DispatchPlan,
    answer: dispatch.RouteAnswer,
) -> tuple[history.LatencyBaseline, bool]:
    """Write the run's history rows, then read the latency baseline.

    In the run generator's own session, once the outcome is final. Neither a
    failed write nor a failed read fails the run: both are logged, and an
    unreadable baseline is reported as such on the strip.

    Args:
        run: The run.
        outcome: Its outcome.
        plan: Where it was dispatched.
        answer: What the route produced.

    Returns:
        The baseline, and whether it could not be read.
    """
    agreement_outcome = history.agreement_row(
        preset=run.preset, outcome=outcome, dispatched_route=plan.route
    )
    latency_ms = history.latency_row(
        outcome=outcome,
        dispatched_route=plan.route,
        answered=isinstance(answer, dispatch.TextAnswer),
        route_ms=answer.elapsed_ms,
    )
    empty = history.LatencyBaseline(typical_ms=None, sample_size=0)
    try:
        async with async_session_factory() as session:
            try:
                await history.write_history(
                    session,
                    preset_id=run.preset.id if run.preset else None,
                    agreement=agreement_outcome,
                    latency_ms=latency_ms,
                )
            except Exception:  # noqa: BLE001 - a history write must not fail the run
                logger.exception("router_history_write_failed", run_id=str(run.run_id))
                await session.rollback()
            return await history.read_latency_baseline(session), False
    except Exception:  # noqa: BLE001 - an unreadable baseline is reported, not raised
        logger.exception("router_baseline_read_failed", run_id=str(run.run_id))
        return empty, True


async def stream_run(run: AdmittedRun) -> AsyncGenerator[StreamEvent, None]:
    """Classify, decide, dispatch, and put each stage on the wire as it happens.

    Args:
        run: The admitted run, already holding its units.

    Yields:
        `run_started`, `stage`, `decision`, `stage`, `answer`, `run_end`.
    """
    ledger = RunLedger(reserved=UNITS_PER_RUN)
    started = time.perf_counter()

    async def charge_classification() -> None:
        ledger.charge(1)

    try:
        yield StreamEvent(
            EVENT_RUN_STARTED,
            RunStarted(
                run_id=str(run.run_id),
                request=run.request,
                preset_id=run.preset.id if run.preset else None,
                units_reserved=ledger.reserved,
            ).model_dump(),
        )
        yield StreamEvent(
            EVENT_STAGE,
            Stage(
                stage="classifying",
                message="Router classifying the request (1 model call)",
            ).model_dump(),
        )
        classification = await classifier.classify(
            run.request, on_request=charge_classification
        )
        outcome = decide(classification)
        plan = dispatch.plan(outcome)
        yield StreamEvent(
            EVENT_DECISION,
            decision_event(outcome, classification, run.preset, plan).model_dump(
                mode="json"
            ),
        )

        if isinstance(plan.evaluation, Accepted):
            # The evaluator accepted: no generation call will follow, so the
            # second unit goes back now rather than at the end of the run.
            await _release_now(run.run_id, ledger, 1)

        yield StreamEvent(
            EVENT_STAGE,
            Stage(
                stage="dispatching",
                message=f"Code dispatching to {ROUTE_LABELS[plan.route]}",
            ).model_dump(),
        )
        answer = await dispatch.run(plan, run.request, async_session_factory)
        ledger.charge(answer.units_used)
        if isinstance(answer, dispatch.TextAnswer):
            await _log_generation(run.run_id, answer)
        yield StreamEvent(EVENT_ANSWER, answer_event(plan, answer).model_dump())

        baseline, baseline_unavailable = await _record_and_read_history(
            run, outcome, plan, answer
        )
        strip = build_cost_strip(
            route=plan.route,
            model_calls=answer.units_used,
            searches=answer.searches,
            retrievals=answer.retrievals,
            route_ms=answer.elapsed_ms,
            overhead_calls=1,
            overhead_ms=classification.elapsed_ms,
            baseline=baseline,
            unit_released=isinstance(plan.evaluation, Accepted),
            baseline_unavailable=baseline_unavailable,
        )
        eligible = rerun.is_eligible(preset=run.preset, dispatched_route=plan.route)
        if eligible and run.preset is not None:
            rerun.TICKETS.issue(run.run_id, run.preset.id, plan.route)
        yield StreamEvent(
            EVENT_RUN_END,
            RunEnd(
                run_id=str(run.run_id),
                ending=(
                    "low_confidence"
                    if isinstance(outcome, LowConfidence)
                    else "routed_answer"
                ),
                dispatched_route=plan.route,
                units=ledger.account(),
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                cost_strip=strip,
                rerun_eligible=eligible,
            ).model_dump(),
        )
    finally:
        # Shielded: a cancelled task's every await raises, so an unshielded
        # settle on disconnect would never run (see `react/service._release`).
        await asyncio.shield(_settle(str(run.run_id), ledger))


# ---------------------------------------------------------------------------
# The comparison re-run
# ---------------------------------------------------------------------------

#: Units a re-run holds: the expected route's own dispatch cost, never the
#: router's. One for every route; the search route also takes one search, from
#: the separate search cap, when it dispatches.
RERUN_UNITS: Final[int] = 1

CODE_RERUN_UNKNOWN: Final[str] = "rerun_unknown"
CODE_RERUN_MISMATCH: Final[str] = "rerun_mismatch"
CODE_RERUN_INELIGIBLE: Final[str] = "rerun_ineligible"
CODE_RERUN_USED: Final[str] = "rerun_already_used"

RERUN_SHARED_CAP_MESSAGE: Final[str] = (
    "The showcase's shared hourly allowance for model calls, used by every "
    "example app, is too close to its cap for this re-run. This is the "
    "gallery-wide cap, not this app's 5-run limit: no run was used and nothing "
    "was held."
)


@dataclass(frozen=True)
class AdmittedRerun:
    """A re-run that passed admission and holds its one unit.

    Attributes:
        run_id: The re-run's own id.
        original_run_id: The run being re-run.
        preset: The preset; its expected route is the forced route.
    """

    run_id: uuid.UUID
    original_run_id: uuid.UUID
    preset: RouterPreset


async def admit_rerun(payload: RerunRequest) -> AdmittedRerun:
    """Admit a re-run: recompute eligibility from trusted data, then hold.

    The client's claim that a run is re-runnable is not used. The expected
    route comes from the preset catalogue and the dispatched route from the
    ticket recorded when the original run ended.

    Args:
        payload: The re-run request.

    Returns:
        The admitted re-run.

    Raises:
        RunRefusedError: When the re-run must not start. Nothing is held.
    """
    preset = get_preset(payload.preset_id)
    if preset is None:
        raise RunRefusedError(
            422, CODE_UNKNOWN_PRESET, "That preset is not in the curated set."
        )
    original = payload.original_run_id
    ticket = rerun.TICKETS.peek(original)
    if ticket is None:
        raise RunRefusedError(
            404,
            CODE_RERUN_UNKNOWN,
            "That run cannot be re-run: it is unknown, has expired, or was "
            "already re-run.",
        )
    if ticket.preset_id != preset.id:
        raise RunRefusedError(
            422, CODE_RERUN_MISMATCH, "That run was not a run of this preset."
        )
    if not rerun.is_eligible(preset=preset, dispatched_route=ticket.dispatched_route):
        raise RunRefusedError(
            422,
            CODE_RERUN_INELIGIBLE,
            "That run already went to its expected route, so there is nothing "
            "to compare.",
        )

    async with async_session_factory() as session:
        try:
            await shared.reserve_capability(
                session,
                shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=RERUN_UNITS,
            )
        except shared.ServiceUnavailableError:
            raise RunRefusedError(
                429, CODE_SHARED_CAP, RERUN_SHARED_CAP_MESSAGE
            ) from None
        try:
            await allowance_holds.reserve(
                session,
                hold_key=rerun.rerun_hold_key(original),
                capability=shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=RERUN_UNITS,
            )
        except allowance_holds.HoldStateError:
            await shared.release_capability(
                session,
                shared.CAPABILITY_GENERATION,
                app_name=ROUTER_APP_NAME,
                units=RERUN_UNITS,
            )
            rerun.TICKETS.spend(original)
            raise RunRefusedError(
                409, CODE_RERUN_USED, "That run has already been re-run once."
            ) from None

    rerun.TICKETS.spend(original)
    run_id = uuid.uuid4()
    logger.info(
        "router_rerun_admitted",
        run_id=str(run_id),
        original_run_id=str(original),
        preset_id=preset.id,
        route=preset.expected_route,
    )
    return AdmittedRerun(run_id=run_id, original_run_id=original, preset=preset)


def forced_plan(preset: RouterPreset) -> dispatch.DispatchPlan:
    """The dispatch plan for a re-run: the expected route, no router.

    The deterministic route evaluates the preset's curated expression -- the
    router, which would otherwise write one, does not run.

    Args:
        preset: The preset.

    Returns:
        The plan.
    """
    if preset.expected_route == DETERMINISTIC_EVALUATOR:
        return dispatch.DispatchPlan(
            route=DETERMINISTIC_EVALUATOR,
            evaluation=evaluate(preset.evaluator_expression or ""),
        )
    return dispatch.DispatchPlan(route=preset.expected_route)


async def _read_baseline(run_id: uuid.UUID) -> tuple[history.LatencyBaseline, bool]:
    """Read the latency baseline without writing anything. Never raises.

    Args:
        run_id: The re-run, for logs.

    Returns:
        The baseline, and whether it could not be read.
    """
    try:
        async with async_session_factory() as session:
            return await history.read_latency_baseline(session), False
    except Exception:  # noqa: BLE001 - an unreadable baseline is reported, not raised
        logger.exception("router_baseline_read_failed", run_id=str(run_id))
        return history.LatencyBaseline(typical_ms=None, sample_size=0), True


async def stream_rerun(run: AdmittedRerun) -> AsyncGenerator[StreamEvent, None]:
    """Dispatch the expected route directly and stream the result.

    No router call, no decision event, and no history row of either kind.

    Args:
        run: The admitted re-run, holding its one unit.

    Yields:
        `run_started`, `stage`, `answer`, `run_end`.
    """
    ledger = RunLedger(reserved=RERUN_UNITS)
    started = time.perf_counter()
    plan = forced_plan(run.preset)
    try:
        yield StreamEvent(
            EVENT_RUN_STARTED,
            RunStarted(
                run_id=str(run.run_id),
                request=run.preset.request,
                preset_id=run.preset.id,
                units_reserved=ledger.reserved,
                is_rerun=True,
                original_run_id=str(run.original_run_id),
            ).model_dump(),
        )
        if isinstance(plan.evaluation, Accepted):
            await _release_now(run.run_id, ledger, 1)
        yield StreamEvent(
            EVENT_STAGE,
            Stage(
                stage="dispatching",
                message=(
                    f"Re-running through {ROUTE_LABELS[plan.route]} (router skipped)"
                ),
            ).model_dump(),
        )
        answer = await dispatch.run(plan, run.preset.request, async_session_factory)
        ledger.charge(answer.units_used)
        if isinstance(answer, dispatch.TextAnswer):
            await _log_generation(run.run_id, answer)
        yield StreamEvent(EVENT_ANSWER, answer_event(plan, answer).model_dump())

        baseline, baseline_unavailable = await _read_baseline(run.run_id)
        strip = build_cost_strip(
            route=plan.route,
            model_calls=answer.units_used,
            searches=answer.searches,
            retrievals=answer.retrievals,
            route_ms=answer.elapsed_ms,
            overhead_calls=0,
            overhead_ms=0,
            baseline=baseline,
            unit_released=isinstance(plan.evaluation, Accepted),
            baseline_unavailable=baseline_unavailable,
        )
        yield StreamEvent(
            EVENT_RUN_END,
            RunEnd(
                run_id=str(run.run_id),
                ending="routed_answer",
                dispatched_route=plan.route,
                units=ledger.account(),
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                cost_strip=strip,
                rerun_eligible=False,
                is_rerun=True,
                original_run_id=str(run.original_run_id),
            ).model_dump(),
        )
    finally:
        await asyncio.shield(_settle(rerun.rerun_hold_key(run.original_run_id), ledger))
