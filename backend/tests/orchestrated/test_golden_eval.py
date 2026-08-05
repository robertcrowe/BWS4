# Built with Spec4 AI - https://spec4.ai
"""The offline golden eval the specification gates release on.

Every case replays a **recorded** coordinator draft, so the whole suite runs
with no live model call, no provider key and no allowance spent. That is not a
convenience: an eval that called a model would be slow, would draw on the same
free tier the showcase runs on, and — with mid-tier free models — would be
flaky in exactly the assertions that need to be sharp. The pairing-stability
check in particular is meaningless against a live model and precise against a
fixture.

**What this can and cannot establish.** It scores the parts of the pipeline this
repository owns and that are deterministic: that a delegation is always two
distinct roster ids however the model misbehaved, that repair costs no second
call, that briefs come out distinct, that the run's arithmetic holds, that
nothing dispatches before confirmation, and that a fabricated contradiction is
dropped. It cannot establish how often a live model *chooses* the human-labelled
pairing or *notices* a planted contradiction — those are live-eval questions,
and the fixtures here record one sample of each rather than measuring a rate.
Where a criterion is stated as a percentage, what is asserted below is the
deterministic property underneath it.

The planted-contradiction stratum is **generated**, not hand-written: a
consistent pair is edited programmatically to reverse one recommendation, which
means the conflict's location is known by construction rather than by an author
remembering to label it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.orchestrated import coordinator, merge, service, validator
from backend.app.orchestrated.presets import CURATED_PRESETS
from backend.app.orchestrated.roster import ROSTER_IDS, SPECIALISTS_PER_RUN
from backend.app.orchestrated.roster import find as roster_find
from backend.app.orchestrated.runtime import (
    MAX_PROVIDER_REQUESTS,
    VISITOR_FACING_CALL_COUNT,
    RunBudget,
)
from backend.app.orchestrated.schemas import (
    ComparisonNote,
    Contradiction,
    CoordinatorDraft,
    MergedAnswer,
    SpecialistAnswer,
    SpecialistId,
    SpecialistStatus,
    SubagentResult,
)
from backend.app.services import moderation
from backend.app.services.agent_runtime import StepResult
from backend.app.services.moderation import ModerationCategory, ModerationVerdict

GOLDEN_DIR = Path(__file__).parent / "golden"


def _load_cases() -> list[dict[str, Any]]:
    """Load the delegation cases, validating each draft against the live schema.

    The defence against fixture drift, and the reason it runs at import: a
    hand-authored draft that no longer matches `CoordinatorDraft` would
    otherwise let this suite pass while the real system failed.
    """
    cases: list[dict[str, Any]] = json.loads(
        (GOLDEN_DIR / "delegation_cases.json").read_text()
    )["cases"]
    for case in cases:
        CoordinatorDraft.model_validate(case["coordinator_draft"])
    return cases


CASES = _load_cases()
PRESET_CASES = [case for case in CASES if case["kind"] == "preset"]

ALLOWED = ModerationVerdict(
    allowed=True, category=ModerationCategory.OK, visitor_message="fine"
)


class _Session:
    """Fake session holding allowance holds by key."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.holds: dict[str, object] = {}

    async def execute(self, statement: Any, *_a: object, **_k: object) -> object:
        try:
            params = list(statement.compile().params.values())
        except Exception:  # noqa: BLE001 - fake session, best effort
            params = []
        key = params[0] if params else None
        found = self.holds.get(key) if key else None

        class _Result:
            def scalar_one_or_none(self) -> object:
                return found

        return _Result()

    def add(self, obj: object) -> None:
        self.added.append(obj)
        hold_key = getattr(obj, "hold_key", None)
        if hold_key is not None:
            self.holds[hold_key] = obj

    async def commit(self) -> None:
        pass


class _RecordedCoordinator:
    """Replays one recorded draft and counts how many times it was asked."""

    def __init__(self, draft: CoordinatorDraft) -> None:
        self._draft = draft
        self.calls = 0

    async def __call__(
        self, question: str, *, budget: RunBudget
    ) -> StepResult[CoordinatorDraft]:
        self.calls += 1
        budget.spend()
        return StepResult(output=self._draft, model="recorded-fixture", requests=1)


