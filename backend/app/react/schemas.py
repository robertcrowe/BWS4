# Built with Spec4 AI - https://spec4.ai
"""The request body, the SSE envelopes, and the whole-trace read model.

## The envelopes are a contract, not an implementation detail

`run_started`, `cycle_thought`, `cycle_action`, `cycle_observation`,
`cycle_counter`, `final_answer`, `budget_exhausted` and `error` are the event
names the stack spec's api_contract names, and the browser listens for exactly
those strings. Each has a model here so the payload is checked before it goes on
the wire rather than assembled from a dict at the call site -- the frontend
binds to field names, and a typo in a hand-built dict is a field the client
silently reads as `undefined`.

Thought, action, observation and counter are **four separate events for one
cycle**, deliberately. Batching them into a single per-cycle event would be
simpler and would destroy what the app exists to show: the model thinks, and
only then acts; the search runs, and only then is there an observation. Those
are separated in time by seconds, and collapsing them would leave the trace
appearing all at once with the reasoning order lost.

## What is deliberately absent

**`RunRequest` has no `cycle_budget` field.** The budget is server-fixed at
`Settings.react_cycle_budget` and there is no 3..6 clamp anywhere. The design
mock offers a cycle-budget select; that wording is superseded by the stack
spec's `react_run_call_budget` decision. The reason is not tidiness: the run's
whole worst case is reserved through `allowance_holds` before the first cycle,
so a client-supplied budget would let a caller reserve one number and spend
another.

There is also no answer field on anything the *catalogue* publishes -- see
`presets.py`. `FinalAnswer` carries an answer because a run produced one.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------
# Event names
# --------------------------------------------------------------------------

EVENT_RUN_STARTED = "run_started"
EVENT_CYCLE_THOUGHT = "cycle_thought"
EVENT_CYCLE_ACTION = "cycle_action"
EVENT_CYCLE_OBSERVATION = "cycle_observation"
EVENT_CYCLE_COUNTER = "cycle_counter"
EVENT_FINAL_ANSWER = "final_answer"
EVENT_BUDGET_EXHAUSTED = "budget_exhausted"
EVENT_ERROR = "error"

#: The post-run annotation, streamed *after* the terminal card.
#:
#: Deliberately **not** in `TERMINAL_EVENTS`: annotation is decorative, so it is
#: neither an ending nor a reason a run ends. A stream that never emits it is a
#: complete, correct run.
EVENT_HOP_ANNOTATIONS = "hop_annotations"

#: The three ways a stream can stop. **Exactly one** of these is emitted per
#: run, and it is the last event -- a run that ended in a budget exhaustion
#: must never also carry a final answer, since that is precisely the dressing-up
#: the feature refuses to do. Asserted in `test_react_api.py`.
TERMINAL_EVENTS: frozenset[str] = frozenset(
    {EVENT_FINAL_ANSWER, EVENT_BUDGET_EXHAUSTED, EVENT_ERROR}
)

#: The two endings `react_runs.ending` may carry, matching the table's check
#: constraint. An `error` terminal is not an ending: it means the run did not
#: reach one.
ENDING_FINAL_ANSWER = "final_answer"
ENDING_BUDGET_EXHAUSTED = "budget_exhausted"


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Body of `POST /api/react/run`.

    Exactly one of `preset_question_id` and `visitor_question` must be
    supplied. Enforced by a validator rather than by two endpoints, because the
    run is one operation either way -- what differs downstream is that a
    free-form question passes the shared moderation gate and the suitability
    check, and a curated preset skips both.

    Attributes:
        preset_question_id: A curated preset id, `p1`..`p5`.
        visitor_question: The visitor's own question.
        session_id: An opaque client-generated identifier for the browser
            session, used to correlate a visitor's runs in telemetry. Not an
            identity: nothing is stored against it and nothing authenticates
            it, and the real per-visit limit is the client-side run counter
            with the server-side hourly gate behind it.
    """

    preset_question_id: str | None = Field(default=None, max_length=32)
    visitor_question: str | None = Field(default=None, max_length=500)
    session_id: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def exactly_one_question_source(self) -> RunRequest:
        """Require exactly one of the two question sources.

        Returns:
            The validated request.

        Raises:
            ValueError: If both or neither question source was supplied.
        """
        preset = self.preset_question_id
        typed = self.visitor_question.strip() if self.visitor_question else None
        if bool(preset) == bool(typed):
            raise ValueError(
                "Supply exactly one of preset_question_id or visitor_question."
            )
        return self


