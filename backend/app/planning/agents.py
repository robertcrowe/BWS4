# Built with Spec4 AI - https://spec4.ai
"""The three model steps of the planning agent: plan, research, synthesise.

Each is one call to the shared PydanticAI lane (`services/agent_runtime.py`) with
this app's prompt and this app's output type. The lane owns providers, the
fallback chain, and the cooldown bench; nothing here names a model slug, which
is the point -- `model_registry` is the single source of truth and these chains
are documented to rot.

## What the model is and is not allowed to author

The planner authors the whole `Plan`. The synthesis step authors the whole
`Itinerary`. But a research step authors **only its summary**: the sources on a
`StepResult` are built from what the search tool actually returned, recorded on
the way past. A model asked to report which sources it used can name ones it
never received, and the resulting `StepResult` would look identical to a real
one. Recording at the tool boundary is what makes the difference checkable.

## Search is injected, never imported

`run_research` takes an `execute_search` callable rather than importing
`services/web_search.py`, exactly as `tools/agent.py` does. Quota reservation,
`SearchQuery` persistence and logging all belong to the caller, so this module
holds no database concerns and its tests need neither a database nor an Exa key.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from backend.app.planning import sanitize
from backend.app.planning.schemas import (
    PLANNER_PROMPT_VERSION,
    RESEARCH_PROMPT_VERSION,
    SYNTHESIS_PROMPT_VERSION,
    Itinerary,
    Plan,
    PlanStep,
    ResearchFinding,
    SearchResult,
    StepResult,
)
from backend.app.services import agent_runtime
from backend.app.services.prompt_context import with_current_date
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.web_search import ExaResult

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent / "prompts"

#: How many model requests each step may make, and why each number is what it
#: is. These bound one *step*; the run-wide ceiling in `budget.py` bounds the
#: whole run and is the harder limit of the two.
#:
#: A research step needs at least two requests -- one to emit the tool call, one
#: to read the results and answer. Everything above that is measured padding:
#:
#:     1  the first search
#:     2  the reformulation the empty-results mitigation calls for
#:     3  the turn spent refusing a third search (measured: models ask anyway)
#:     4  the answer
#:     5  PydanticAI's own retry when that answer fails schema validation
#:
#: Three was the shipped value and budgeted the reformulation and the schema
#: retry into the same slot, so a step that reformulated had nothing left to
#: answer with. Four covered every request a re-probe actually observed -- and
#: exactly, with no margin, which is what this fifth adds. The planner and
#: synthesis steps use no tools, so one request suffices; their allowance of
#: two is that same schema-retry headroom.
PLANNER_REQUEST_LIMIT = 2
RESEARCH_REQUEST_LIMIT = 5
SYNTHESIS_REQUEST_LIMIT = 2

#: Searches one research step may run, enforced in code below.
#:
#: `research_v1.md` tells the model "One reformulation, never more". **A limit
#: stated in a prompt is not a limit**, and measurement is unambiguous about it:
#: probed against this repo's own lane, a step given *useful* results searched
#: four times in one run of three, and a step given empty results searched six
#: times in every run -- exhausting even a deliberately generous six-request
#: budget without ever answering. That is the failure reported from the running
#: app, where two research steps in a row died on `StepRequestLimitExceeded`.
#:
#: The cost is not only the run's own budget. `service.py` reserves a
#: `CAPABILITY_SEARCH` unit per search against an hourly cap of five shared
#: across the whole showcase, so one unbounded step could take the tool-use app
#: dark as well. The tool-use agent has always bounded its searches in code for
#: exactly this reason (`tools/agent.py::MAX_SEARCHES`); this step never did.
MAX_SEARCHES_PER_STEP = 2

#: Search results kept per step, after de-duplication by URL.
MAX_SOURCES_PER_STEP = 5

GateHook = Callable[[], Awaitable[None]]
ExecuteSearch = Callable[[str], Awaitable[list[ExaResult]]]

_GOAL_TEMPLATE = """The visitor wants a one-day itinerary.

City: {city}
Interests: {interests}"""

_REPLAN_TEMPLATE = """{goal}

Your previous plan was rejected by the plan checker. Fix every problem listed
and return a corrected plan.

Problems found:
{problems}"""

_RESEARCH_TEMPLATE = """{goal}

You are executing step {index} of the approved plan.

Step description: {description}
Search query to run: {query}"""

_SYNTHESIS_TEMPLATE = """{goal}

The approved plan was:
{plan}

The research steps have finished. Their results follow.