class _RecordedSpecialists:
    """Answers every specialist from a fixture, counting dispatches."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(
        self,
        specialist_id: SpecialistId,
        brief: str,
        question: str,
        budget: RunBudget,
    ) -> StepResult[SpecialistAnswer]:
        self.calls.append(specialist_id.value)
        budget.spend()
        # A real specialist always awaits a provider round trip. Without a
        # yield point here the first branch would run to completion before the
        # second started, which is not how the code behaves in production and
        # would make the event-ordering assertion below meaningless.
        await asyncio.sleep(0.01)
        return StepResult(
            output=SpecialistAnswer(
                answer=f"{specialist_id.value} answered its brief.",
                key_points=[f"{specialist_id.value} point {n}" for n in range(1, 4)],
            ),
            model="recorded-fixture",
            requests=1,
        )


async def _stub_merge(
    *, question: str, decision: object, results: list[SubagentResult], budget: RunBudget
) -> tuple[MergedAnswer, dict[str, object]]:
    """A recorded synthesis turn that charges the run's last request."""
    budget.spend()
    return (
        MergedAnswer(
            text="One integrated answer organised by the question's sub-issues.",
            sources_used=[result.specialist_id for result in results if result.ok],
        ),
        {"recorded": True},
    )


def _question_for(case: dict[str, Any]) -> str:
    if case["kind"] == "preset":
        preset = next(p for p in CURATED_PRESETS if p.preset_id == case["preset_id"])
        return str(preset.question)
    return str(case["question"])


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    """Replay one golden case through the real pipeline, end to end."""
    session: Any = _Session()
    draft = CoordinatorDraft.model_validate(case["coordinator_draft"])
    agent = _RecordedCoordinator(draft)
    specialists = _RecordedSpecialists()
    question = _question_for(case)
    preset_id = case.get("preset_id")

    async def go() -> dict[str, Any]:
        with patch.object(coordinator, "decide", agent):
            outcome = await service.begin_run(
                session,
                question=question,
                preset_id=preset_id,
                moderate=_always_allowed,
            )

        # Nothing has been dispatched at this point, and that is asserted
        # rather than assumed -- it is the capability's own criterion.
        dispatched_before_confirmation = list(specialists.calls)

        events: list[service.DispatchEvent] = []
        if outcome.ready and outcome.decision is not None:
            budget = RunBudget(used=1)
            async for event in service.confirm_dispatch(
                session,
                decision_id=outcome.decision_id,
                decision=outcome.decision,
                question=question,
                budget=budget,
                runner=specialists,
                synthesiser=_stub_merge,
            ):
                events.append(event)
            return {
                "outcome": outcome,
                "events": events,
                "budget": budget,
                "coordinator_calls": agent.calls,
                "specialist_calls": specialists.calls,
                "before_confirmation": dispatched_before_confirmation,
            }
        raise AssertionError(f"case {case['id']} did not produce a decision")

    return asyncio.run(go())


async def _always_allowed(text: str, context: str) -> ModerationVerdict:
    return ALLOWED


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
class TestEveryGoldenCase:
    def test_selects_exactly_two_distinct_roster_specialists(
        self, case: dict[str, Any]
    ) -> None:
        """Zero tolerance: 100% of runs, however the model behaved."""
        result = _run_case(case)
        chosen = result["outcome"].decision.chosen_specialists

        assert len(chosen) == SPECIALISTS_PER_RUN == 2
        assert len(set(chosen)) == 2
        assert {item.value for item in chosen} <= ROSTER_IDS

    def test_costs_exactly_one_coordinator_call(self, case: dict[str, Any]) -> None:
        """Repair is deterministic, so a malformed decision costs nothing extra.

        This is the assertion the adversarial cases exist for: three of them
        record a model that misbehaved, and none of them buys a second call.
        """
        result = _run_case(case)
        assert result["coordinator_calls"] == 1

    def test_writes_two_distinct_briefs(self, case: dict[str, Any]) -> None:
        """Two near-identical briefs make the columns redundant.

        Distinctness is the property that always holds. The *score* falling
        below the threshold is asserted separately, over the cases where the
        coordinator behaved — see `TestBriefDistinctness`.
        """
        briefs = result_briefs(_run_case(case))

        assert len(briefs) == 2
        assert briefs[0].strip() != briefs[1].strip()

    def test_issues_no_specialist_request_before_confirmation(
        self, case: dict[str, Any]
    ) -> None:
        """The gate, as an integration assertion rather than a reading of the code."""
        result = _run_case(case)
        assert result["before_confirmation"] == []

    def test_holds_the_run_to_its_call_budget(self, case: dict[str, Any]) -> None:
        """Three visitor-facing calls, four provider requests, never more."""
        result = _run_case(case)
        budget = result["budget"]

        assert len(result["specialist_calls"]) == 2
        assert budget.used <= MAX_PROVIDER_REQUESTS
        assert budget.ceiling == MAX_PROVIDER_REQUESTS
        assert VISITOR_FACING_CALL_COUNT == 3

    def test_streams_the_expected_event_sequence(self, case: dict[str, Any]) -> None:
        """A complete run: two statuses, two answers, the fan-out, the merge."""
        names = [event.name for event in _run_case(case)["events"]]

        assert names == [
            "specialist_status",
            "specialist_status",
            "specialist_answer",
            "specialist_answer",
            "fan_out_complete",
            "merged_answer",
        ]