# --------------------------------------------------------------------------
# Presets endpoint
# --------------------------------------------------------------------------


class PresetView(BaseModel):
    """One preset as the selector sees it.

    Carries the question, a chip label, and the two pieces of display metadata
    the selector uses. **It carries no answer, and nothing may add one** -- see
    `presets.py`. The per-hop maintainer notes are deliberately not published
    either: they are for arguing about the preset set, not for a visitor, and
    hop 1's `fact` in particular would resolve part of the question before the
    run began.

    Attributes:
        id: The preset id, `p1`..`p5`.
        label: Short chip text.
        question: The question, verbatim -- what the model is actually asked.
        hop_count: How many facts the question chains.
        guaranteed_fully_observed: True for the presets curated so every hop
            needs an observation.
    """

    id: str
    label: str
    question: str
    hop_count: int
    guaranteed_fully_observed: bool


class PresetsResponse(BaseModel):
    """Response body of `GET /api/react/presets`.

    Attributes:
        presets: The five curated questions, in catalogue order.
        set_version: Which catalogue version these came from.
        cycle_budget: The server-fixed search-cycle ceiling, published so the
            selector can state the run's cost without hardcoding a number that
            could drift from the server's.
    """

    presets: list[PresetView]
    set_version: str
    cycle_budget: int


# --------------------------------------------------------------------------
# SSE envelopes
# --------------------------------------------------------------------------


class RunStarted(BaseModel):
    """First event of every run.

    Attributes:
        run_id: The id the trace is retrievable under once the run ends.
        question: The question being answered, verbatim.
        question_source: `preset` or `custom`.
        preset_id: The preset id when there was one.
        cycle_budget: The server-fixed search-cycle ceiling for this run.
        runs_remaining: How many runs this visitor has left in the session,
            as the server understood it when the run began.
        stub: True while the loop is not yet built. The banner that says so is
            driven by this flag rather than by a frontend constant, so it stops
            rendering on its own when Phase 3 emits real events -- a hardcoded
            placeholder notice is the version of this that gets left behind.
    """

    run_id: str
    question: str
    question_source: Literal["preset", "custom"]
    preset_id: str | None = None
    cycle_budget: int
    runs_remaining: int
    stub: bool = False


class CycleThought(BaseModel):
    """The model's short reasoning at the start of one cycle.

    Attributes:
        cycle: 1-based cycle number.
        thought: The model's own words, unedited.
        stub: See `RunStarted.stub`.
    """

    cycle: int
    thought: str
    stub: bool = False


class CycleAction(BaseModel):
    """What the model chose to do this cycle.

    Two kinds, and the distinction is the pattern: `search` issues the exact
    query the model wrote, and `answer` is the model declaring it has enough.
    Deciding *not* to search is as much a routing decision as searching, so it
    is a first-class action rather than the absence of one.

    Attributes:
        cycle: 1-based cycle number.
        kind: `search` or `answer`.
        query: The exact query issued, verbatim, on a `search`. None on an
            `answer`.
        rationale: One line on why this action, from the model.
        stub: See `RunStarted.stub`.
    """

    cycle: int
    kind: Literal["search", "answer"]
    query: str | None = None
    rationale: str = ""
    stub: bool = False


class ObservationSnippet(BaseModel):
    """One search result, rendered verbatim into the observation.

    Rendered from what the search actually returned rather than from anything
    the model said about it -- the same rule as the RAG app's cited passages
    and the planning app's `StepResult.sources`. A model cannot name a source it
    was never handed, so a fabricated observation is visibly absent here.

    Attributes:
        title: The result's title.
        snippet: The summary text the search returned.
        url: Where it came from.
        published_date: When the page was published, or None. Rendered as
            "undated" rather than left blank: an empty slot reads as "recent"
            to someone scanning a list.
    """

    title: str
    snippet: str
    url: str
    published_date: str | None = None


class CycleObservation(BaseModel):
    """What came back from the action this cycle.

    Attributes:
        cycle: 1-based cycle number.
        results: The snippets returned, verbatim. Empty when nothing was found.
        empty: True when the search returned no results. An explicit
            observation rather than a missing one -- "the search found nothing"
            is a fact the next thought must be able to build on, and leaving
            the field blank invites the model to invent a result.
        stub: See `RunStarted.stub`.
    """

    cycle: int
    results: list[ObservationSnippet] = Field(default_factory=list)
    empty: bool = False
    stub: bool = False


