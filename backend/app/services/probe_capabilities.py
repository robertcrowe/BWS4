# Built with Spec4 AI - https://spec4.ai
"""Probe a model slug against the capabilities this project's chains require.

Chain membership here means "probed for *this* capability", and there are four
of them. `discover_models.py` automates the first; this module automates the
other three, which were previously established by throwaway scripts and
recorded only as prose in the chain comments:

===========================  ==========================================
Governs                      Capability
===========================  ==========================================
TOOL_MODEL_CHAIN             LiteLLM tool loop -- `discover_models.py`
GENERATION_MODEL_CHAIN       `answer_v2` JSON + citation discipline
AGENT_LANE_KNOWN_BAD         PydanticAI typed output, no tools
TOOL_LANE_KNOWN_BAD          PydanticAI typed output *with* a tool
===========================  ==========================================

**A probe result belongs to a capability, not to a model.** This project has
been caught by that repeatedly -- the same slug passes one and fails another,
and one pair passes in *opposite* directions (`groq/llama-3.1-8b-instant` fails
tool-less typed output and passes it with a tool offered, because a model given
a real tool has no reason to invent one). Never carry a result across columns.

## What counts as a failure

Not everything that goes wrong disqualifies a slug, and the distinction is
mechanical rather than a judgement call:

* A **hard API error** is tolerable. `FallbackModel` falls through on
  `ModelAPIError`, and the budget gate wraps it from the *outside*, so the
  attempt costs no quota unit and no `request_limit` slot -- roughly a second of
  wall clock. A slug that fails this way some of the time can still earn a place
  as a cheap bet ahead of a slower provider.
* A **runaway** is fatal. A model that keeps calling the tool until
  `request_limit` trips raises `StepRequestLimitExceeded`, which nothing falls
  through: the step is lost along with everything already spent on it.
* **Empty-but-valid output** is worse still, because no layer has grounds to
  reject it. The same goes for an answer that cites a passage while declining,
  which is the one thing `rag/citations.py`'s audit cannot detect.

So the report gives a pass count *and* a failure class per case. Read both.

## Usage

    uv run python -m backend.app.services.probe_capabilities \
        --slug groq/llama-3.3-70b-versatile --runs 5

No Exa quota is spent: the research probe's search tool is stubbed. Provider
quota *is* spent, one request per run per case.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import litellm
from pydantic import BaseModel, Field, ValidationError

from backend.app.rag.answer import _SYSTEM_PROMPT, PROMPT_VERSION, _extract_json_object
from backend.app.rag.citations import audit_citations
from backend.app.rag.prompt_loader import load_prompt
from backend.app.rag.schemas import LlmAnswer
from backend.app.services import agent_runtime, model_registry

#: Runs per slug per case unless overridden. Three because every failure this
#: module classifies has been observed as *intermittent* at least once -- a
#: single run measures the weather.
DEFAULT_RUNS = 3

REQUEST_TIMEOUT_SECONDS = 60

#: Seconds between cases. One pass costs *more* than its five cases: the two
#: tool cases take 2-3 provider requests each, so a pass is nearer eight. Paced
#: for that rather than for the case count, with `_patiently` absorbing the
#: rest. An unpaced run measures the meter instead of the model -- measured on a
#: provider allowing 5 requests/minute, where the first version of this module
#: reported every slug as failing.
STAGGER_SECONDS = 20.0

#: A rate limit is not a result, so it is waited out rather than recorded.
#:
#: The floor matters more than the provider's stated delay and is not a padding
#: guess. A per-minute allowance is a *rolling window*, and a tool case spends
#: 2-3 requests, so retrying one costs 6-9 requests against a tight allowance:
#: waiting the ~36s one provider asked for put the retry back inside the same
#: window and it 429'd again. Waiting a full window clears it.
RATE_LIMIT_RETRIES = 2
MIN_RATE_LIMIT_WAIT_SECONDS = 62.0
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 62.0
MAX_RATE_LIMIT_WAIT_SECONDS = 150.0

#: Failure classes that do not disqualify a slug. See the module docstring.
TOLERABLE_FAILURES = frozenset({"api_error"})


@dataclass(frozen=True)
class ProbeResult:
    """One probe run.

    Attributes:
        capability: Which chain or exclusion set this bears on.
        case: The variant within the capability, e.g. "declining".
        ok: Whether the model did what the capability requires.
        failure: A failure class, or None on success. Compare against
            TOLERABLE_FAILURES rather than treating every failure alike.
        detail: Human-readable specifics, for the operator reading the table.
        seconds: Wall clock, which is why this exercise started.
    """

    capability: str
    case: str
    ok: bool
    failure: str | None
    detail: str
    seconds: float


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

#: Passages that genuinely answer the question below, so a grounded answer is
#: possible and a citation is checkable against a known-correct index.
_ANSWERABLE_PASSAGES = [
    "(Voyager Program) Voyager 1 launched on 5 September 1977 and crossed the "
    "heliopause in August 2012, becoming the first craft to enter interstellar "
    "space.",
    "(Hubble Space Telescope) Hubble was carried to orbit by Space Shuttle "
    "Discovery in April 1990 and observes mainly in visible and ultraviolet "
    "light.",
]
_ANSWERABLE_QUESTION = "When did Voyager 1 cross the heliopause?"

#: The passages are on-topic but contain nothing that answers the question --
#: the case `answer_v2` must decline, **without citation markers**, because
#: `citations.py` reads a marker on a refusal as a grounded answer.
_UNANSWERABLE_QUESTION = "Who was the first woman to travel into space?"

#: Distinctive enough that a summary repeating them is demonstrably working
#: from the results rather than from the model's own knowledge.
_SEARCH_RESULTS = (
    "[1] Meridian Observatory opening times -- open 09:30-17:00, closed Tuesdays.\n"
    "[2] Meridian Observatory transit -- reached by the number 44 tram.\n"
    "[3] Meridian Observatory cafe -- serves lunch until 15:00."
)
_GROUNDING_TOKENS = ("meridian", "09:30", "tram", "44")


class _Summary(BaseModel):
    """The typed output both agent-lane probes ask for."""

    summary: str = Field(description="What you found, in two or three sentences.")
    confident: bool = Field(description="Whether the material supported an answer.")


# --------------------------------------------------------------------------
# Capability 2: generation (answer_v2 JSON + citation discipline)
# --------------------------------------------------------------------------


def _render_answer_prompt(question: str, passages: Sequence[str]) -> str:
    """Fill the shipped `answer_v2` template exactly as `rag/answer.py` does.

    Args:
        question: The question to put to the model.
        passages: Passage texts, numbered from 1 in the rendered prompt.

    Returns:
        The rendered prompt.
    """
    template = load_prompt(PROMPT_VERSION)
    numbered = "\n\n".join(f"[{i}] {text}" for i, text in enumerate(passages, start=1))
    return template.replace("{{PASSAGES}}", numbered).replace("{{QUESTION}}", question)


async def probe_generation(slug: str, *, declining: bool) -> ProbeResult:
    """Check one slug against the RAG answer capability.

    Runs the real `answer_v2` prompt and applies the same two checks the app
    depends on: the response must validate as `LlmAnswer`, and its citation
    markers must match what the case calls for. The declining case is the
    load-bearing one -- `citations.py` distinguishes a grounded answer from a
    refusal *solely* by whether markers are present, so a model that cites a
    passage while declining silently defeats the audit.

    Args:
        slug: The full registry slug, e.g. "groq/openai/gpt-oss-120b".
        declining: Whether to pose the question the passages cannot answer.

    Returns:
        The probe result.
    """
    case = "declining" if declining else "answerable"
    question = _UNANSWERABLE_QUESTION if declining else _ANSWERABLE_QUESTION
    prompt = _render_answer_prompt(question, _ANSWERABLE_PASSAGES)
    started = time.monotonic()

    model_registry.ensure_provider_credentials()
    try:
        response = await litellm.acompletion(
            model=slug,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001 - any provider/transport failure
        return ProbeResult(
            "generation",
            case,
            False,
            _classify_exception(exc),
            f"{type(exc).__name__}: {str(exc)[:120]}",
            time.monotonic() - started,
        )

    elapsed = time.monotonic() - started
    raw = response.choices[0].message.content or ""
    try:
        answer = LlmAnswer.model_validate(json.loads(_extract_json_object(raw)))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        return ProbeResult(
            "generation",
            case,
            False,
            "schema",
            f"not answer_v2-shaped: {type(exc).__name__}: {raw[:90]!r}",
            elapsed,
        )

    if not answer.answer.strip():
        return ProbeResult(
            "generation", case, False, "empty_output", "blank answer", elapsed
        )

    audit = audit_citations(answer.answer, len(_ANSWERABLE_PASSAGES))
    if declining:
        # The rule `answer_v2` exists to add, and the only one nothing
        # downstream can re-derive.
        if audit.cited or audit.unresolved:
            return ProbeResult(
                "generation",
                case,
                False,
                "cited_when_declining",
                f"declined but emitted markers {audit.cited or audit.unresolved}",
                elapsed,
            )
        return ProbeResult("generation", case, True, None, "declined cleanly", elapsed)

    if not audit.cited:
        return ProbeResult(
            "generation", case, False, "ungrounded", "answered without citing", elapsed
        )
    if audit.unresolved:
        return ProbeResult(
            "generation",
            case,
            False,
            "ungrounded",
            f"cited passages that do not exist: {audit.unresolved}",
            elapsed,
        )
    return ProbeResult("generation", case, True, None, f"cited {audit.cited}", elapsed)


# --------------------------------------------------------------------------
# Capabilities 3 and 4: the PydanticAI lane, without and with a tool
# --------------------------------------------------------------------------


@asynccontextmanager
async def _pinned_to(slug: str) -> AsyncIterator[None]:
    """Force the lane to build a one-model chain of exactly `slug`.

    Deliberately bypasses `lane_chain`'s exclusion sets. A probe whose job is to
    re-test a slug the exclusion sets currently reject cannot ask those sets
    whether it may run -- that is the whole reason to re-probe, and the sets are
    known to rot. Everything else stays real: `run_typed_step` supplies the same
    output binding, request limits and error handling the apps get.

    Args:
        slug: The full registry slug to pin.

    Yields:
        None, for the duration of the pin.
    """
    original = agent_runtime.lane_chain
    agent_runtime.lane_chain = lambda chain=None, **_: [slug]
    try:
        yield
    finally:
        agent_runtime.lane_chain = original


async def probe_agent_typed(slug: str) -> ProbeResult:
    """Check one slug against tool-less typed output (`AGENT_LANE_KNOWN_BAD`).

    PydanticAI binds typed output through a synthetic output tool, which is a
    requirement neither the LiteLLM probes cover. The recorded failure here is a
    model inventing a tool that was never offered.

    Args:
        slug: The full registry slug.

    Returns:
        The probe result.
    """
    started = time.monotonic()
    async with _pinned_to(slug):
        try:
            step = await agent_runtime.run_typed_step(
                label="probe-typed",
                instructions=(
                    "You summarise material for a colleague. Answer only from "
                    "what the user gives you."
                ),
                user_prompt=(
                    "Summarise this for a visitor planning a trip:\n" + _SEARCH_RESULTS
                ),
                output_type=_Summary,
                request_limit=2,
            )
        except Exception as exc:  # noqa: BLE001 - the lane raises several types
            return ProbeResult(
                "agent_typed",
                "plain",
                False,
                _classify_exception(exc),
                f"{type(exc).__name__}: {str(exc.__cause__ or exc)[:120]}",
                time.monotonic() - started,
            )

    elapsed = time.monotonic() - started
    if not step.output.summary.strip():
        return ProbeResult(
            "agent_typed", "plain", False, "empty_output", "blank summary", elapsed
        )
    return ProbeResult(
        "agent_typed",
        "plain",
        True,
        None,
        f"{step.requests} req, {len(step.output.summary)}ch",
        elapsed,
    )


async def probe_agent_tool(slug: str, *, empty_results: bool) -> ProbeResult:
    """Check one slug against typed output *while* calling a tool.

    Two cases, because the recorded failures differ between them: given useful
    results a bad model over-searches, and given none it may never stop. The
    search is stubbed, so no Exa quota is involved.

    Args:
        slug: The full registry slug.
        empty_results: Whether the stubbed search returns nothing.

    Returns:
        The probe result.
    """
    case = "empty" if empty_results else "useful"
    searches: list[str] = []
    started = time.monotonic()

    async def lookup(query: str) -> str:
        """Look up visitor information about a place.

        Args:
            query: What to look up, written as a search phrase.

        Returns:
            Ranked results as text.
        """
        searches.append(query)
        if empty_results:
            return "No results were returned for that query."
        return _SEARCH_RESULTS

    async with _pinned_to(slug):
        try:
            step = await agent_runtime.run_typed_step(
                label="probe-tool",
                instructions=(
                    "Use the `lookup` tool once to research the visitor's "
                    "question, then summarise what it returned. You may search "
                    "at most twice. If nothing useful comes back, say so plainly "
                    "rather than answering from your own knowledge."
                ),
                user_prompt="What should a visitor know about Meridian Observatory?",
                output_type=_Summary,
                tools=[lookup],
                request_limit=4,
            )
        except Exception as exc:  # noqa: BLE001 - the lane raises several types
            return ProbeResult(
                "agent_tool",
                case,
                False,
                _classify_exception(exc),
                f"{type(exc).__name__}: {str(exc.__cause__ or exc)[:120]}",
                time.monotonic() - started,
            )

    elapsed = time.monotonic() - started
    summary = step.output.summary.strip()
    if not summary:
        return ProbeResult(
            "agent_tool", case, False, "empty_output", "blank summary", elapsed
        )
    if not searches:
        return ProbeResult(
            "agent_tool", case, False, "no_tool_call", "never called the tool", elapsed
        )
    if not empty_results and not any(t in summary.lower() for t in _GROUNDING_TOKENS):
        return ProbeResult(
            "agent_tool",
            case,
            False,
            "ungrounded",
            f"summary ignores the results: {summary[:80]!r}",
            elapsed,
        )
    return ProbeResult(
        "agent_tool",
        case,
        True,
        None,
        f"{step.requests} req, {len(searches)} search, {len(summary)}ch",
        elapsed,
    )


def _classify_exception(exc: BaseException) -> str:
    """Sort a failure into the classes the module docstring defines.

    Args:
        exc: The exception raised by a probe.

    The whole exception *tree* is scanned, not just the top frame. The agent
    lane wraps provider failures twice over -- an `AgentLaneError` whose cause
    is a `FallbackExceptionGroup` whose sub-exceptions carry the real status --
    and `str()` on the outer layer says only "All models from FallbackModel
    failed". A first version read only the outer frame and reported a 429 as an
    ordinary `api_error`, which is the difference between "this model is busy"
    and "this model is disqualified": it would have excluded four healthy slugs.

    Args:
        exc: The exception raised by a probe.

    Returns:
        A failure class. "runaway" and "rate_limited" are the two that must not
        be read as ordinary API errors -- the first disqualifies a slug, the
        second says nothing about it at all.
    """
    if isinstance(exc, agent_runtime.StepRequestLimitExceeded):
        return "runaway"
    text = _flatten(exc)
    if model_registry.looks_rate_limited(text):
        return "rate_limited"
    if model_registry.names_permanent_failure(text):
        # Distinguished from `api_error` because it is the opposite of
        # intermittent: a withdrawn or misspelled slug fails every time, so
        # reporting it as a tolerable flake would invite listing it as a cheap
        # bet. Observed on a slug that was retired mid-probe.
        return "unavailable"
    return "api_error"


def _flatten(exc: BaseException, depth: int = 0) -> str:
    """Collect the text of an exception and everything nested beneath it.

    Args:
        exc: The exception to flatten.
        depth: Recursion guard, since `__cause__` chains can cycle.

    Returns:
        The concatenated text of the whole tree.
    """
    if depth > 5:
        return ""
    parts = [str(exc)]
    for nested in getattr(exc, "exceptions", []) or []:
        parts.append(_flatten(nested, depth + 1))
    if exc.__cause__ is not None:
        parts.append(_flatten(exc.__cause__, depth + 1))
    return " ".join(parts)


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


@dataclass
class SlugReport:
    """Every result gathered for one slug.

    Attributes:
        slug: The registry slug probed.
        results: Every run, in the order they were made.
    """

    slug: str
    results: list[ProbeResult] = field(default_factory=list)

    def verdict(self, capability: str) -> str:
        """Summarise one capability as a line an operator can paste into a comment.

        Args:
            capability: The capability key, e.g. "agent_tool".

        Returns:
            A one-line verdict, including the failure classes seen.
        """
        runs = [r for r in self.results if r.capability == capability]
        if not runs:
            return "not probed"
        passed = sum(1 for r in runs if r.ok)
        classes = sorted({r.failure for r in runs if r.failure})
        blocking = sorted(
            c for c in classes if c not in TOLERABLE_FAILURES and c != "rate_limited"
        )
        median = sorted(r.seconds for r in runs)[len(runs) // 2]
        verdict = "ADOPT" if passed and not blocking else "REJECT"
        if any(r.failure == "rate_limited" for r in runs) and not passed:
            verdict = "INCONCLUSIVE (rate limited)"
        detail = f", failures: {', '.join(classes)}" if classes else ""
        return f"{verdict} -- {passed}/{len(runs)} passed, ~{median:.1f}s{detail}"


async def _patiently(probe: Callable[[], Awaitable[ProbeResult]]) -> ProbeResult:
    """Run one probe, waiting out a rate limit rather than recording one.

    Free tiers are metered tightly enough that an unpaced probe measures the
    meter instead of the model. Measured against a provider allowing five
    requests per minute per model: the first version had no pacing and reported
    every one of its slugs as failing, which is the exact trap
    `discover_models.py`'s `STAGGER_SECONDS` already existed to avoid -- and the
    reason a 429 must never be recorded as incapability.

    Waits the window the provider itself states, via the shared parser, so this
    adapts to whichever provider is being probed.

    Args:
        probe: A zero-argument coroutine function running one case.

    Returns:
        The probe result, after up to `RATE_LIMIT_RETRIES` attempts.
    """
    result = await probe()
    for _ in range(RATE_LIMIT_RETRIES):
        if result.failure != "rate_limited":
            return result
        stated = model_registry.parse_retry_after(result.detail)
        wait = max(
            stated or DEFAULT_RATE_LIMIT_WAIT_SECONDS, MIN_RATE_LIMIT_WAIT_SECONDS
        )
        wait = min(wait, MAX_RATE_LIMIT_WAIT_SECONDS)
        print(f"      (rate limited; waiting {wait:.0f}s)", flush=True)
        await asyncio.sleep(wait + 1.0)
        result = await probe()
    return result


async def probe_slug(slug: str, runs: int = DEFAULT_RUNS) -> SlugReport:
    """Run every capability probe against one slug.

    Cases are separated by `STAGGER_SECONDS`, which keeps a run inside a
    5-per-minute allowance without relying on the retry path to absorb it.

    Args:
        slug: The full registry slug.
        runs: Repetitions per case.

    Returns:
        The gathered report.
    """
    report = SlugReport(slug=slug)
    cases: list[Callable[[], Awaitable[ProbeResult]]] = [
        lambda: probe_generation(slug, declining=False),
        lambda: probe_generation(slug, declining=True),
        lambda: probe_agent_typed(slug),
        lambda: probe_agent_tool(slug, empty_results=False),
        lambda: probe_agent_tool(slug, empty_results=True),
    ]
    for run_index in range(runs):
        for case_index, case in enumerate(cases):
            if run_index or case_index:
                await asyncio.sleep(STAGGER_SECONDS)
            report.results.append(await _patiently(case))
    return report


CAPABILITIES = ("generation", "agent_typed", "agent_tool")


async def main(slugs: Sequence[str], runs: int) -> None:
    """Probe each slug and print a report.

    Args:
        slugs: Full registry slugs to probe.
        runs: Repetitions per case.
    """
    for slug in slugs:
        print(f"\n=== {slug}", flush=True)
        report = await probe_slug(slug, runs)
        for result in report.results:
            mark = "pass" if result.ok else f"FAIL[{result.failure}]"
            print(
                f"  {result.capability:12s} {result.case:10s} "
                f"{result.seconds:6.1f}s  {mark:22s} {result.detail}",
                flush=True,
            )
        print("  --", flush=True)
        for capability in CAPABILITIES:
            print(f"  {capability:12s} {report.verdict(capability)}", flush=True)


def _parse_args() -> argparse.Namespace:
    """Parse the command line.

    Returns:
        The parsed arguments.
    """
    summary = __doc__.splitlines()[0] if __doc__ else ""
    parser = argparse.ArgumentParser(description=summary)
    parser.add_argument(
        "--slug", action="append", required=True, help="Full registry slug"
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    return parser.parse_args()


if __name__ == "__main__":
    _args = _parse_args()
    asyncio.run(main(_args.slug, _args.runs))