def result_briefs(result: dict[str, Any]) -> list[str]:
    """The two brief texts a replayed case produced."""
    return [brief.instruction for brief in result["outcome"].decision.briefs]


class TestBriefDistinctness:
    """The online guard: wording overlap below the threshold on a good draft.

    Scoped to the cases where the coordinator returned two genuinely different
    briefs — which is every case except the one that records a model returning
    two identical ones. That case is repaired rather than rejected, and what
    repair guarantees is distinctness, not a particular score.
    """

    WELL_FORMED = [c for c in CASES if c["id"] != "adversarial-duplicate-brief"]

    @pytest.mark.parametrize("case", WELL_FORMED, ids=[c["id"] for c in WELL_FORMED])
    def test_overlap_stays_below_the_threshold(self, case: dict[str, Any]) -> None:
        briefs = result_briefs(_run_case(case))
        assert validator.jaccard(*briefs) < validator.JACCARD_THRESHOLD


class TestThePresetKey:
    @pytest.mark.parametrize("case", PRESET_CASES, ids=[c["id"] for c in PRESET_CASES])
    def test_matches_the_human_labelled_pairing(self, case: dict[str, Any]) -> None:
        """Scores the recorded choice against the offline key.

        A fixture, so this measures the *pipeline* preserving the coordinator's
        choice rather than a live model's hit rate — repair must not quietly
        substitute a different specialist when the draft was already valid.
        """
        result = _run_case(case)
        chosen = sorted(
            item.value for item in result["outcome"].decision.chosen_specialists
        )

        assert chosen == sorted(case["expected_pairing"])

    def test_the_preset_set_spans_at_least_four_distinct_pairings(self) -> None:
        """A coordinator returning the same pair every time would be useless.

        Checked against the *key*, so the preset set itself is what has to stay
        diverse — this catches a preset edited into a duplicate pairing, which
        would quietly reduce what the demo can show.
        """
        pairings = {tuple(sorted(case["expected_pairing"])) for case in PRESET_CASES}
        assert len(pairings) >= 4

    def test_every_specialist_appears_in_more_than_one_preset(self) -> None:
        """A coordinator ignoring one specialist should show up as a pattern."""
        counts = {sid: 0 for sid in ROSTER_IDS}
        for case in PRESET_CASES:
            for sid in case["expected_pairing"]:
                counts[sid] += 1

        assert all(count >= 2 for count in counts.values()), counts

    @pytest.mark.parametrize("case", PRESET_CASES, ids=[c["id"] for c in PRESET_CASES])
    def test_the_pairing_is_stable_across_repeated_runs(
        self, case: dict[str, Any]
    ) -> None:
        """The same fixture must produce the same pairing every time.

        What this proves is that nothing in the pipeline is non-deterministic —
        no clock, no ordering that depends on a set's iteration order, no
        randomised tie-break in the fallback pairing. A live-model stability
        rate is a different measurement and is not attempted here.
        """
        first = _run_case(case)["outcome"].decision.chosen_specialists
        second = _run_case(case)["outcome"].decision.chosen_specialists

        assert first == second