class CycleCounter(BaseModel):
    """The budget as it stands after this cycle.

    Its own event rather than a field on the others so the counter can advance
    the moment a search is spent, which is what makes the budget being consumed
    visible while the run is still going.

    Attributes:
        searches_used: Searches issued so far.
        cycle_budget: The ceiling they are counted against.
        stub: See `RunStarted.stub`.
    """

    searches_used: int
    cycle_budget: int
    stub: bool = False


class ComposedAnswer(BaseModel):
    """The final-answer call's typed output.

    Its own model call with its own prompt, not a field harvested from the last
    cycle's `AnswerAction`. That action is the *decision* to stop searching; this
    is the answer composed with every observation in view, and it is the tenth
    and last request the run's budget reserves for.

    Attributes:
        answer: The answer, in the model's own words. Displayed as-is and
            deliberately not schema-constrained beyond being present.
        grounded_on: Observation indices the answer rests on. Checked against
            the run's real observation list by `audit_grounding` -- a model can
            cite a number it was never shown, and this app exists to make that
            visible rather than to trust it.
    """

    answer: str = Field(min_length=1)
    grounded_on: list[int] = Field(default_factory=list)


class GroundingAudit(BaseModel):
    """Whether the answer's citations point at observations that exist.

    The same shape of check as `rag/citations.py`, reused as a **pattern** and
    not as a module: RAG audits `[N]` markers against retrieved passages, this
    audits `grounded_on` against issued observations. Both answer one question
    the model cannot be trusted with -- did the thing you cited actually happen?

    Note what it deliberately does not do: it establishes that a cited
    observation *exists*, never that it *supports* the claim. Verifying support
    needs a second model call, which this run has no budget for and which the
    RAG app declined for the same reason.

    Attributes:
        all_cited_present: True when every cited index resolves.
        cited: The indices the answer cited, in the order cited.
        unverified: Cited indices with no matching observation. Surfaced on the
            card rather than silently dropped.
    """

    all_cited_present: bool
    cited: list[int] = Field(default_factory=list)
    unverified: list[int] = Field(default_factory=list)


class FinalAnswer(BaseModel):
    """Terminal event: the model answered.

    Attributes:
        run_id: The id the whole trace is retrievable under.
        answer: The answer, in the model's own words.
        observation_cycles: Which observations the answer drew on. These are
            observation indices, which are also the cycles that produced them.
        audit: Whether those citations resolve. Shown, not enforced.
        searches_used: How much of the budget the run spent.
        cycle_budget: The ceiling it was spent against.
        stub: See `RunStarted.stub`.
    """

    run_id: str
    answer: str
    observation_cycles: list[int] = Field(default_factory=list)
    audit: GroundingAudit
    searches_used: int
    cycle_budget: int
    stub: bool = False


#: Why a run ended without an answer. Every one of these is a candid ending, and
#: each maps to its own sentence on the card -- an operator reading telemetry and
#: a visitor reading the screen both need to know *which* wall was hit.
ExhaustionReason = Literal[
    "search_ceiling",
    "malformed_step",
    "search_unavailable",
    "model_unavailable",
    "wall_clock",
    "call_budget",
]


class BudgetExhausted(BaseModel):
    """Terminal event: the run stopped before it could answer.

    A legitimate ending, presented as one. **There is no `answer` field on this
    model and none may be added** -- that is the structural half of "a
    budget-exhausted run is never dressed up as an answer", and it is why this
    is a separate event rather than a flag on `FinalAnswer`.

    Attributes:
        run_id: The id the partial trace is retrievable under.
        reason: Which ceiling or failure ended the run.
        unresolved: What the run did not manage to establish, in plain words.
        partial_findings: Observation indices that did return something, so the
            visitor can see the run was not simply empty.
        searches_used: The budget spent.
        cycle_budget: The ceiling it was counted against.
        stub: See `RunStarted.stub`.
    """

    run_id: str
    reason: ExhaustionReason
    unresolved: list[str] = Field(default_factory=list)
    partial_findings: list[int] = Field(default_factory=list)
    searches_used: int
    cycle_budget: int
    stub: bool = False


