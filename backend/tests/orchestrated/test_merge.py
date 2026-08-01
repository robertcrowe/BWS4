# Built with Spec4 AI - https://spec4.ai
"""The fan-in: one call, honest contradictions, and a run that ends within budget.

Four properties this file exists to pin, each of which a plausible change would
break without any other test noticing:

1. **The disagreement note costs no model call.** The intuitive implementation
   is a second call to compare the two answers, and it would take the run to
   four visitor-facing calls to say something the merge already had to decide.
   Every test here counts requests.
2. **A fabricated contradiction never reaches the visitor.** Manufactured
   disagreement is the capability's highest-rated failure and the one a schema
   cannot prevent, since an invented conflict is perfectly well-formed. The
   check is a lookup: an invented quote is not in the source answer.
3. **Degraded mode is an application override, not a prompt hope.** A model
   handed one answer and asked for a comparison will sometimes write one, so
   the list fields are discarded rather than inspected.
4. **A synthesis failure does not discard the columns.** Three provider
   requests have already been spent by then.

`test_golden_merge_cases` runs the deterministic checks over hand-authored
fixtures, following the planning app's golden pattern -- including its most
important property, that the fixtures are validated against the *production*
schema at collection time, so a fixture that drifts fails loudly instead of
passing while the live system breaks.

Nothing here contacts a provider or a database.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.orchestrated import merge, service, validator
from backend.app.orchestrated.runtime import (
    MAX_PROVIDER_REQUESTS,
    VISITOR_FACING_CALL_COUNT,
    RunBudget,
)
from backend.app.orchestrated.schemas import (
    Brief,
    ComparisonNote,
    Contradiction,
    DelegationDecision,
    FitQuality,
    MergedAnswer,
    SpecialistId,
    SpecialistStatus,
    SubagentResult,
)
from backend.app.services.agent_runtime import AgentLaneError, StepResult

GOLDEN = Path(__file__).parent / "golden" / "merge_cases.json"

QUESTION = "Should we move our reporting workload off the primary database?"

# Long enough to exceed MAX_VERBATIM_RUN_TOKENS when copied wholesale, which is
# what the concatenation test needs to distinguish a lifted run from a quotation.
TECHNICAL_ANSWER = (
    "Running reports against the primary database competes with transactional "
    "traffic for buffer pool and locks, because both workloads draw on the same "
    "finite resources at the same time. A read replica isolates that contention, "
    "since replication applies changes asynchronously and a long analytical scan "
    "on the replica cannot take a lock the primary needs."
)
FINANCIAL_ANSWER = (
    "A managed read replica roughly doubles the database line on the bill, "
    "landing near 380 dollars a month for a mid-sized instance."
)


def _decision() -> DelegationDecision:
    return DelegationDecision(
        chosen_specialists=[SpecialistId.TECHNICAL, SpecialistId.FINANCIAL],
        rationale="Mechanism and cost are the two live questions here.",
        briefs=[
            Brief(
                specialist_id=SpecialistId.TECHNICAL,
                instruction="Cover the mechanism, leave cost to the financial analyst.",
            ),
            Brief(
                specialist_id=SpecialistId.FINANCIAL,
                instruction="Cover the cost, leave mechanism to the technical analyst.",
            ),
        ],
        fit_quality=FitQuality.STRONG,
    )


def _results(*, financial_ok: bool = True) -> list[SubagentResult]:
    return [
        SubagentResult(
            specialist_id=SpecialistId.TECHNICAL,
            status=SpecialistStatus.OK,
            answer=TECHNICAL_ANSWER,
            key_points=["Contention is the problem"],
        ),
        SubagentResult(
            specialist_id=SpecialistId.FINANCIAL,
            status=SpecialistStatus.OK if financial_ok else SpecialistStatus.FAILED,
            answer=FINANCIAL_ANSWER if financial_ok else "",
            key_points=["Roughly double the bill"] if financial_ok else [],
            error=None if financial_ok else "This specialist couldn't be reached.",
        ),
    ]


class _Synth:
    """A stubbed synthesis turn that counts requests and records temperatures."""

    def __init__(
        self,
        *answers: MergedAnswer | Exception,
    ) -> None:
        self._queue = list(answers)
        self.calls = 0
        self.temperatures: list[float | None] = []

    async def __call__(self, **kwargs: object) -> StepResult[MergedAnswer]:
        self.calls += 1
        settings = kwargs.get("model_settings")
        self.temperatures.append(
            settings.get("temperature") if settings else None  # type: ignore[union-attr]
        )
        budget = kwargs["budget"]
        budget.spend()  # type: ignore[attr-defined]

        item = self._queue.pop(0) if self._queue else self._queue[-1]
        if isinstance(item, Exception):
            raise item
        return StepResult(output=item, model="test-model", requests=1)


def _answer(
    *,
    summary: str = "One supplied the mechanism, the other priced it at roughly double.",
    contradictions: list[Contradiction] | None = None,
    text: str = "Separating the workloads is worth it, and the cost is known.",
    agreements: list[str] | None = None,
) -> MergedAnswer:
    return MergedAnswer(
        disagreement_note=ComparisonNote(
            summary=summary,
            agreements=agreements if agreements is not None else ["Contention is real"],
            complements=["Technical supplied mechanism, Financial supplied cost"],
            contradictions=contradictions or [],
            comparable=True,
        ),
        text=text,
        sources_used=[SpecialistId.TECHNICAL, SpecialistId.FINANCIAL],
    )


def _run(
    synth: _Synth,
    *,
    budget: RunBudget | None = None,
    results: list[SubagentResult] | None = None,
) -> tuple[MergedAnswer, dict[str, object]]:
    async def go() -> tuple[MergedAnswer, dict[str, object]]:
        with patch.object(merge, "run_agent_step", synth):
            return await merge.synthesise(
                question=QUESTION,
                decision=_decision(),
                results=results if results is not None else _results(),
                budget=budget
                if budget is not None
                else RunBudget(used=MAX_PROVIDER_REQUESTS - 2),
            )

    return asyncio.run(go())


class TestTheCallCount:
    def test_a_complete_run_stays_inside_the_ceiling(self) -> None:
        """The run's whole arithmetic, asserted end to end.

        Six spent before the merge is the worst case the fan-out can leave:
        the delegation and both specialists each taking their full allowance.
        The merge's own reserve still fits on top.
        """
        budget = RunBudget(used=MAX_PROVIDER_REQUESTS - service.SYNTHESIS_RESERVE)
        synth = _Synth(_answer())

        _run(synth, budget=budget)

        assert budget.used <= MAX_PROVIDER_REQUESTS == 8

    def test_the_disagreement_note_costs_no_extra_call(self) -> None:
        """The note rides on the synthesis response, which is the entire point.

        A second call to compare the answers would take the run to four
        visitor-facing calls to produce something the merge already decided.
        """
        synth = _Synth(
            _answer(
                contradictions=[
                    Contradiction(
                        claim_a="A read replica isolates that contention",
                        claim_b="roughly doubles the database line on the bill",
                        specialist_a=SpecialistId.TECHNICAL,
                        specialist_b=SpecialistId.FINANCIAL,
                    )
                ]
            )
        )

        merged, _ = _run(synth)

        assert synth.calls == 1
        assert merged.disagreement_note.summary  # the note came from that one call
        assert merged.disagreement_note.contradictions

    def test_the_visitor_facing_count_stays_three(self) -> None:
        """It counts logical calls, not the framework's re-prompts."""
        assert VISITOR_FACING_CALL_COUNT == 3
        assert MAX_PROVIDER_REQUESTS > VISITOR_FACING_CALL_COUNT

    def test_the_synthesis_runs_at_the_specified_temperature(self) -> None:
        synth = _Synth(_answer())
        _run(synth)
        assert synth.temperatures == [merge.MERGE_TEMPERATURE]


