# Built with Spec4 AI - https://spec4.ai
"""Structured-output shapes for the trip-day planning agent.

**These field names come straight from the capability specification's Schema
notes and are not ours to improve.** They are the contract three separate things
agree on — the planner's constrained decoding, the SSE payloads Phase 3 emits,
and the frontend types Phase 4 renders — so renaming `why_it_matches` to
something tidier would silently break the agreement at every one of them.

Versioned alongside the prompts, per the project's prompt-versioning convention:
`PROMPT_SET_VERSION` moves when a *shipped* shape changes, and a shipped version
is never edited in place. Prompt and schema move together because a planner
prompt describing four fields cannot be paired with a five-field model.

`SearchResult` is the one shape the specification names but does not define. It
is defined here as the projection of the framework's `ExaResult` that a model is
allowed to see, which is also what makes the mapping one-directional: results
enter from `services/web_search.py` and nothing here can invent one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: Bumped by adding a new prompt/schema set alongside this one, never by
#: editing these models in place -- a past run's output must stay reproducible
#: from the version that produced it.
PROMPT_SET_VERSION = "v1"

PLANNER_PROMPT_VERSION = "planner_v1"
RESEARCH_PROMPT_VERSION = "research_v1"
SYNTHESIS_PROMPT_VERSION = "synthesis_v1"

#: A step either gathers information or composes the answer. The planner may
#: emit no other kind, and the validator rejects a plan that tries.
KIND_RESEARCH = "research"
KIND_SYNTHESIS = "synthesis"

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class PlanStep(BaseModel):
    """One step of the planner's decomposition.

    Attributes:
        index: Position in the plan, 1-based and contiguous.
        kind: `research` (runs a web search) or `synthesis` (composes the
            itinerary). Exactly one synthesis step is allowed, and it must be
            last -- enforced by `validator.py`, not by this model, because a
            plan that breaks the rule must be *reported* rather than rejected
            at parse time so the replan can quote the reason back to the model.
        description: What this step is for, shown to the visitor before
            anything runs.
        search_query: The query a research step will run. Null for the
            synthesis step, and required non-empty for research steps.
    """

    index: int
    kind: Literal["research", "synthesis"]
    description: str
    search_query: str | None = None


class Plan(BaseModel):
    """The planner's output: a goal restated, and the steps to reach it."""

    goal: str
    steps: list[PlanStep]


class SearchResult(BaseModel):
    """One web result a research step actually retrieved.

    Not a model output. These are built from what `services/web_search.py`
    returned, so a citation in the itinerary can be resolved to a real
    retrieval rather than to something the model asserted was retrieved.
    """

    title: str
    url: str
    snippet: str


class StepResult(BaseModel):
    """The outcome of executing one plan step.

    Attributes:
        step_index: The `PlanStep.index` this reports on.
        status: `completed` or `failed`. A research step that ran but found
            nothing is **completed**, not failed -- the search worked and the
            honest answer is that the web had little to say. `failed` is
            reserved for a step that could not be carried out at all.
        summary: What the step found, in the model's words.
        sources: The results the tool actually returned. Empty is a legitimate
            and informative value.
    """

    step_index: int
    status: Literal["completed", "failed"]
    summary: str
    sources: list[SearchResult] = Field(default_factory=list)


class ItineraryBlock(BaseModel):
    """One part of the day.

    Attributes:
        time_of_day: Which part of the day this block fills.
        activity: What to do.
        why_it_matches: How this connects to the interests the visitor gave.
        source_refs: Indices of the `PlanStep`s whose research supports this
            block. An empty list is the honest marker for a block composed
            without research behind it.
    """

    time_of_day: Literal["morning", "afternoon", "evening"]
    activity: str
    why_it_matches: str
    source_refs: list[int] = Field(default_factory=list)


class Itinerary(BaseModel):
    """The synthesis step's output: one day, composed from the step results."""

    city: str
    blocks: list[ItineraryBlock]


class ResearchFinding(BaseModel):
    """What a research executor is asked to return.

    Deliberately *not* a `StepResult`. The model supplies the summary and
    nothing else; `step_index`, `status`, and `sources` are stamped by the
    orchestrator from what actually happened. A model asked to report which
    sources it used could name ones it never received -- the same class of
    unverified claim this project has had to remove three times.
    """

    summary: str