def audit_grounding(
    grounded_on: list[int], observations: list[Observation]
) -> GroundingAudit:
    """Check an answer's citations against the observations the run really made.

    Args:
        grounded_on: The indices the model cited.
        observations: Every observation this run produced, in order.

    Returns:
        The audit. An empty citation list audits as *present* -- there is
        nothing unresolvable about citing nothing, and an answer that cites
        nothing is a different concern the card shows on its own.
    """
    known = {observation.index for observation in observations}
    unverified = [index for index in grounded_on if index not in known]
    return GroundingAudit(
        all_cited_present=not unverified,
        cited=list(grounded_on),
        unverified=unverified,
    )


class RunError(BaseModel):
    """Terminal event: the run could not continue.

    Carried as an event on a 200 stream rather than an HTTP error status,
    following the convention the planning, orchestrated and collaboration apps
    set: a run that produced cycles and then failed must not push the client's
    error branch and discard them.

    Attributes:
        code: Machine-readable reason, so the client can distinguish a refusal
            the visitor can fix from one they can only wait out.
        message: What to show the visitor.
        stub: See `RunStarted.stub`.
    """

    code: str
    message: str
    stub: bool = False


# --------------------------------------------------------------------------
# The typed per-cycle step: one thought, one action
# --------------------------------------------------------------------------

#: Bounds the specification's mechanism block states, restated here as the one
#: place they are enforced. They are short on purpose: the thought is displayed
#: beside its action in a trace card, and a query long enough to need 120
#: characters is a query the model has stopped composing and started narrating.
MAX_THOUGHT_CHARS = 240
MAX_QUERY_CHARS = 120


class SearchAction(BaseModel):
    """The model has decided to issue a web search this cycle.

    `query` is passed to Exa **verbatim** -- it is not reworded, expanded or
    templated on the way. That is what makes "the exact query issued" a claim
    the trace can honestly render, and it is why the field is bounded rather
    than free.

    Attributes:
        kind: The discriminator. Always `search`.
        query: The exact search text, non-empty and at most 120 characters.
    """

    kind: Literal["search"] = "search"
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


class AnswerAction(BaseModel):
    """The model has decided it can answer from the observations it has.

    `grounded_on` is what makes the answer auditable: it names the observation
    indices the answer rests on, so a later check can ask whether each one
    exists and whether it carries the fact claimed. **A non-empty list is
    required** -- an answer grounded on nothing is an answer from memory, and
    this app exists to tell the two apart.

    That every index must exist in the run's observation list is a *run-level*
    fact and cannot be expressed here; `unknown_grounding()` below is where it
    is checked, at the point the run's observations are known.

    Attributes:
        kind: The discriminator. Always `answer`.
        answer: The answer prose, displayed as-is. Deliberately not
            schema-constrained beyond being present.
        grounded_on: Observation indices the answer rests on. Non-empty.
    """

    kind: Literal["answer"] = "answer"
    answer: str = Field(min_length=1)
    grounded_on: list[int] = Field(min_length=1)


#: The two things a cycle may do, discriminated on `kind`. A tagged union rather
#: than a bare one so a malformed action is rejected against the *right* variant
#: and the validation error names it, instead of pydantic reporting that the
#: payload failed to match either member.
CycleAction_ = Annotated[SearchAction | AnswerAction, Field(discriminator="kind")]


class ReactStep(BaseModel):
    """One cycle's decision: a short thought, then exactly one action.

    The output type the model is bound to. Reading this off a validated object
    rather than out of prose is what lets the backend branch on `kind` and hand
    `query` to Exa without a regex anywhere in the path.

    Attributes:
        thought: The model's reasoning for this cycle, at most 240 characters.
            Displayed as-is; bounded so an eight-cycle transcript stays legible
            and stays inside the context the next cycle has to fit in.
        action: The search or the answer. Exactly one.
    """

    thought: str = Field(min_length=1, max_length=MAX_THOUGHT_CHARS)
    action: CycleAction_


class ReactSearchStep(BaseModel):
    """The cycle-1 output type: structurally incapable of answering.

    **This is the whole cycle-1 constraint, and it is a type rather than a
    sentence.** The capability's highest-likelihood failure is the model
    answering from memory on cycle 1, leaving a trace in which no observation
    did any work. Asking a model in prose not to answer yet is a request; not
    offering it the answer variant is a fact about what it can emit.

    Identical to `ReactStep` except that `action` admits only `SearchAction`, so
    `to_step()` widens without revalidating anything.

    Attributes:
        thought: The model's reasoning for this cycle.
        action: A search. There is no other option.
    """

    thought: str = Field(min_length=1, max_length=MAX_THOUGHT_CHARS)
    action: SearchAction

    def to_step(self) -> ReactStep:
        """Widen to the general step shape once the constraint has done its job.

        Returns:
            The same thought and action as a `ReactStep`, so the caller handles
            one type regardless of which cycle produced it.
        """
        return ReactStep(thought=self.thought, action=self.action)


