# Built with Spec4 AI - https://spec4.ai
"""Wire schemas for a Router run: the request body and the staged events.

A run streams five kinds of event, in this order:

1. `run_started` -- the run was admitted and its two units are held.
2. `stage` -- progress, one per step (classifying, dispatching).
3. `decision` -- the decision card: all four scores, the chosen route, the
   rationale, and for presets the agreement statement; or the low-confidence
   caveat; or the malformed-decision note; and any evaluator fallback.
4. `answer` -- the dispatched route's answer labelled with its path: the
   evaluator's value and verdict, generated text, or a candid failure.
5. `run_end` -- the ending (routed answer or low-confidence card), the
   dispatched route, the unit accounting and the measured run time. The client
   spends one of its five runs on this event and on nothing else.

A refusal before the run starts (moderation, the shared cap, descriptions not
ready) is not an event at all: it is an ordinary HTTP error and no run exists.
"""

from __future__ import annotations

import uuid
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.router.constants import RouteId
from backend.app.router.cost_strip import CostStrip
from backend.app.router.decision import Agreement

#: Longest request a visitor may type, in characters. Matches the input's
#: `maxlength` on the page.
MAX_REQUEST_CHARS: Final[int] = 300

EVENT_RUN_STARTED: Final[str] = "run_started"
EVENT_STAGE: Final[str] = "stage"
EVENT_DECISION: Final[str] = "decision"
EVENT_ANSWER: Final[str] = "answer"
EVENT_RUN_END: Final[str] = "run_end"

Ending = Literal["routed_answer", "low_confidence"]
DecisionKind = Literal["routed", "low_confidence", "malformed"]
StageName = Literal["classifying", "dispatching"]


class RunRequest(BaseModel):
    """Body of `POST /api/router/run`.

    Attributes:
        request: The request text, trimmed. For a preset it must be the
            preset's canonical text: a preset id is a claim, and the server
            routes its own copy of the text rather than trusting the client's.
        preset_id: The preset this request is, if any.
        visit_id: The browser visit, for correlating a visitor's runs in logs.
    """

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)
    preset_id: str | None = Field(default=None, max_length=8)
    visit_id: str = Field(min_length=1, max_length=64)

    @field_validator("request")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("request must not be blank")
        return trimmed


class RerunRequest(BaseModel):
    """Body of `POST /api/router/rerun`.

    Attributes:
        preset_id: The preset whose run is being re-run.
        original_run_id: The run to re-run, from its `run_end` event.
        visit_id: The browser visit, for logs.
    """

    model_config = ConfigDict(extra="forbid")

    preset_id: str = Field(min_length=1, max_length=8)
    original_run_id: uuid.UUID
    visit_id: str = Field(min_length=1, max_length=64)


class RunRefusal(BaseModel):
    """The `detail` of an HTTP error refusing a run before it starts.

    Attributes:
        code: Machine-readable cause: `moderation_blocked`,
            `moderation_unavailable`, `shared_cap_reached`,
            `descriptions_not_ready` or `preset_mismatch`.
        message: What to show the visitor. A shared-cap refusal names the
            shared cap, never this app's five-run limit.
    """

    code: str
    message: str


class RunStarted(BaseModel):
    """The run was admitted: its units are held and classification follows.

    For a comparison re-run, `is_rerun` is true and no classification follows.
    """

    run_id: str
    request: str
    preset_id: str | None
    units_reserved: int
    is_rerun: bool = False
    original_run_id: str | None = None


class Stage(BaseModel):
    """One step of progress."""

    stage: StageName
    message: str


class LowConfidenceCard(BaseModel):
    """What the low-confidence card says.

    Attributes:
        torn: The two top-scoring routes, cheaper first.
        dispatched: The cheaper of the two.
        caveat: The plain statement shown on the card.
    """

    torn: tuple[RouteId, RouteId]
    dispatched: RouteId
    caveat: str