{results}"""


@dataclass
class ResearchOutcome:
    """One research step's model work, with the sources it genuinely retrieved.

    Attributes:
        summary: What the model reported finding.
        sources: What the search tool actually returned, de-duplicated by URL
            and recorded as the calls happened -- not read back off the model.
        queries: Every query the model ran, in order. Two entries means it
            reformulated.
        model: The slug that served the step.
        requests: Model requests the step consumed.
    """

    summary: str
    sources: list[SearchResult] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    model: str = "unknown"
    requests: int = 0


def build_goal(city: str, interests: str) -> str:
    """Render the goal block every step of the run is given.

    One rendering shared by planner, research and synthesis, so all three are
    working from an identical statement of what the visitor asked for.

    Args:
        city: The sanitised city.
        interests: The sanitised interests.

    Returns:
        The goal block.
    """
    return _GOAL_TEMPLATE.format(city=city, interests=interests)


async def run_planner(
    *,
    goal: str,
    problems: list[str] | None = None,
    on_request: GateHook | None = None,
) -> agent_runtime.StepResult[Plan]:
    """Decompose the goal into a plan, or re-plan against a checker's findings.

    Google-style docstring per project convention.

    Args:
        goal: The goal block from `build_goal`.
        problems: Errors from a previous `validator.check_plan`. When present
            this is the replan attempt, and the errors are quoted into the
            prompt so the model is fixing something specific rather than
            guessing what went wrong.
        on_request: Awaited before each model request.

    Returns:
        The candidate plan -- not yet checked. Validation is the caller's, and
        deliberately so: a planner that graded its own output would be the
        prompt-level enforcement this design exists to avoid.

    Raises:
        AgentLaneError: If the model chain could not produce a parseable plan.
    """
    user_prompt = goal
    if problems:
        user_prompt = _REPLAN_TEMPLATE.format(
            goal=goal,
            problems="\n".join(f"- {problem}" for problem in problems),
        )

    return await agent_runtime.run_typed_step(
        label="planner",
        instructions=load_prompt(PROMPTS_DIR, PLANNER_PROMPT_VERSION),
        user_prompt=user_prompt,
        output_type=Plan,
        request_limit=PLANNER_REQUEST_LIMIT,
        on_request=on_request,
    )


async def run_research(
    *,
    goal: str,
    step: PlanStep,
    execute_search: ExecuteSearch,
    on_request: GateHook | None = None,
    request_limit: int = RESEARCH_REQUEST_LIMIT,
) -> ResearchOutcome:
    """Execute one research step: the model searches, reads, and summarises.

    The model drives the tool. It is given the planner's query but calls
    `web_search` itself, may reformulate once when results are poor, and decides
    when it has enough -- that decision being the model's is what makes this a
    tool-using executor rather than a search call with a summarisation step
    bolted on.

    Args:
        goal: The goal block from `build_goal`.
        step: The research step to execute.
        execute_search: Injected search. The caller reserves quota, persists the
            query, and calls Exa; this module never learns how.
        on_request: Awaited before each model request.
        request_limit: Model requests this step may make. The orchestrator
            lowers it when the run has less budget left than a whole step
            needs, so the framework ends the step at the run's edge rather than
            the gate having to refuse part-way through one.

    Returns:
        The summary, the sources actually retrieved, and what the step cost.

    Raises:
        AgentLaneError: If the model chain failed or exceeded its request limit.
    """
    retrieved: list[ExaResult] = []
    queries: list[str] = []

    async def web_search(query: str) -> str:
        """Search the web for current information and return ranked results.

        Args:
            query: The search text to send to the web search engine. Write it
                as you would type it into a search box.

        Returns:
            The ranked results as text, inside an untrusted-content block.
        """
        if len(queries) >= MAX_SEARCHES_PER_STEP:
            # Refused *before* `execute_search`, so a model that keeps asking
            # spends this step's requests but no further search quota. Outside
            # the untrusted block on purpose: this sentence is the framework
            # speaking, and wrapping it in the delimiters the prompt is told to
            # distrust would be telling the model to ignore it.
            return (
                f"No searches remain for this step -- you have used all "
                f"{MAX_SEARCHES_PER_STEP}. Do not call `web_search` again. "
                "Answer now from the results you already have, and say plainly "
                "what you could not find."
            )

        queries.append(query)
        results = await execute_search(query)
        retrieved.extend(results)
        block = sanitize.untrusted_block(
            f"search results for {query!r}", _format_results(results)
        )

        if len(queries) < MAX_SEARCHES_PER_STEP:
            return block

        # The last permitted search says so in the same turn that delivers its
        # results. Waiting for the model to ask again would be correct and cost
        # a whole extra request to say no -- and measurement says it does ask
        # again, so that request would be spent most of the time.
        return (
            f"{block}\n\nThat was the last of your {MAX_SEARCHES_PER_STEP} "
            "searches for this step. Answer now from what you have, and say "
            "plainly what you could not find."
        )

    result = await agent_runtime.run_typed_step(
        label=f"research-step-{step.index}",
        # Dated: this is the one planning step that composes a *search query*,
        # and a model with no clock anchors "recent" on its training cutoff and
        # writes that year into the query. See services/prompt_context.py.
        instructions=with_current_date(
            load_prompt(PROMPTS_DIR, RESEARCH_PROMPT_VERSION)
        ),
        user_prompt=_RESEARCH_TEMPLATE.format(
            goal=goal,
            index=step.index,
            description=step.description,
            query=step.search_query or "",
        ),
        output_type=ResearchFinding,
        tools=[web_search],
        request_limit=request_limit,
        on_request=on_request,
    )

    return ResearchOutcome(
        summary=result.output.summary,
        sources=_to_sources(retrieved),
        queries=queries,
        model=result.model,
        requests=result.requests,
    )


async def run_synthesis(
    *,
    goal: str,
    plan: Plan,
    results: list[StepResult],
    on_request: GateHook | None = None,
) -> agent_runtime.StepResult[Itinerary]:
    """Compose the itinerary from the research that actually ran.

    Args:
        goal: The goal block from `build_goal`.
        plan: The executed plan, for restating each step's purpose.
        results: Every research step's result, including failed ones. Failures
            are passed in on purpose: the prompt asks the model to acknowledge
            gaps, and it cannot acknowledge a gap it was never shown.
        on_request: Awaited before each model request.

    Returns:
        The composed itinerary.

    Raises:
        AgentLaneError: If the model chain could not produce one.
    """
    return await agent_runtime.run_typed_step(
        label="synthesis",
        instructions=load_prompt(PROMPTS_DIR, SYNTHESIS_PROMPT_VERSION),
        user_prompt=_SYNTHESIS_TEMPLATE.format(
            goal=goal,
            plan=_format_plan(plan),
            results=_format_step_results(results),
        ),
        output_type=Itinerary,
        request_limit=SYNTHESIS_REQUEST_LIMIT,
        on_request=on_request,
    )


def _format_results(results: list[ExaResult]) -> str:
    """Render search results as the text a model reads.

    Args:
        results: What the search returned.

    Returns:
        One block per result, or an explicit statement that there were none --
        never an empty string, which a model would be free to interpret as a
        tool malfunction rather than as a genuine absence of results.
    """
    if not results:
        return "No results were returned for this query."

    return "\n\n".join(
        f"[{position}] {item.title}\nURL: {item.source}\n"
        f"{item.summary[: sanitize.MAX_SNIPPET_CHARS]}"
        for position, item in enumerate(results, start=1)
    )


def _to_sources(results: list[ExaResult]) -> list[SearchResult]:
    """Convert retrieved Exa results into the app's source shape.

    De-duplicates by URL, because a reformulated query commonly returns some of
    the same pages and the visitor should not see one source listed twice.

    Args:
        results: Everything the tool returned across all queries in this step.

    Returns:
        Up to `MAX_SOURCES_PER_STEP` unique sources, in retrieval order.
    """
    seen: set[str] = set()
    sources: list[SearchResult] = []

    for item in results:
        if item.source in seen:
            continue
        seen.add(item.source)
        sources.append(
            SearchResult(
                title=item.title,
                url=item.source,
                snippet=item.summary[: sanitize.MAX_SNIPPET_CHARS],
            )
        )
        if len(sources) >= MAX_SOURCES_PER_STEP:
            break

    return sources


def _format_plan(plan: Plan) -> str:
    """Render the plan as a numbered list for the synthesis prompt.

    Args:
        plan: The executed plan.

    Returns:
        One line per step.
    """
    return "\n".join(f"{step.index}. [{step.kind}] {step.description}" for step in plan.steps)


def _format_step_results(results: list[StepResult]) -> str:
    """Render step results into delimited untrusted blocks for the synthesis prompt.

    Each step's material is wrapped separately so the model can attribute a
    finding to a step number -- which is what `source_refs` cites.

    Args:
        results: Every research step's result.

    Returns:
        One untrusted block per step.
    """
    if not results:
        return sanitize.untrusted_block(
            "step results", "No research steps produced results in this run."
        )

    blocks = []
    for item in results:
        body = f"Status: {item.status}\nSummary: {item.summary}"
        if item.sources:
            listed = "\n".join(
                f"- {source.title} ({source.url})" for source in item.sources
            )
            body = f"{body}\nSources retrieved:\n{listed}"
        blocks.append(sanitize.untrusted_block(f"step {item.step_index} results", body))

    return "\n\n".join(blocks)
