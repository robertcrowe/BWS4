# Built with Spec4 AI - https://spec4.ai
"""The subagent orchestration runtime: budget ceiling and concurrent fan-out.

Two properties this file exists to pin, both of which a later phase could break
without any other test noticing:

1. The provider-request ceiling **aborts** rather than warns. A logged warning
   would let a coding error turn a three-call demo into an unbounded one against
   a shared free tier and merely mention it afterwards.
2. One failing branch does not cancel the other. That is what `return_exceptions
   =True` buys, and it is the difference between a visitor keeping the column
   that succeeded and losing both.

Nothing here contacts a provider.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.app.orchestrated import runtime
from backend.app.orchestrated.runtime import (
    MAX_PROVIDER_REQUESTS,
    VISITOR_FACING_CALL_COUNT,
    RunBudget,
    RunBudgetExceededError,
    fan_out,
)


class TestRunBudget:
    def test_the_ceiling_matches_the_run_shape(self) -> None:
        # Delegation, two specialists, and the coordinator's closing synthesis
        # turn. The moderation gate is not counted: different provider, free of
        # charge, no model allowance.
        assert MAX_PROVIDER_REQUESTS == 4

    def test_exactly_four_provider_requests_are_permitted(self) -> None:
        budget = RunBudget()

        for _ in range(MAX_PROVIDER_REQUESTS):
            budget.spend()

        assert budget.used == MAX_PROVIDER_REQUESTS
        assert budget.remaining() == 0

    def test_the_fifth_provider_request_aborts_the_run(self) -> None:
        """An exception, not a warning. This is the whole ceiling."""
        budget = RunBudget()
        for _ in range(MAX_PROVIDER_REQUESTS):
            budget.spend()

        with pytest.raises(RunBudgetExceededError):
            budget.spend()

    def test_a_refused_request_is_not_counted(self) -> None:
        # It never happened, so charging for it would make the counter lie to
        # whatever reports what the run spent.
        budget = RunBudget(ceiling=1)
        budget.spend()

        with pytest.raises(RunBudgetExceededError):
            budget.spend()

        assert budget.used == 1

    def test_the_visitor_facing_count_reads_three(self) -> None:
        """Deliberately not the enforcement ceiling.

        The merge is the coordinator's closing turn on a conversation it already
        holds, so from the visitor's side the run is one coordinator plus two
        specialists. Reporting four would count an implementation detail at
        them; enforcing three would abort a run behaving exactly as designed.
        """
        budget = RunBudget()

        assert budget.visitor_facing_count == VISITOR_FACING_CALL_COUNT == 3
        assert budget.visitor_facing_count < budget.ceiling

    def test_the_visitor_count_does_not_move_as_calls_are_spent(self) -> None:
        budget = RunBudget()
        budget.spend()
        budget.spend()

        assert budget.visitor_facing_count == 3


class TestFanOut:
    def test_both_branches_run_and_both_results_come_back(self) -> None:
        async def branch(value: str) -> str:
            await asyncio.sleep(0)
            return value

        result = asyncio.run(
            fan_out(("technical", branch("a")), ("financial", branch("b")))
        )

        statuses = [outcome.status for outcome in result.branches]
        assert statuses == ["completed", "completed"]
        assert [outcome.value for outcome in result.branches] == ["a", "b"]
        labels = [outcome.label for outcome in result.branches]
        assert labels == ["technical", "financial"]

    def test_one_branch_failing_does_not_cancel_the_other(self) -> None:
        """The reason `return_exceptions=True` is not optional.

        The survivor sleeps *past* the moment the other raises, so if the
        gather cancelled it the flag would never be set — which is what
        distinguishes "it survived" from "it happened to finish first".
        """
        finished: list[str] = []

        async def fails() -> str:
            raise RuntimeError("specialist unavailable")

        async def survives() -> str:
            await asyncio.sleep(0.05)
            finished.append("survivor ran to completion")
            return "an answer"

        result = asyncio.run(fan_out(("technical", fails()), ("financial", survives())))

        assert finished == ["survivor ran to completion"]
        assert result.branches[0].status == "failed"
        assert isinstance(result.branches[0].error, RuntimeError)
        assert result.branches[1].status == "completed"
        assert result.branches[1].value == "an answer"
        assert len(result.survivors) == 1
        assert result.all_failed is False

    def test_a_slow_branch_times_out_distinguishably_from_a_failure(self) -> None:
        """Two different things to tell a visitor, so two different statuses.

        "Still thinking" and "broke" suggest different next steps, and only one
        of them is worth retrying.
        """

        async def slow() -> str:
            await asyncio.sleep(5)
            return "never"

        async def quick() -> str:
            return "done"

        result = asyncio.run(
            fan_out(("technical", slow()), ("financial", quick()), timeout=0.05)
        )

        assert result.branches[0].status == "timed_out"
        assert result.branches[1].status == "completed"
        assert result.branches[0].status != "failed"

    def test_a_timeout_on_one_branch_does_not_bound_the_other(self) -> None:
        # The timeout is per branch, so a slow one cannot consume the other's
        # time. Both would fail if it were applied to the pair.
        async def slow() -> str:
            await asyncio.sleep(5)
            return "never"

        async def steady() -> str:
            await asyncio.sleep(0.08)
            return "made it"

        result = asyncio.run(
            fan_out(("technical", slow()), ("financial", steady()), timeout=0.3)
        )

        assert result.branches[0].status == "timed_out"
        assert result.branches[1].value == "made it"

    def test_both_failing_is_reported_as_such(self) -> None:
        async def fails(message: str) -> str:
            raise RuntimeError(message)

        result = asyncio.run(fan_out(("a", fails("x")), ("b", fails("y"))))

        assert result.all_failed is True
        assert result.survivors == []

    def test_the_branches_actually_overlap_in_time(self) -> None:
        """Concurrency, measured rather than assumed.

        Two branches that each sleep 0.1s take ~0.1s together and ~0.2s in
        sequence. Running them one after another would still return both
        results and pass every other test in this class.
        """

        async def slow_branch(value: str) -> str:
            await asyncio.sleep(0.1)
            return value

        async def timed() -> float:
            loop = asyncio.get_running_loop()
            started = loop.time()
            await fan_out(("a", slow_branch("x")), ("b", slow_branch("y")))
            return loop.time() - started

        elapsed = asyncio.run(timed())

        assert elapsed < 0.18, f"branches ran in sequence ({elapsed:.3f}s)"


class TestNoHardcodedModels:
    def test_no_model_slug_appears_anywhere_in_the_package(self) -> None:
        """Slug selection belongs to the shared registry, not to this package.

        A slug pinned here would sidestep the provider rotation and the cooldown
        bench, and would rot silently — the registry's own notes say the chains
        are expected to.
        """
        package = Path(runtime.__file__).parent
        markers = (
            "openrouter/",
            "groq/",
            "gpt-",
            "llama",
            "claude-",
            "gemini",
            "qwen",
            "mistral",
        )

        for path in package.rglob("*.py"):
            source = path.read_text(encoding="utf-8").lower()
            for marker in markers:
                assert marker not in source, (
                    f"{path.name} names a model slug: {marker!r}"
                )

    def test_the_runtime_builds_its_model_through_the_shared_lane(self) -> None:
        # The seam that keeps one model list authoritative across both apps
        # already using this lane.
        source = Path(runtime.__file__).read_text(encoding="utf-8")

        assert "agent_runtime.build_fallback_model()" in source