class TestRepairFiredWhereItShould:
    def test_a_three_selection_draft_is_trimmed_to_two(self) -> None:
        case = next(c for c in CASES if c["id"] == "adversarial-three-selections")
        result = _run_case(case)

        assert len(result["outcome"].decision.chosen_specialists) == 2
        assert result["coordinator_calls"] == 1  # trimmed, not re-requested

    def test_duplicate_briefs_gain_their_exclusion_clauses(self) -> None:
        """The specified remedy is appending the clauses, not re-prompting.

        Worth stating plainly because it is counterintuitive: appending each
        specialist's angle-exclusion clause makes the two briefs *different*
        and steers the specialists apart, but it does **not** drive the overlap
        score below the threshold — the identical body they started with still
        dominates the token set. Measured at 0.58 on this case. The score is
        reported in the run summary so an operator can see it; the repair is
        what the capability asks for, and re-prompting to chase the number
        would cost a provider request the run does not have.
        """
        case = next(c for c in CASES if c["id"] == "adversarial-duplicate-brief")
        result = _run_case(case)
        briefs = result_briefs(result)

        assert briefs[0] != briefs[1]
        assert result["coordinator_calls"] == 1  # repaired, not re-requested

        # Each brief now carries its own specialist's exclusion clause.
        for brief in result["outcome"].decision.briefs:
            entry = roster_find(brief.specialist_id.value)
            assert entry is not None
            assert entry.angle_exclusion in brief.instruction

    def test_a_weak_fit_is_reported_rather_than_hidden(self) -> None:
        case = next(c for c in CASES if c["id"] == "freeform-weak-fit")
        decision = _run_case(case)["outcome"].decision

        assert validator.is_weak_fit(decision)

    def test_an_off_roster_request_cannot_produce_an_off_roster_id(self) -> None:
        """The enum, not the prompt, is what makes this impossible."""
        case = next(c for c in CASES if c["id"] == "adversarial-off-roster")
        chosen = _run_case(case)["outcome"].decision.chosen_specialists

        assert {item.value for item in chosen} <= ROSTER_IDS
        with pytest.raises(ValueError):
            SpecialistId("legal")


class TestTheModerationGate:
    """Every curated preset and light paraphrase must reach the classifier.

    What is asserted offline is the deterministic half: `moderation.py`
    short-circuits malformed input *before* any network call, and a preset
    caught by that short-circuit would be refused without anything examining
    it. Presets skip the gate entirely by design, so this matters most for the
    paraphrases a visitor would actually type. The classifier's own verdict
    needs a live call and is not asserted here.
    """

    PARAPHRASES = [
        "should a small team run its own database server?",
        "Is picking up a second programming language worth it mid-career?",
        "why did everyone move to microservices, and was it a good idea",
        "how do i start a compost bin in a flat with no garden?",
        "Are rooftop solar panels worth the money for a normal house?",
        "should companies make people come back into the office?",
    ]

    @pytest.mark.parametrize("preset", CURATED_PRESETS, ids=lambda p: p.preset_id)
    def test_no_curated_preset_is_refused_before_the_classifier(
        self, preset: Any
    ) -> None:
        # A preset caught here would break the demo's primary path, which is
        # why this gate blocks merge.
        assert not moderation._is_malformed(preset.question, moderation.MAX_TEXT_CHARS)

    @pytest.mark.parametrize("text", PARAPHRASES)
    def test_no_light_paraphrase_is_refused_before_the_classifier(
        self, text: str
    ) -> None:
        assert not moderation._is_malformed(text, moderation.MAX_TEXT_CHARS)

    def test_the_short_circuit_still_catches_what_it_is_for(self) -> None:
        """A gate that passed everything would make the tests above vacuous."""
        for junk in ("", "   ", "?!?!?!", "https://example.com", "zzz bbb"):
            assert moderation._is_malformed(junk, moderation.MAX_TEXT_CHARS)


# --------------------------------------------------------------------------
# The disagreement-note strata
# --------------------------------------------------------------------------

CONSISTENT_PAIR = {
    SpecialistId.TECHNICAL: (
        "A read replica isolates report queries from transactional traffic, and "
        "you should move the reporting workload onto one before the next peak."
    ),
    SpecialistId.FINANCIAL: (
        "A replica adds roughly the price of the primary again, which pays for "
        "itself against a single outage, so the spend is justified."
    ),
}

DISJOINT_PAIR = {
    SpecialistId.HISTORICAL: (
        "Reporting replicas became common once asynchronous replication was "
        "reliable enough to trust in production."
    ),
    SpecialistId.PRACTICAL: (
        "Start by pointing one dashboard at the replica and watch replication "
        "lag for a week before moving anything else."
    ),
}


def _plant_contradiction(
    pair: dict[SpecialistId, str],
) -> tuple[dict[SpecialistId, str], Contradiction]:
    """Reverse one answer's recommendation, yielding a known-location conflict.

    Generated rather than hand-written, per the phase's own instruction: editing
    a consistent pair programmatically means the conflict's location is known by
    construction, so the label cannot drift from the text it describes.

    Args:
        pair: A consistent answer pair.

    Returns:
        The edited pair and the contradiction that should be found in it.
    """
    left, right = list(pair)
    reversed_claim = "you should not move the reporting workload onto one"
    edited: dict[Any, Any] = dict(pair)
    edited[left] = pair[left].replace(
        "you should move the reporting workload onto one", reversed_claim
    )
    return edited, Contradiction(
        claim_a=reversed_claim,
        claim_b="the spend is justified",
        specialist_a=left,
        specialist_b=right,
    )