class TestClaimTraceability:
    def test_a_fabricated_contradiction_is_dropped(self) -> None:
        """Neither quote appears in the answer it is attributed to."""
        synth = _Synth(
            _answer(
                contradictions=[
                    Contradiction(
                        claim_a="rooftop solar is rarely worth it",
                        claim_b="every homeowner should install panels immediately",
                        specialist_a=SpecialistId.TECHNICAL,
                        specialist_b=SpecialistId.FINANCIAL,
                    )
                ]
            )
        )

        merged, telemetry = _run(synth)

        assert merged.disagreement_note.contradictions == []
        assert telemetry["contradictions_dropped"] == 1

    def test_a_genuine_contradiction_survives(self) -> None:
        """A check that dropped everything would score perfectly and be useless."""
        synth = _Synth(
            _answer(
                contradictions=[
                    Contradiction(
                        claim_a="A read replica isolates that contention",
                        claim_b="roughly doubles the database line on the bill",
                        specialist_a=SpecialistId.TECHNICAL,
                        specialist_b=SpecialistId.FINANCIAL,
                    )
                ]
            )
        )

        merged, telemetry = _run(synth)

        assert len(merged.disagreement_note.contradictions) == 1
        assert telemetry["contradictions_dropped"] == 0

    def test_attribution_to_a_specialist_that_did_not_run_is_dropped(self) -> None:
        """The enum permits four ids; only the run knows which two are legal."""
        synth = _Synth(
            _answer(
                contradictions=[
                    Contradiction(
                        claim_a="A read replica isolates that contention",
                        claim_b="anything at all",
                        specialist_a=SpecialistId.TECHNICAL,
                        specialist_b=SpecialistId.HISTORICAL,
                    )
                ]
            )
        )

        merged, telemetry = _run(synth)

        assert merged.disagreement_note.contradictions == []
        assert telemetry["contradictions_dropped"] == 1

    def test_a_contradiction_with_itself_is_dropped(self) -> None:
        synth = _Synth(
            _answer(
                contradictions=[
                    Contradiction(
                        claim_a="A read replica isolates that contention",
                        claim_b="A read replica isolates that contention",
                        specialist_a=SpecialistId.TECHNICAL,
                        specialist_b=SpecialistId.TECHNICAL,
                    )
                ]
            )
        )

        merged, _ = _run(synth)

        assert merged.disagreement_note.contradictions == []

    def test_a_short_genuine_quote_is_not_dropped_for_being_short(self) -> None:
        """Fewer than three tokens has no trigrams; substring containment covers it."""
        assert validator.trigram_containment("read replica", TECHNICAL_ANSWER) == 1.0
        assert (
            validator.trigram_containment("quantum tunnelling", TECHNICAL_ANSWER) == 0.0
        )


