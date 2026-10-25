# Built with Spec4 AI - https://spec4.ai
"""Code-owned dispatch from a decided route to that route's existing path.

The router model takes no part here and never sees a handler's result.
Dispatch is two steps:

1. **Plan** (pure). Decide the final route. On the deterministic route the
   model's expression goes to the evaluator *before anything is released*:
   - a confident deterministic choice the evaluator rejects falls back to
     single call -- the router's own misroute, stated on the card, inside the
     routed-answer ending;
   - a low-confidence tie-break that lands on deterministic and is rejected
     goes to the *other* torn route instead, and stays the low-confidence
     ending, because the router never chose.
   A malformed decision is planned straight to single call.
2. **Run** the final route's handler from `HANDLERS`, a plain table keyed by
   route id: the evaluator, the single-call route, the RAG example's retriever,
   or Exa search plus one generation call.

Each handler reports the model-call units it actually spent, so the run's
ledger charges what happened rather than what a route "usually" costs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal

import structlog

from backend.app.router import retrieval_route, search_route, single_call_route
from backend.app.router.constants import (
    DETERMINISTIC_EVALUATOR,
    RETRIEVAL,
    ROUTE_LABELS,
    SEARCH_GENERATION,
    SINGLE_CALL,
    RouteId,
)
from backend.app.router.decision import LowConfidence, Malformed, Outcome, Routed
from backend.app.router.evaluator import Accepted, Rejected, evaluate
from backend.app.router.retrieval_route import Passage
from backend.app.router.search_route import SessionFactory, Snippet

logger = structlog.get_logger()


@dataclass(frozen=True)
class DispatchPlan:
    """Where a request goes, decided by code before any route runs.

    Attributes:
        route: The final route.
        evaluation: The evaluator's verdict when the deterministic route was
            attempted, else None.
        fallback_note: The plain card statement when the evaluator rejected
            the expression and the request went elsewhere, else None.
    """

    route: RouteId
    evaluation: Accepted | Rejected | None = None
    fallback_note: str | None = None

    @property
    def evaluator_fallback(self) -> bool:
        """Whether the evaluator rejected and the request went elsewhere."""
        return isinstance(self.evaluation, Rejected)


@dataclass(frozen=True)
class DeterministicAnswer:
    """The evaluator's result. No model call was made."""

    expression: str
    value: float
    unit: str | None
    display: str
    units_used: int = 0
    elapsed_ms: int = 0
    searches: int = 0
    retrievals: int = 0
    kind: Literal["deterministic"] = "deterministic"


@dataclass(frozen=True)
class TextAnswer:
    """A generated answer from a model-backed route, with what grounded it.

    Attributes:
        text: The answer.
        model: The slug that served it.
        elapsed_ms: The route's own measured time.
        units_used: Model-call units spent.
        truncated: True when cut to fit the card.
        searches: Searches made.
        retrievals: Retrievals made.
        query: The exact search query, on the search route.
        snippets: The search results the answer cites.
        passages: The retrieved passages the answer cites.
        invalid_citations: Cited indices with no source, stripped or flagged.
        removed_urls: URLs the model wrote that were not a source's, removed.
        grounding: The RAG audit verdict on the retrieval route.
    """

    text: str
    model: str
    elapsed_ms: int
    units_used: int
    truncated: bool = False
    searches: int = 0
    retrievals: int = 0
    query: str | None = None
    snippets: tuple[Snippet, ...] = ()
    passages: tuple[Passage, ...] = ()
    invalid_citations: tuple[int, ...] = ()
    removed_urls: tuple[str, ...] = ()
    grounding: str | None = None
    kind: Literal["text"] = "text"


@dataclass(frozen=True)
class NoticeAnswer:
    """A candid, fixed non-answer: no model wrote it.

    Used when a route ran and honestly has nothing to say -- no usable search
    results, or a dataset that does not cover the request.
    """

    message: str
    elapsed_ms: int
    units_used: int = 0
    searches: int = 0
    retrievals: int = 0
    query: str | None = None
    snippets: tuple[Snippet, ...] = ()
    passages: tuple[Passage, ...] = ()
    kind: Literal["notice"] = "notice"


@dataclass(frozen=True)
class RouteFailure:
    """The route could not produce an answer. Nothing is fabricated.

    Whatever the route did gather -- snippets, passages -- is still shown.
    """

    message: str
    elapsed_ms: int
    units_used: int = 0
    searches: int = 0
    retrievals: int = 0
    query: str | None = None
    snippets: tuple[Snippet, ...] = ()
    passages: tuple[Passage, ...] = ()
    kind: Literal["failure"] = "failure"


RouteAnswer = DeterministicAnswer | TextAnswer | NoticeAnswer | RouteFailure


def _rejection_text(rejection: Rejected) -> str:
    return rejection.detail.rstrip(".")