def _results_from(pair: dict[SpecialistId, str]) -> list[SubagentResult]:
    return [
        SubagentResult(
            specialist_id=specialist_id, status=SpecialistStatus.OK, answer=text
        )
        for specialist_id, text in pair.items()
    ]


def _synthesis(contradictions: list[Contradiction]) -> MergedAnswer:
    return MergedAnswer(
        disagreement_note=ComparisonNote(
            summary="One frames the mechanism, the other prices it.",
            agreements=["Contention is the underlying problem"],
            complements=["Technical supplied mechanism, Financial supplied cost"],
            contradictions=contradictions,
            comparable=True,
        ),
        text="One integrated answer.",
        sources_used=list(CONSISTENT_PAIR),
    )


class TestTheDisagreementStrata:
    def test_a_planted_contradiction_survives_the_traceability_check(self) -> None:
        """Recall: a real conflict, quoted from the answers, must be kept."""
        edited, planted = _plant_contradiction(CONSISTENT_PAIR)
        cleaned, telemetry = merge.check_merge(
            _synthesis([planted]), _results_from(edited)
        )

        assert len(cleaned.disagreement_note.contradictions) == 1
        assert telemetry["contradictions_dropped"] == 0

    def test_a_consistent_pair_reports_no_contradiction(self) -> None:
        """False-positive control: nothing invented where nothing conflicts."""
        cleaned, telemetry = merge.check_merge(
            _synthesis([]), _results_from(CONSISTENT_PAIR)
        )

        assert cleaned.disagreement_note.contradictions == []
        assert telemetry["contradictions"] == 0

    def test_an_invented_contradiction_on_a_consistent_pair_is_dropped(self) -> None:
        """The stratum that matters: a model reaching for a conflict finds none."""
        invented = Contradiction(
            claim_a="never use a replica under any circumstances",
            claim_b="always use a replica regardless of cost",
            specialist_a=SpecialistId.TECHNICAL,
            specialist_b=SpecialistId.FINANCIAL,
        )
        cleaned, telemetry = merge.check_merge(
            _synthesis([invented]), _results_from(CONSISTENT_PAIR)
        )

        assert cleaned.disagreement_note.contradictions == []
        assert telemetry["contradictions_dropped"] == 1

    def test_a_disjoint_pair_reports_no_contradiction(self) -> None:
        """Different sub-topics are not a conflict — they are the design."""
        answer = MergedAnswer(
            disagreement_note=ComparisonNote(
                summary="One supplies the background, the other the first step.",
                complements=[
                    "Historical supplied precedent, Practical supplied the step"
                ],
                contradictions=[],
                comparable=True,
            ),
            text="One integrated answer.",
            sources_used=list(DISJOINT_PAIR),
        )
        cleaned, telemetry = merge.check_merge(answer, _results_from(DISJOINT_PAIR))

        assert cleaned.disagreement_note.contradictions == []
        assert telemetry["contradictions"] == 0

    def test_the_planted_edit_actually_changed_the_answer(self) -> None:
        """Guards the generator: an edit that silently no-opped would make the
        recall assertion above pass against an unmodified consistent pair."""
        edited, _ = _plant_contradiction(CONSISTENT_PAIR)

        assert edited != CONSISTENT_PAIR
        assert "should not move" in edited[SpecialistId.TECHNICAL]


class TestTheEvalIsOffline:
    def test_no_case_can_reach_a_provider(self) -> None:
        """The whole point: replayed fixtures, zero allowance spent.

        Asserted by running every case with the lane's model factory replaced
        by something that raises — if any path reached it, the suite would fail
        loudly rather than quietly spending a request.
        """
        from backend.app.services import agent_runtime

        def refuse(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("a golden case reached the live provider")

        with patch.object(agent_runtime, "build_fallback_model", refuse):
            for case in CASES:
                _run_case(case)

    def test_the_two_exhaustion_outcomes_stay_distinct(self) -> None:
        """The server half of the two-messages rule the frontend also pins."""
        assert service.Outcome.USAGE_LIMIT_REACHED.value == "usage_limit_reached"
        assert (
            service.Outcome.USAGE_LIMIT_REACHED  # type: ignore[comparison-overlap]  # distinctness is the assertion: two enum members given the same value would alias at runtime
            is not service.Outcome.SPECIALISTS_FAILED
        )
        assert len({item.value for item in service.Outcome}) == len(
            list(service.Outcome)
        )