class TestTheVerbatimRunCheck:
    def test_a_long_copied_run_is_flagged_but_not_blocked(self) -> None:
        """Refusing to show a merge over writing style would waste the whole run."""
        copied = TECHNICAL_ANSWER + " " + FINANCIAL_ANSWER
        synth = _Synth(_answer(text=copied))

        merged, telemetry = _run(synth)

        assert telemetry["verbatim_run_flagged"] is True
        assert int(telemetry["verbatim_run_tokens"]) > validator.MAX_VERBATIM_RUN_TOKENS
        assert merged.text == copied  # still shown

    def test_a_synthesised_merge_is_not_flagged(self) -> None:
        synth = _Synth(_answer())
        _, telemetry = _run(synth)
        assert telemetry["verbatim_run_flagged"] is False

    def test_the_threshold_is_the_one_the_capability_names(self) -> None:
        assert validator.MAX_VERBATIM_RUN_TOKENS == 30
        assert validator.CLAIM_TRACEABILITY_THRESHOLD == 0.6


class TestTheBannedPhraseLint:
    def test_a_vacuous_summary_triggers_exactly_one_retry(self) -> None:
        """One regeneration, never two -- the retries share a single budget."""
        vacuous = _answer(
            summary="Both specialists broadly agree and offer complementary views."
        )
        synth = _Synth(vacuous, vacuous, vacuous)
        budget = RunBudget(ceiling=12, used=3)

        _, telemetry = _run(synth, budget=budget)

        assert synth.calls == 2  # the original and one retry
        assert telemetry["retries"] == 1
        assert synth.temperatures == [merge.MERGE_TEMPERATURE, merge.RETRY_TEMPERATURE]

    def test_a_retry_is_refused_when_the_ceiling_has_no_room(self) -> None:
        """At the shipped budget this is the correct answer, not a defect.

        Delegation and both specialists have already spent three of four, so the
        synthesis itself takes the last one. A regeneration would be a fifth
        provider request, which the capability's own hard counter forbids.
        """
        vacuous = _answer(summary="Both specialists broadly agree.")
        synth = _Synth(vacuous, vacuous)
        budget = RunBudget(used=MAX_PROVIDER_REQUESTS - 1)

        merged, telemetry = _run(synth, budget=budget)

        assert synth.calls == 1
        assert telemetry["retries"] == 0
        assert budget.used == MAX_PROVIDER_REQUESTS
        # The bland summary is still shown; it is not grounds to lose the merge.
        assert merged.text

    def test_a_clean_summary_triggers_no_retry(self) -> None:
        synth = _Synth(_answer())
        budget = RunBudget(ceiling=12, used=3)

        _, telemetry = _run(synth, budget=budget)

        assert synth.calls == 1
        assert telemetry["retries"] == 0

    def test_the_banned_list_is_the_capability_s_own(self) -> None:
        assert set(validator.BANNED_SUMMARY_PHRASES) == {
            "complementary perspectives",
            "broadly agree",
            "both provide valuable",
        }