def step_output_type(observation_count: int) -> type[ReactStep] | type[ReactSearchStep]:
    """Choose the output type this cycle's model call is bound to.

    Search-only until at least one observation exists, then the full union.
    Keyed on the observation count rather than the cycle number because that is
    what the constraint is actually about -- a cycle whose search failed leaves
    the run with nothing to answer from, and the answer branch should stay shut.

    Args:
        observation_count: How many observations the run has gathered so far.

    Returns:
        `ReactSearchStep` when there is nothing to answer from, `ReactStep`
        otherwise.
    """
    return ReactStep if observation_count > 0 else ReactSearchStep


def unknown_grounding(action: AnswerAction, observation_count: int) -> list[int]:
    """Return the cited observation indices that do not exist in the run.

    The run-level half of `AnswerAction`'s contract, which the schema cannot
    express. Observations are numbered from 1 in the order they were produced.

    Args:
        action: The answer the model returned.
        observation_count: How many observations the run actually gathered.

    Returns:
        Every cited index outside `1..observation_count`, in the order cited.
        Empty when every citation resolves.
    """
    return [
        index for index in action.grounded_on if index < 1 or index > observation_count
    ]


# --------------------------------------------------------------------------
# Observations: built server-side, never authored by a model
# --------------------------------------------------------------------------

#: Per-snippet cap before a snippet enters the model's context, per the
#: `hop_source_annotation` specification's truncation bound.
#:
#: The per-cycle total the same instruction asks for needs no second knob: Exa
#: returns at most `web_search.NUM_RESULTS` (5) results, so one cycle's snippet
#: payload is bounded by 5 x 400 = 2,000 characters by construction. On an
#: eight-cycle run that is ~16,000 characters of transcript, which every model
#: in the chain holds comfortably.
SNIPPET_MAX_CHARS = 400


class ObservationResult(BaseModel):
    """One search result inside an observation, verbatim from the provider.

    Every field is copied from the Exa payload. **The model never authors any
    of this** -- that is the app's honesty guarantee, and it is why a fabricated
    fact is visibly absent from the observation rather than blended into it.

    Attributes:
        idx: 1-based position within this observation.
        title: The result's title, verbatim.
        url: Where it came from.
        snippet: The provider's text, truncated to `SNIPPET_MAX_CHARS` and
            never otherwise transformed.
        published_date: When the page was published, or None -- rendered as
            "undated" rather than blank, since an empty slot reads as "recent".
        truncated: Whether this snippet was cut. Recorded so the prompt can say
            so and the model does not read absence as evidence.
    """

    idx: int
    title: str
    url: str
    snippet: str
    published_date: str | None = None
    truncated: bool = False


#: What happened when the query was issued.
#:
#: Three values, not two, and the third is why. An empty result and an
#: unreachable provider both produce no snippets, but they are different facts:
#: one is the web's answer to the question, the other is the demonstration
#: failing. The run tolerates at most one `unavailable` cycle before ending
#: candidly, and it could not apply that rule if the two looked alike.
ObservationStatus = Literal["ok", "empty", "unavailable"]


class Observation(BaseModel):
    """What one search action returned, recorded server-side.

    The domain record. Phase 3 projects it onto the `cycle_observation` SSE
    envelope and into the persisted trace; nothing here knows about either.

    Attributes:
        index: 1-based observation number, the value `AnswerAction.grounded_on`
            cites.
        query: The exact query issued, verbatim -- the same string handed to
            Exa, so the trace's claim about it is checkable.
        results: The snippets returned. Empty unless `status` is `ok`.
        is_empty: True when no snippets came back, for either reason. An
            **explicit** flag rather than a dropped cycle: the model has to be
            made to react to a miss, and a hidden miss is the failure mode this
            guards.
        status: Whether the search succeeded, found nothing, or could not run.
        detail: Why the search could not run. Operator-facing, never
            model-authored, and None unless `status` is `unavailable`.
        truncated: Whether any snippet in this observation was cut.
    """

    index: int
    query: str
    results: list[ObservationResult] = Field(default_factory=list)
    is_empty: bool
    status: ObservationStatus
    detail: str | None = None
    truncated: bool = False