def plan(outcome: Outcome) -> DispatchPlan:
    """Decide the final route for an outcome, gating deterministic on the evaluator.

    Args:
        outcome: Routed, low-confidence or malformed.

    Returns:
        The plan.
    """
    if isinstance(outcome, Malformed):
        return DispatchPlan(route=SINGLE_CALL)

    target = outcome.route if isinstance(outcome, Routed) else outcome.dispatched
    if target != DETERMINISTIC_EVALUATOR:
        return DispatchPlan(route=target)

    evaluation = evaluate(outcome.expression or "")
    if isinstance(evaluation, Accepted):
        return DispatchPlan(route=DETERMINISTIC_EVALUATOR, evaluation=evaluation)

    logger.info("router_evaluator_fallback", reason=evaluation.reason.value)
    reason = _rejection_text(evaluation)
    if isinstance(outcome, LowConfidence):
        other = outcome.other
        return DispatchPlan(
            route=other,
            evaluation=evaluation,
            fallback_note=(
                "The tie-break landed on the deterministic evaluator, but the "
                f"evaluator could not compute the expression ({reason}), so the "
                f"request went to {ROUTE_LABELS[other]}, the other route the "
                "router was torn between."
            ),
        )
    return DispatchPlan(
        route=SINGLE_CALL,
        evaluation=evaluation,
        fallback_note=(
            "The router chose the deterministic evaluator, but the evaluator "
            f"could not compute the expression ({reason}), so the request was "
            "dispatched to single call. This is a misroute of the router's own "
            "making."
        ),
    )


async def _deterministic(
    plan: DispatchPlan, _request: str, _sessions: SessionFactory
) -> RouteAnswer:
    evaluation = plan.evaluation
    if not isinstance(evaluation, Accepted):
        # Unreachable by construction: `plan` only routes here on acceptance.
        return RouteFailure(message="The evaluator did not accept.", elapsed_ms=0)
    return DeterministicAnswer(
        expression=evaluation.expression,
        value=evaluation.value,
        unit=evaluation.unit,
        display=evaluation.display,
    )


async def _single_call(
    _plan: DispatchPlan, request: str, _sessions: SessionFactory
) -> RouteAnswer:
    result = await single_call_route.answer(request)
    if isinstance(result, single_call_route.SingleCallFailure):
        return RouteFailure(message=result.message, elapsed_ms=result.elapsed_ms)
    return TextAnswer(
        text=result.answer_text,
        model=result.model,
        elapsed_ms=result.elapsed_ms,
        units_used=1,
        truncated=result.truncated,
    )


async def _retrieval(
    _plan: DispatchPlan, request: str, sessions: SessionFactory
) -> RouteAnswer:
    result = await retrieval_route.answer(request, sessions)
    if result.answer_text is not None and result.model is not None:
        return TextAnswer(
            text=result.answer_text,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
            units_used=result.model_calls,
            retrievals=result.retrievals,
            passages=result.passages,
            invalid_citations=result.unresolved_citations,
            grounding=result.status,
        )
    message = result.message or retrieval_route.RETRIEVAL_FAILED_MESSAGE
    if result.status == "low_relevance":
        return NoticeAnswer(
            message=message,
            elapsed_ms=result.elapsed_ms,
            retrievals=result.retrievals,
            passages=result.passages,
        )
    return RouteFailure(
        message=message,
        elapsed_ms=result.elapsed_ms,
        retrievals=result.retrievals,
        passages=result.passages,
    )


async def _search_generation(
    _plan: DispatchPlan, request: str, sessions: SessionFactory
) -> RouteAnswer:
    result = await search_route.answer(request, sessions)
    if result.answer_text is not None and result.model is not None:
        return TextAnswer(
            text=result.answer_text,
            model=result.model,
            elapsed_ms=result.elapsed_ms,
            units_used=result.model_calls,
            searches=result.searches,
            query=result.query,
            snippets=result.snippets,
            invalid_citations=result.invalid_citations,
            removed_urls=result.removed_urls,
        )
    message = result.message or search_route.COMPOSE_FAILED_MESSAGE
    if result.status == "no_results":
        return NoticeAnswer(
            message=message,
            elapsed_ms=result.elapsed_ms,
            searches=result.searches,
            query=result.query,
        )
    return RouteFailure(
        message=message,
        elapsed_ms=result.elapsed_ms,
        searches=result.searches,
        query=result.query,
        snippets=result.snippets,
    )


Handler = Callable[[DispatchPlan, str, SessionFactory], Awaitable[RouteAnswer]]

#: The dispatch table. Code, not the model, picks the entry.
HANDLERS: Final[dict[RouteId, Handler]] = {
    DETERMINISTIC_EVALUATOR: _deterministic,
    SINGLE_CALL: _single_call,
    RETRIEVAL: _retrieval,
    SEARCH_GENERATION: _search_generation,
}


async def run(
    plan: DispatchPlan, request: str, sessions: SessionFactory
) -> RouteAnswer:
    """Run the planned route's handler.

    Args:
        plan: The dispatch plan.
        request: The request text.
        sessions: Opens a database session, for routes that read or meter.

    Returns:
        The route's answer, notice or failure, with what it spent.
    """
    return await HANDLERS[plan.route](plan, request, sessions)