class TestDegradedMode:
    def test_only_one_answer_forces_comparability_false(self) -> None:
        """An application override, so a hallucination cannot reach the screen."""
        synth = _Synth(
            _answer(
                summary="The two answers diverge sharply on cost.",
                agreements=["They agree on the mechanism"],
                contradictions=[
                    Contradiction(
                        claim_a="A read replica isolates that contention",
                        claim_b="invented",
                        specialist_a=SpecialistId.TECHNICAL,
                        specialist_b=SpecialistId.FINANCIAL,
                    )
                ],
            )
        )

        merged, telemetry = _run(synth, results=_results(financial_ok=False))
        note = merged.disagreement_note

        assert note.comparable is False
        assert telemetry["comparable"] is False
        # Every list the model returned is discarded, not inspected.
        assert note.agreements == []
        assert note.complements == []
        assert note.contradictions == []
        assert note.summary == merge.DEGRADED_NOTE_COPY
        assert merged.sources_used == [SpecialistId.TECHNICAL]

    def test_the_merged_text_survives_degraded_mode(self) -> None:
        """A single-angle answer is still an answer."""
        synth = _Synth(_answer(text="Here is what the one answer supports."))

        merged, _ = _run(synth, results=_results(financial_ok=False))

        assert merged.text == "Here is what the one answer supports."

    def test_both_answers_leave_the_note_alone(self) -> None:
        synth = _Synth(_answer())
        merged, _ = _run(synth)
        assert merged.disagreement_note.comparable is True
        assert merged.disagreement_note.agreements == ["Contention is real"]


class TestFailureHandling:
    def test_a_parse_failure_with_budget_retries_once_then_succeeds(self) -> None:
        synth = _Synth(AgentLaneError("coordinator-synthesis", "bad json"), _answer())
        budget = RunBudget(ceiling=12, used=3)

        merged, telemetry = _run(synth, budget=budget)

        assert synth.calls == 2
        assert telemetry["retries"] == 1
        assert merged.text

    def test_a_parse_failure_with_no_budget_raises_for_the_caller(self) -> None:
        """The caller keeps the columns on screen; it does not discard the run."""
        synth = _Synth(
            AgentLaneError("coordinator-synthesis", "bad json"),
            AgentLaneError("coordinator-synthesis", "bad json"),
        )

        with pytest.raises(AgentLaneError):
            _run(synth, budget=RunBudget(used=MAX_PROVIDER_REQUESTS - 1))

        assert synth.calls == 1

    def test_an_empty_merge_is_treated_as_a_failure_not_shown(self) -> None:
        """Found live: the schema accepts an empty answer, so nothing rejected it.

        Every field on `MergedAnswer` has a default -- which is what buys the
        no-re-prompt guarantee -- so a model returning nothing produces a valid
        object. Ending the run with a blank panel under two filled columns reads
        as the app breaking rather than as the model returning nothing.
        """
        synth = _Synth(_answer(text="   "), _answer(text="  "))

        with pytest.raises(AgentLaneError):
            _run(synth, budget=RunBudget(ceiling=12, used=3))

        assert synth.calls == 2  # retried once, then gave up

    def test_an_empty_merge_with_no_budget_fails_immediately(self) -> None:
        synth = _Synth(_answer(text=""))

        with pytest.raises(AgentLaneError):
            _run(synth, budget=RunBudget(used=MAX_PROVIDER_REQUESTS - 1))

        assert synth.calls == 1

    def test_a_degraded_run_tells_the_model_there_is_nothing_to_compare(self) -> None:
        """The prompt is written for two answers; a one-answer run must say so.

        Live, a merge asked to compare a single answer returned nothing at all.
        """
        prompts: list[str] = []

        async def capture(**kwargs: object) -> StepResult[MergedAnswer]:
            prompts.append(str(kwargs["user_prompt"]))
            budget = kwargs["budget"]
            budget.spend()  # type: ignore[attr-defined]
            return StepResult(output=_answer(), model="m", requests=1)

        async def go(results: list[SubagentResult]) -> None:
            with patch.object(merge, "run_agent_step", capture):
                await merge.synthesise(
                    question=QUESTION,
                    decision=_decision(),
                    results=results,
                    budget=RunBudget(used=MAX_PROVIDER_REQUESTS - 2),
                )

        asyncio.run(go(_results(financial_ok=False)))
        asyncio.run(go(_results()))

        assert "only one specialist answered" in prompts[0]
        assert "only one specialist answered" not in prompts[1]

    def test_the_fallback_answer_keeps_the_text_and_replaces_the_note(self) -> None:
        """Instruction 11's second half: surface the merge, replace the panel."""
        fallback = merge.fallback_answer("raw merged text", _results())

        assert fallback.text == "raw merged text"
        assert fallback.disagreement_note.summary == merge.FALLBACK_NOTE_COPY
        assert fallback.disagreement_note.comparable is False
        assert fallback.disagreement_note.contradictions == []

    def test_the_fallback_and_degraded_copy_are_different_strings(self) -> None:
        """'Nothing to compare' and 'the comparison broke' are different facts."""
        assert merge.FALLBACK_NOTE_COPY != merge.DEGRADED_NOTE_COPY


