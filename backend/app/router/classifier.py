# Built with Spec4 AI - https://spec4.ai
"""The route classification call: exactly one typed model call, never retried.

This is the whole of the Router's model involvement in a decision: one call
through the shared PydanticAI lane (`agent_runtime.run_typed_step`), slugs from
the shared registry, returning a `RoutingDecision`. Everything after it --
argmax, margin, tie-break, dispatch -- is code in `decision.py`.

**Zero retries.** The stack spec is authoritative over the capability spec's
one-retry figure: a schema-invalid decision is not re-asked. It is enforced
with `request_limit=1`, the same way the ReAct suitability and annotation
calls are bounded: PydanticAI's own output-validation retry would be a second
model request, so the limit turns it into a failure instead of a second call.
A failed or schema-invalid call is reported as `Classification.decision is
None`, which `decision.decide` turns into the dedicated malformed outcome.

The request is wrapped as untrusted data. The route block in the instructions
is `state.current_route_block()` -- the same string the page renders.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_ai.settings import ModelSettings

from backend.app.core import observability
from backend.app.router import state
from backend.app.router.constants import DETERMINISTIC_EVALUATOR, RouteId
from backend.app.services import agent_runtime
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR: Final[Path] = Path(__file__).parent / "prompts"
#: The classification prompt version. Bumped by adding `route_v2.md`, never by
#: editing a shipped version in place.
ROUTE_PROMPT_VERSION: Final[str] = "route_v1"
#: Where the route block is substituted into the prompt.
_ROUTE_PLACEHOLDER: Final[str] = "{route_descriptions}"
#: The step's label in logs and lane errors.
CLASSIFY_LABEL: Final[str] = "router-classify"
#: One model request, no output-validation retry.
CLASSIFY_REQUEST_LIMIT: Final[int] = 1
#: Longest rationale the card shows.
MAX_RATIONALE_CHARS: Final[int] = 160
#: Deterministic sampling: the margin rule, not a coin flip, decides close calls.
CLASSIFY_MODEL_SETTINGS: Final[ModelSettings] = {"temperature": 0.0}


class RouteScores(BaseModel):
    """A score for each of the four routes. All four are required.

    Fields are named by the route ids, so an unknown route is an extra field
    (forbidden) and a missing one is a missing required field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    deterministic_evaluator: float = Field(ge=0.0, le=1.0)
    single_call: float = Field(ge=0.0, le=1.0)
    retrieval: float = Field(ge=0.0, le=1.0)
    search_generation: float = Field(ge=0.0, le=1.0)

    def as_dict(self) -> dict[RouteId, float]:
        """Return the scores keyed by route id.

        Returns:
            The four scores.
        """
        return {
            "deterministic_evaluator": self.deterministic_evaluator,
            "single_call": self.single_call,
            "retrieval": self.retrieval,
            "search_generation": self.search_generation,
        }


class RoutingDecision(BaseModel):
    """The router's typed decision.

    Attributes:
        scores: One uncalibrated 0-1 score per route.
        route: The route the model says it chose. Advisory: code recomputes
            the choice from the scores and the scores win.
        rationale: One line, at most 160 characters.
        expression: The calculation in the evaluator's grammar, only when
            `route` is the deterministic evaluator. Untrusted text, never
            executed; it is only ever passed to the evaluator.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    scores: RouteScores
    route: RouteId
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_CHARS)
    expression: str | None = None

    @field_validator("rationale")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("rationale must be one line")
        return value.strip()

    @model_validator(mode="after")
    def _expression_only_for_deterministic(self) -> Self:
        if self.expression is not None and self.route != DETERMINISTIC_EVALUATOR:
            raise ValueError("expression must be null unless route is deterministic")
        return self


class RouteDescriptionsNotReadyError(RuntimeError):
    """The route block has not been generated, so the router cannot be told."""


@dataclass(frozen=True)
class Classification:
    """The result of the one classification call.

    Attributes:
        decision: The validated decision, or None when the call failed or the
            output did not match the schema.
        model: The slug that served the call, or None if none did.
        elapsed_ms: Wall-clock time of the call, measured here.
        failure: Why there is no decision, for logs and the card note.
    """

    decision: RoutingDecision | None
    model: str | None
    elapsed_ms: int
    failure: str | None = None


def build_instructions(route_block: str) -> str:
    """Load the versioned prompt and substitute the route block verbatim.

    Args:
        route_block: The exact block the page renders.

    Returns:
        The instructions the model receives.
    """
    template = load_prompt(PROMPTS_DIR, ROUTE_PROMPT_VERSION)
    return template.replace(_ROUTE_PLACEHOLDER, route_block)


async def classify(
    request: str,
    *,
    on_request: Callable[[], Awaitable[None]] | None = None,
) -> Classification:
    """Make the one classification call for a request.

    Args:
        request: The visitor's request (preset text or moderated free text).
        on_request: Awaited immediately before the model request -- where the
            caller redeems its reserved unit. Anything it raises propagates
            unchanged and no model is contacted.

    Returns:
        The classification: a decision, or None with the failure reason.

    Raises:
        RouteDescriptionsNotReadyError: If the route block is not generated.
        Exception: Whatever `on_request` raises.
    """
    route_block = state.current_route_block()
    if route_block is None:
        raise RouteDescriptionsNotReadyError("Route descriptions are not ready.")

    started = time.perf_counter()
    with observability.span("router.classify", "router classification call"):
        try:
            result = await agent_runtime.run_typed_step(
                label=CLASSIFY_LABEL,
                instructions=build_instructions(route_block),
                user_prompt=untrusted_block("visitor request", request),
                output_type=RoutingDecision,
                request_limit=CLASSIFY_REQUEST_LIMIT,
                on_request=on_request,
                model_settings=CLASSIFY_MODEL_SETTINGS,
            )
        except agent_runtime.AgentLaneError as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            logger.warning(
                "router_classification_schema_failure",
                error_type=type(exc).__name__,
                elapsed_ms=elapsed_ms,
            )
            return Classification(
                decision=None, model=None, elapsed_ms=elapsed_ms, failure=str(exc)
            )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info(
        "router_classification_completed",
        model=result.model,
        elapsed_ms=elapsed_ms,
        advisory_route=result.output.route,
    )
    return Classification(
        decision=result.output, model=result.model, elapsed_ms=elapsed_ms
    )