# --------------------------------------------------------------------------
# The free-form question's suitability advisory
# --------------------------------------------------------------------------

#: What the check may conclude. **`unknown` is deliberately absent.** It is a
#: frontend-only sentinel meaning "nothing assessed this", and admitting it here
#: would let a model *claim* the fail-open state — which is exactly the claim
#: nothing would have checked. A test pins its absence.
SuitabilityVerdict_ = Literal[
    "multi_hop_live", "multi_hop_static", "single_hop", "unanswerable"
]

#: Cap on the sentence shown to the visitor.
MAX_VISITOR_MESSAGE_CHARS = 180

#: Cap on the description of the hop that needs live information.
MAX_LIVE_HOP_CHARS = 120

#: Hops the check may report. The spec says clamp above this rather than
#: reject: a model answering "7" has understood the question and mis-scaled its
#: answer, and spending a repair retry on that would cost more than it fixes.
MAX_ESTIMATED_HOPS = 5

#: Used when the model's own sentence cannot be shown. Keyed off the verdict so
#: the fallback still says something true about the question.
_MESSAGE_TEMPLATES: dict[str, str] = {
    "multi_hop_live": (
        "This looks like it needs more than one fact, and at least one of them "
        "changes over time — good conditions for the loop."
    ),
    "multi_hop_static": (
        "This looks like it needs more than one fact chained together, so the "
        "loop should have something to do."
    ),
    "single_hop": (
        "This looks answerable in a single lookup, so the loop may finish in one cycle."
    ),
    "unanswerable": (
        "This may not be answerable from a web search, so the run is likely to "
        "end without an answer."
    ),
}

_TAG = re.compile(r"<[^>]*>")
_MARKDOWN = re.compile(r"[*_`#\[\]()>|~]")
_URL = re.compile(r"(https?://|www\.|\b[\w-]+\.(?:com|org|net|io|ai|co)\b)", re.I)


def sanitise_visitor_message(message: str, verdict: str) -> str:
    """Make a model-written sentence safe to render verbatim.

    Strips tags and markdown markers, collapses whitespace, and **substitutes a
    template** when what is left carries a URL or overruns the cap. Substituting
    rather than raising is deliberate: an over-long or link-carrying sentence is
    a cosmetic fault, and failing validation over it would spend the one repair
    retry that exists for real schema breaches.

    Args:
        message: The model's sentence.
        verdict: The verdict it accompanies, selecting the fallback.

    Returns:
        A single plain sentence, at most `MAX_VISITOR_MESSAGE_CHARS` long.
    """
    cleaned = " ".join(_MARKDOWN.sub("", _TAG.sub(" ", message)).split())
    if not cleaned or _URL.search(cleaned) or len(cleaned) > MAX_VISITOR_MESSAGE_CHARS:
        return _MESSAGE_TEMPLATES.get(verdict, _MESSAGE_TEMPLATES["unanswerable"])
    return cleaned