class TestTrimming:
    def test_lists_are_truncated_rather_than_re_prompted(self) -> None:
        note = ComparisonNote(
            summary="fine",
            agreements=[f"a{n}" for n in range(9)],
            complements=[f"c{n}" for n in range(9)],
            contradictions=[Contradiction() for _ in range(9)],
        )

        trimmed = merge.trim_note(note)

        assert len(trimmed.agreements) == merge.MAX_NOTE_ITEMS == 3
        assert len(trimmed.complements) == 3
        assert len(trimmed.contradictions) == 3

    def test_an_over_long_summary_is_cut_to_the_word_cap(self) -> None:
        note = ComparisonNote(summary=" ".join(["word"] * 200))
        trimmed = merge.trim_note(note)
        # The ellipsis attaches to the last kept word rather than standing alone.
        assert len(trimmed.summary.split()) == merge.MAX_SUMMARY_WORDS
        assert trimmed.summary.endswith("…")

    def test_blank_items_are_dropped(self) -> None:
        note = ComparisonNote(summary="fine", agreements=["real", "  ", ""])
        assert merge.trim_note(note).agreements == ["real"]

    def test_sources_used_is_what_ran_not_what_the_model_claimed(self) -> None:
        """Attribution is a server fact, like `role` in the chained-calls app."""
        overclaiming = _answer()
        overclaiming.sources_used = [SpecialistId.HISTORICAL, SpecialistId.PRACTICAL]
        synth = _Synth(overclaiming)

        merged, _ = _run(synth)

        assert merged.sources_used == [SpecialistId.TECHNICAL, SpecialistId.FINANCIAL]


def _load_golden() -> list[dict]:
    """Load the golden cases, validating every fixture against the live schema.

    The whole defence against fixture drift, and the reason it runs at load
    time: hand-authored model output that no longer matches `MergedAnswer`
    would otherwise let this suite pass while the real system failed.
    """
    cases = json.loads(GOLDEN.read_text())["cases"]
    for case in cases:
        MergedAnswer.model_validate(case["synthesis"])
    return cases


GOLDEN_CASES = _load_golden()


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c["id"] for c in GOLDEN_CASES])
def test_golden_merge_cases(case: dict) -> None:
    """Run the deterministic fan-in checks over a hand-authored case.

    Assertions are tied to what the checks must *conclude*, never to fixture
    prose, so rewording a case cannot break the suite or hide a regression.
    """
    answer = MergedAnswer.model_validate(case["synthesis"])
    results = [
        SubagentResult(
            specialist_id=SpecialistId(sid),
            status=SpecialistStatus.OK,
            answer=text,
        )
        for sid, text in case["answers"].items()
    ]

    cleaned, telemetry = merge.check_merge(answer, results)
    expected = case["expect"]

    assert (
        len(cleaned.disagreement_note.contradictions) == expected["contradictions_kept"]
    )
    assert telemetry["contradictions_dropped"] == expected["contradictions_dropped"]
    assert telemetry["verbatim_run_flagged"] is expected["verbatim_run_flagged"]
    assert len(list(telemetry["banned_phrase_hits"])) == expected["banned_phrase_hits"]
    assert cleaned.disagreement_note.comparable is expected["comparable"]


def test_the_golden_set_covers_both_directions_of_the_traceability_check() -> None:
    """A suite that only planted fabrications would pass by dropping everything."""
    kept = [c for c in GOLDEN_CASES if c["expect"]["contradictions_kept"] > 0]
    dropped = [c for c in GOLDEN_CASES if c["expect"]["contradictions_dropped"] > 0]

    assert kept, "no case exercises a contradiction that must survive"
    assert dropped, "no case exercises a contradiction that must be dropped"