class DecisionEvent(BaseModel):
    """The decision card.

    Attributes:
        kind: Routed, low-confidence or malformed.
        chosen_route: The argmax route; None when malformed or low-confidence
            (the router did not choose).
        dispatched_route: Where the request goes.
        scores: All four uncalibrated scores; None only when malformed.
        rationale: The model's one-line rationale; plain text.
        expression: The model's expression, if any. Untrusted; never executed.
        agreement: For presets only: agreed, misrouted or declined. None for
            free text and for a malformed decision.
        expected_route: For presets, revealed now the decision is made.
        expected_reason: The preset's one-line reason.
        low_confidence: The low-confidence card's content, when that applies.
        malformed_note: The plain note for a malformed decision.
        evaluator_fallback_note: The plain statement when the evaluator
            rejected the expression and the request went elsewhere.
        classifier_ms: How long the classification call took.
        model: The slug that served the classification, if any did.
    """

    kind: DecisionKind
    chosen_route: RouteId | None
    dispatched_route: RouteId
    scores: dict[RouteId, float] | None
    rationale: str | None
    expression: str | None
    agreement: Agreement | None
    expected_route: RouteId | None
    expected_reason: str | None
    low_confidence: LowConfidenceCard | None
    malformed_note: str | None
    evaluator_fallback_note: str | None
    classifier_ms: int
    model: str | None


class UnitAccount(BaseModel):
    """What the run held and what happened to it.

    Attributes:
        reserved: Model-call units held before the router ran.
        used: Units actually spent on model calls.
        released: Units given back.
    """

    reserved: int
    used: int
    released: int


class SnippetOut(BaseModel):
    """One search result as shown beside the answer."""

    index: int
    title: str
    url: str
    excerpt: str
    published_date: str | None
    truncated: bool


class PassageOut(BaseModel):
    """One retrieved passage as shown beside the answer."""

    index: int
    title: str
    excerpt: str
    similarity: float
    cited: bool


class AnswerEvent(BaseModel):
    """The dispatched route's answer, labelled with its path.

    Attributes:
        route: The route that produced it.
        route_label: Its display name.
        kind: `deterministic` (the evaluator's value, no model call), `text`
            (generated), `notice` (a fixed candid non-answer, no model), or
            `failure` (no answer; nothing fabricated).
        text: Generated answer text, for `text`. Model output: render through
            the shared Markdown component, never as HTML.
        expression: The expression the evaluator computed, for `deterministic`.
        evaluator_verdict: `accepted` for a deterministic answer.
        value_display: The evaluator's result, e.g. `20 m/s`.
        model: The slug that served a generated answer.
        elapsed_ms: The route's own measured time.
        truncated: True when a generated answer was cut to fit.
        error: The plain statement, for `failure` and `notice`.
        query: The exact search query, on the search route.
        snippets: Search results, so `[n]` citations resolve on the page.
        passages: Retrieved passages, so `[n]` citations resolve on the page.
        invalid_citations: Cited indices with no source behind them.
        removed_urls: URLs the model wrote that were not a source's.
        grounding: The RAG audit verdict (`grounded` or `unsupported`).
        model_calls: Generation calls this route made.
        searches: Searches this route made.
        retrievals: Retrievals this route made.
    """

    route: RouteId
    route_label: str
    kind: Literal["deterministic", "text", "notice", "failure"]
    text: str | None = None
    expression: str | None = None
    evaluator_verdict: Literal["accepted"] | None = None
    value_display: str | None = None
    model: str | None = None
    elapsed_ms: int
    truncated: bool = False
    error: str | None = None
    query: str | None = None
    snippets: list[SnippetOut] = Field(default_factory=list)
    passages: list[PassageOut] = Field(default_factory=list)
    invalid_citations: list[int] = Field(default_factory=list)
    removed_urls: list[str] = Field(default_factory=list)
    grounding: str | None = None
    model_calls: int = 0
    searches: int = 0
    retrievals: int = 0


class RunEnd(BaseModel):
    """The run's ending. Exactly one per started run.

    Attributes:
        run_id: The run.
        ending: Routed answer or low-confidence card.
        dispatched_route: The route the request was dispatched to.
        units: The unit accounting.
        elapsed_ms: The whole run's measured time, router included.
        cost_strip: The route taken against the no-router baseline.
        rerun_eligible: True when the client may offer the comparison re-run:
            a preset run dispatched away from its expected route. The server
            rechecks this itself when a re-run is requested.
        is_rerun: True for a comparison re-run's own ending.
        original_run_id: For a re-run, the run it re-ran.
    """

    run_id: str
    ending: Ending
    dispatched_route: RouteId
    units: UnitAccount
    elapsed_ms: int
    cost_strip: CostStrip
    rerun_eligible: bool = False
    is_rerun: bool = False
    original_run_id: str | None = None