class QuestionSuitability(BaseModel):
    """The advisory verdict on a visitor's own question.

    **Advisory, never a gate.** Nothing here may disable Start — that is the
    capability's central design property, and the failure it guards against is
    an upstream model outage silently closing the whole example. The frontend
    treats every value here, and the absence of any value, as a hint.

    Every invariant the specification names is enforced by a validator rather
    than trusted to the model. That is the point of the tier: the frontend
    branches on `verdict` and the eval joins `estimated_hops` against what the
    run actually did, so a self-contradictory verdict is read by code, not just
    displayed.

    Attributes:
        verdict: The four-way classification.
        estimated_hops: Chained facts the question needs, 1-5.
        requires_live_info: Whether any hop needs current information.
        live_hop_description: Which hop needs it. Present iff
            `requires_live_info`.
        exercises_loop: Whether this question will make the loop work. Derived
            from `verdict`, and corrected if the model disagrees with itself.
        confidence: How sure the check is. `low` is rendered as a hedge.
        visitor_message: One plain sentence, already sanitised.
    """

    verdict: SuitabilityVerdict_
    estimated_hops: int = Field(ge=1, le=MAX_ESTIMATED_HOPS)
    requires_live_info: bool
    live_hop_description: str | None = Field(
        default=None, max_length=MAX_LIVE_HOP_CHARS
    )
    exercises_loop: bool
    confidence: Literal["low", "medium", "high"]
    visitor_message: str = Field(max_length=MAX_VISITOR_MESSAGE_CHARS)

    @field_validator("estimated_hops", mode="before")
    @classmethod
    def _clamp_hops(cls, value: object) -> object:
        """Clamp an over-large hop count rather than rejecting it."""
        if isinstance(value, int) and value > MAX_ESTIMATED_HOPS:
            return MAX_ESTIMATED_HOPS
        return value

    @model_validator(mode="before")
    @classmethod
    def _sanitise_message(cls, data: object) -> object:
        """Clean the visitor-facing sentence *before* the field bounds apply.

        **This has to run in `mode="before"`.** `visitor_message` carries
        `max_length`, and a field bound rejects rather than repairs -- so an
        over-long sentence would fail validation, spend the one repair retry
        that exists for genuine schema breaches, and quite possibly resolve the
        whole check to the neutral state over a cosmetic fault. Sanitising
        first means the cap is applied by substitution and the field bound
        becomes a backstop that can no longer trip.

        It needs the verdict to pick the fallback, which a field validator
        cannot see -- hence a model validator rather than a field one.

        Args:
            data: The raw payload, before field validation.

        Returns:
            The payload with a safe sentence.
        """
        if not isinstance(data, dict):
            return data
        message = data.get("visitor_message")
        verdict = data.get("verdict")
        if isinstance(message, str) and isinstance(verdict, str):
            data = {
                **data,
                "visitor_message": sanitise_visitor_message(message, verdict),
            }
        return data

    @model_validator(mode="after")
    def _enforce_invariants(self) -> QuestionSuitability:
        """Apply the specification's invariants.

        Two are **repaired** and three are **rejected**, and the split is not
        arbitrary. `exercises_loop` is derivable from `verdict` with no
        ambiguity, so a model that disagrees with itself about it is corrected;
        the message is cosmetic, so it is sanitised. The other three are
        genuine self-contradictions about the answer — a `single_hop` verdict
        claiming three hops means the check did not decide anything — and those
        get the repair retry the capability provides for.

        Returns:
            The validated verdict.

        Raises:
            ValueError: On a self-contradictory verdict.
        """
        # Derivable, so corrected rather than argued with.
        object.__setattr__(self, "exercises_loop", self.verdict.startswith("multi_hop"))

        if self.requires_live_info != (self.live_hop_description is not None):
            raise ValueError(
                "live_hop_description must be present exactly when "
                "requires_live_info is true."
            )
        if self.verdict == "single_hop" and self.estimated_hops != 1:
            raise ValueError("A single_hop verdict must report exactly one hop.")
        if self.verdict == "multi_hop_live" and not self.requires_live_info:
            raise ValueError(
                "A multi_hop_live verdict must set requires_live_info to true."
            )

        return self


# --------------------------------------------------------------------------
# The post-run hop-source annotation
# --------------------------------------------------------------------------

#: Where a hop's fact came from.
#:
#: `mixed` exists because a hop can genuinely be both -- the model knew the
#: shape of the answer and an observation confirmed a figure. It is treated as a
#: grounding claim by the cross-checks, so it is downgraded on exactly the same
#: evidence `observation` is.
HopSourceLabel = Literal["observation", "model_knowledge", "mixed"]

#: Caps the specification names. Both are enforced twice: as a schema bound so
#: the model is told, and by truncation in code so an overrun trims the note
#: rather than rejecting the whole payload and costing every other hop its badge.
MAX_HOP_FACT_CHARS = 120
MAX_HOP_NOTE_CHARS = 200

#: Claims a budget-exhausted run's annotation must not make.
#:
#: The run produced no answer, so an annotation saying a hop was "answered" or
#: "resolved" would dress an unfinished run up as a finished one -- in the very
#: panel that exists to say where the facts came from. Scanned in code because a
#: prompt instruction is not a check.
_RESOLUTION_MARKERS: tuple[str, ...] = (
    "answered",
    "resolved",
    "the answer is",
    "final answer",
    "completes the chain",
    "concluded",
)


class HopAnnotation(BaseModel):
    """One hop, and where its fact actually came from.

    Attributes:
        cycle_index: The cycle this hop belongs to. Validated against the
            submitted trace in code; an index the run never produced is
            **dropped**, because a badge on the wrong hop is worse than none.
        fact: What the hop established, at most 120 characters.
        source: Observation, the model's own knowledge, or both.
        supporting_cycle: The cycle whose observation supplies the fact. Must
            not be later than `cycle_index` and must name a cycle that actually
            searched -- both checked in code, not trusted.
        note: One line of reasoning, at most 200 characters.
    """

    cycle_index: int
    fact: str = Field(max_length=MAX_HOP_FACT_CHARS)
    source: HopSourceLabel
    supporting_cycle: int | None = None
    note: str = Field(default="", max_length=MAX_HOP_NOTE_CHARS)


class HopAnnotations(BaseModel):
    """The model's reading of which hops observation actually supplied.

    **Note what is absent: there is no "every hop was observed" field.** That
    flag is the product criterion presets 1-3 rest on, so it is *derived in
    backend code* from the validated annotations rather than emitted here.
    Letting a model assert it would make the claim exactly as trustworthy as the
    over-crediting this whole feature exists to catch.

    Attributes:
        hops: One entry per numbered cycle, before the cross-checks run.
    """

    hops: list[HopAnnotation] = Field(default_factory=list)


class AnnotationResult(BaseModel):
    """What survived the cross-checks, and what the panel may claim.

    Attributes:
        hops: The annotations that passed. Partial results are kept -- a
            dropped entry costs one badge, not the whole panel.
        all_hops_observed: **Derived in code.** True only when every surviving
            hop is grounded in a cycle that really searched and really returned
            snippets.
        observed_count: How many hops observation supplied.
        recalled_count: How many came from the model's own knowledge.
        dropped: Annotations discarded, with why -- surfaced in telemetry so an
            index-drifting model is visible rather than merely quiet.
        downgraded: Hops whose grounding claim the cross-checks refused.
    """

    hops: list[HopAnnotation] = Field(default_factory=list)
    all_hops_observed: bool = False
    observed_count: int = 0
    recalled_count: int = 0
    dropped: list[str] = Field(default_factory=list)
    downgraded: list[int] = Field(default_factory=list)


def implies_resolution(note: str) -> bool:
    """Whether a note claims the run reached an answer.

    Args:
        note: The annotation's note text.

    Returns:
        True when it uses language a budget-exhausted run has not earned.
    """
    lowered = note.lower()
    return any(marker in lowered for marker in _RESOLUTION_MARKERS)


# --------------------------------------------------------------------------
# Whole-trace read model
# --------------------------------------------------------------------------


class SuitabilityVerdict(BaseModel):
    """The advisory verdict on a free-form question. Null on preset runs.

    Attributes:
        chained_facts: Whether the question needs more than one fact chained.
        needs_live_info: Whether at least one hop needs live web information.
        estimated_hops: How many facts the check thinks the chain needs.
        confidence: How sure the check is.
    """

    chained_facts: bool
    needs_live_info: bool
    estimated_hops: int
    confidence: str


class TraceResponse(BaseModel):
    """Response body of `GET /api/react/run/{run_id}`: one whole stored run.

    Read back whole rather than field by field, which is why the cycles and the
    terminal card are opaque JSON here -- they are handed to the client exactly
    as they were persisted. What is typed is the header: the metrics an
    operator aggregates across runs.

    Attributes:
        run_id: The run's id.
        created_at: When the run finished, ISO-8601.
        question_origin: A preset id, or `custom`. Never the question text.
        searches_used: How much of the budget the run spent.
        cycle_budget: The ceiling it was spent against.
        ending: `final_answer` or `budget_exhausted`, or None if neither was
            reached.
        duplicate_queries_blocked: Candidate queries the near-duplicate guard
            refused.
        empty_observations: Searches that returned nothing.
        annotation_outcome: How the post-run hop annotation went.
        suitability: The free-form question's verdict, when there was one.
        cycle_trace: The ordered cycles, as persisted.
        terminal_card: The final-answer or budget-exhausted card, as persisted.
        hop_annotations: The post-run hop-source labels, as persisted.
        cycle_timings: Per-cycle latencies, as persisted.
    """

    run_id: str
    created_at: str
    question_origin: str
    searches_used: int
    cycle_budget: int
    ending: str | None
    duplicate_queries_blocked: int
    empty_observations: int
    annotation_outcome: str | None
    suitability: SuitabilityVerdict | None
    cycle_trace: list[dict[str, object]]
    terminal_card: dict[str, object] | None
    hop_annotations: dict[str, object] | None
    cycle_timings: dict[str, object] | None
