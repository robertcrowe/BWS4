# Built with Spec4 AI - https://spec4.ai
"""The delegation phase: ordering, repair, budget and the run stream.

Three properties this file exists to pin, each of which a plausible refactor
would break silently:

1. **Repair never costs a model call.** The intuitive fix for a malformed
   delegation is to ask again, and doing so would spend a second request out of
   the budget the whole app exists to demonstrate. Every repair case here
   asserts the coordinator was called exactly once.
2. **The order is moderate → gate → reserve → call.** Each swap breaks
   something specific, so each is asserted rather than assumed from reading.
3. **No specialist request is issued before the visitor confirms.** An explicit
   success criterion, and the thing an "obvious" optimisation would undo.

Nothing here contacts a provider or a database.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import orchestrated as api
from backend.app.db.models import AllowanceHold, ServiceLogEntry, UsageLimit
from backend.app.main import app
from backend.app.orchestrated import coordinator, service, validator
from backend.app.orchestrated.presets import CURATED_PRESETS
from backend.app.orchestrated.roster import SPECIALIST_ROSTER_CONFIG, find
from backend.app.orchestrated.schemas import (
    Brief,
    CoordinatorDraft,
    FitQuality,
    SpecialistId,
)
from backend.app.orchestrated.service import Outcome
from backend.app.services import allowance_holds, shared
from backend.app.services.agent_runtime import AgentLaneError, StepResult
from backend.app.services.moderation import ModerationCategory, ModerationVerdict

client = TestClient(app)

PRESET = CURATED_PRESETS[0]
FREE_FORM = "Is it worth rewriting our billing service in a different language?"

ALLOWED = ModerationVerdict(
    allowed=True, category=ModerationCategory.OK, visitor_message="fine"
)
BLOCKED = ModerationVerdict(
    allowed=False, category=ModerationCategory.UNSAFE, visitor_message="Try rephrasing."
)


def _draft(
    ids: list[str],
    *,
    briefs: list[tuple[str, str]] | None = None,
    rationale: str = "These two modes suit the question.",
) -> CoordinatorDraft:
    """Build a coordinator draft, including deliberately malformed ones."""
    return CoordinatorDraft(
        chosen_specialists=[SpecialistId(value) for value in ids],
        rationale=rationale,
        briefs=[
            Brief(specialist_id=SpecialistId(sid), instruction=text)
            for sid, text in (briefs or [])
        ],
        fit_quality=FitQuality.STRONG,
    )


def _good_briefs() -> list[tuple[str, str]]:
    return [
        (
            "technical",
            "Explain the mechanism and the engineering trade-offs involved here, "
            "naming what each choice gives up. Leave the money to the financial "
            "analyst.",
        ),
        (
            "financial",
            "Put numbers on this: spend, savings, payback period, and what would "
            "have to be true for it to pay. Leave architecture to the technical "
            "analyst.",
        ),
    ]


class _Result:
    def __init__(self, scalar: object = None, rows: list[object] | None = None) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self._rows


class _Session:
    """Fake session holding one usage row per capability and holds by key."""

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.added: list[object] = []
        self.limits: dict[str, UsageLimit] = {}
        self.holds: dict[str, AllowanceHold] = {}
        self._caps = caps or {}

    async def execute(self, statement: object, *_a: object, **_k: object) -> _Result:
        try:
            params = list(statement.compile().params.values())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - fake session, best effort
            params = []
        key = params[0] if params else None

        if key in self.limits:
            return _Result(scalar=self.limits[key])
        if key in self.holds:
            return _Result(scalar=self.holds[key])
        return _Result(scalar=None)

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj
        if isinstance(obj, AllowanceHold):
            self.holds[obj.hold_key] = obj

    async def commit(self) -> None:
        pass

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def hold_states(self) -> list[str]:
        return [hold.state for hold in self.holds.values()]

    def summaries(self) -> list[str]:
        return [row.summary for row in self.added if isinstance(row, ServiceLogEntry)]


class _Coordinator:
    """Counts calls, so "exactly once" is measured rather than assumed."""

    def __init__(
        self, draft: CoordinatorDraft | None = None, raises: Exception | None = None
    ):
        self._draft = draft
        self._raises = raises
        self.calls = 0

    async def __call__(
        self, question: str, *, budget: object
    ) -> StepResult[CoordinatorDraft]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        budget.spend()  # type: ignore[attr-defined]
        assert self._draft is not None
        return StepResult(output=self._draft, model="test-model", requests=1)


def _moderator(verdict: ModerationVerdict) -> tuple[object, list[str]]:
    seen: list[str] = []

    async def moderate(text: str, calling_context: str) -> ModerationVerdict:
        seen.append(text)
        return verdict

    return moderate, seen


def _run(session: _Session, *, question: str, preset_id: str | None, moderate: object):
    return asyncio.run(
        service.begin_run(
            session, question=question, preset_id=preset_id, moderate=moderate
        )
    )


class TestOrdering:
    def test_a_curated_preset_skips_moderation_entirely(self) -> None:
        """Pre-vetted, so the gate costs nothing and needs nothing reachable."""
        session = _Session()
        moderate, seen = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert seen == [], "a curated preset must not be sent to the moderation service"
        assert outcome.outcome is Outcome.READY

    def test_a_forged_preset_id_does_not_skip_moderation(self) -> None:
        """The id is a claim, not a credential.

        Accepting it would let any text bypass the safety gate by attaching an
        id — the text must byte-match the stored question.
        """
        session = _Session()
        moderate, seen = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            _run(
                session,
                question="something else entirely",
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert seen == ["something else entirely"]

    def test_a_blocked_question_reserves_nothing_and_calls_nothing(self) -> None:
        """The order's whole point: refuse before spending anything."""
        session = _Session()
        moderate, _ = _moderator(BLOCKED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session, question=FREE_FORM, preset_id=None, moderate=moderate
            )

        assert outcome.outcome is Outcome.MODERATION_BLOCKED
        assert agent.calls == 0
        assert session.holds == {}
        assert session.limits == {}, "the usage gate must not be touched either"

    def test_the_hold_is_reserved_before_the_coordinator_is_called(self) -> None:
        """A decision must never reach the screen that the allowance cannot run."""
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        observed: dict[str, object] = {}

        draft = _draft(["technical", "financial"], briefs=_good_briefs())

        async def observing(
            question: str, *, budget: object
        ) -> StepResult[CoordinatorDraft]:
            observed["holds_at_call_time"] = list(session.holds)
            budget.spend()  # type: ignore[attr-defined]
            return StepResult(output=draft, model="test-model", requests=1)

        with patch.object(coordinator, "decide", observing):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert observed["holds_at_call_time"] == [outcome.decision_id]

    def test_an_exhausted_hourly_gate_refuses_before_reserving_or_calling(self) -> None:
        session = _Session(caps={shared.CAPABILITY_GENERATION: 0})
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert outcome.outcome is Outcome.USAGE_LIMIT_REACHED
        assert agent.calls == 0
        assert session.holds == {}

    def test_every_outcome_stays_distinguishable(self) -> None:
        # One generic error would leave a visitor unable to tell a refused
        # question from a busy showcase. Asserted as "no two share a value"
        # rather than against a count, so adding an outcome in a later phase
        # does not have to touch this test to keep meaning what it says.
        assert len({o.value for o in Outcome}) == len(list(Outcome))

        # The pairs a refactor is most likely to fold together, each of which
        # points the visitor somewhere different.
        distinct = [
            (Outcome.MODERATION_BLOCKED, Outcome.MODERATION_UNAVAILABLE),
            (Outcome.DISPATCH_UNKNOWN, Outcome.DISPATCH_EXPIRED),
            (Outcome.COORDINATOR_FAILED, Outcome.SPECIALISTS_FAILED),
        ]
        for left, right in distinct:
            assert left is not right

    def test_an_unreachable_moderation_service_is_not_reported_as_a_refusal(
        self,
    ) -> None:
        """An outage and a rejection are different things to tell someone.

        Phase 2 gave the gate a distinct `UNAVAILABLE` category precisely so a
        caller could tell them apart; collapsing it here would describe a
        question as rejected when nothing examined it. Found by a live run
        against a deployment with no moderation key.
        """
        session = _Session()
        unavailable = ModerationVerdict(
            allowed=False,
            category=ModerationCategory.UNAVAILABLE,
            visitor_message="The safety check couldn't run just now.",
        )
        moderate, _ = _moderator(unavailable)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session, question=FREE_FORM, preset_id=None, moderate=moderate
            )

        assert outcome.outcome is Outcome.MODERATION_UNAVAILABLE
        assert outcome.outcome is not Outcome.MODERATION_BLOCKED
        assert agent.calls == 0
        assert session.holds == {}


class TestExactlyOneModelCall:
    """Repair is deterministic, so every case below costs exactly one call."""

    @pytest.mark.parametrize(
        ("ids", "label"),
        [
            (["technical", "technical"], "duplicate-id"),
            (["technical"], "one-selection"),
            (["technical", "financial", "practical"], "three-selection"),
            ([], "no-selection"),
        ],
    )
    def test_each_malformed_delegation_is_repaired_without_a_second_call(
        self, ids: list[str], label: str
    ) -> None:
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(ids))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert agent.calls == 1, f"{label} triggered a re-prompt"
        assert outcome.outcome is Outcome.READY
        assert outcome.model_calls == 1
        assert outcome.decision is not None
        assert len(outcome.decision.chosen_specialists) == 2
        assert len(set(outcome.decision.chosen_specialists)) == 2

    def test_a_valid_delegation_also_costs_exactly_one_call(self) -> None:
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert agent.calls == 1
        assert outcome.model_calls == 1

    def test_the_repair_module_cannot_reach_a_provider_at_all(self) -> None:
        """Structural, not disciplinary.

        The repair path is safe from re-prompting because nothing it *imports*
        can reach a model — not because a comment asks it not to. Parsed rather
        than grepped: the module's prose necessarily mentions the coordinator,
        and a substring scan would either fail on that or be loosened until it
        stopped checking anything.
        """
        import ast
        from pathlib import Path

        tree = ast.parse(Path(validator.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        forbidden = ("agent_runtime", "coordinator", "httpx", "pydantic_ai", "openai")
        for module in imported:
            for name in forbidden:
                assert name not in module, f"validator.py imports {module}"


class TestValidatorRepair:
    """The pure core, exercised directly."""

    def test_a_valid_draft_passes_through_unrepaired(self) -> None:
        check = validator.validate_and_repair(
            _draft(["technical", "financial"], briefs=_good_briefs()),
            question=PRESET.question,
        )

        assert check.ok
        assert check.rules_fired == []

    def test_a_duplicate_selection_gains_a_distinct_partner(self) -> None:
        check = validator.validate_and_repair(
            _draft(["technical", "technical"]), question=PRESET.question
        )

        assert check.ok
        assert check.decision is not None
        assert len(set(check.decision.chosen_specialists)) == 2
        assert validator.RULE_DEDUPLICATED in check.rules_fired

    def test_three_selections_are_trimmed_to_two(self) -> None:
        check = validator.validate_and_repair(
            _draft(["technical", "financial", "practical"]), question=PRESET.question
        )

        assert check.decision is not None
        assert [s.value for s in check.decision.chosen_specialists] == [
            "technical",
            "financial",
        ]
        assert validator.RULE_TRIMMED_EXTRA in check.rules_fired

    def test_a_single_selection_is_completed_by_keyword_affinity(self) -> None:
        # "cost" and "worth" are financial affinities, so the fallback should
        # reach for the financial analyst rather than an arbitrary partner.
        check = validator.validate_and_repair(
            _draft(["technical"]),
            question="Is the cost of this worth it, and is it cheaper to buy?",
        )

        assert check.decision is not None
        assert SpecialistId.FINANCIAL in check.decision.chosen_specialists
        assert validator.RULE_FILLED_MISSING in check.rules_fired

    def test_an_off_roster_id_cannot_be_expressed(self) -> None:
        """The structural defence against a question naming a specialist.

        The enum makes an invented id unrepresentable, so this is checked at the
        schema rather than repaired after the fact.
        """
        with pytest.raises(ValueError):
            CoordinatorDraft.model_validate(
                {
                    "chosen_specialists": ["legal"],
                    "rationale": "r",
                    "briefs": [],
                    "fit_quality": "strong",
                }
            )

    def test_a_missing_brief_is_rebuilt_from_the_roster(self) -> None:
        check = validator.validate_and_repair(
            _draft(["technical", "financial"]), question=PRESET.question
        )

        assert check.decision is not None
        assert len(check.decision.briefs) == 2
        assert validator.RULE_REBUILT_BRIEFS in check.rules_fired
        assert all(brief.instruction.strip() for brief in check.decision.briefs)


class TestBriefDistinctness:
    def test_near_duplicate_briefs_get_the_angle_exclusion_clauses_appended(
        self,
    ) -> None:
        """The capability's mitigation, and it appends rather than re-prompting."""
        identical = (
            "Explain what matters about this question in a clear and useful way "
            "for the visitor reading the answer."
        )
        check = validator.validate_and_repair(
            _draft(
                ["technical", "financial"],
                briefs=[("technical", identical), ("financial", identical)],
            ),
            question=PRESET.question,
        )

        assert check.jaccard >= validator.JACCARD_THRESHOLD
        assert validator.RULE_APPENDED_EXCLUSIONS in check.rules_fired
        assert check.decision is not None
        for brief in check.decision.briefs:
            entry = find(brief.specialist_id.value)
            assert entry is not None
            assert entry.angle_exclusion in brief.instruction

    def test_distinct_briefs_are_left_alone(self) -> None:
        check = validator.validate_and_repair(
            _draft(["technical", "financial"], briefs=_good_briefs()),
            question=PRESET.question,
        )

        assert check.jaccard < validator.JACCARD_THRESHOLD
        assert validator.RULE_APPENDED_EXCLUSIONS not in check.rules_fired

    def test_the_threshold_is_the_one_the_capability_names(self) -> None:
        assert validator.JACCARD_THRESHOLD == 0.45

    def test_jaccard_is_a_set_measure(self) -> None:
        # A brief repeating one word is not thereby more distinct from its
        # partner.
        assert validator.jaccard("cost cost cost", "cost") == 1.0
        assert validator.jaccard("alpha beta", "gamma delta") == 0.0


class TestFailureRefundsTheHold:
    def test_a_coordinator_failure_refunds_rather_than_stranding_the_budget(
        self,
    ) -> None:
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(raises=AgentLaneError("coordinator", "chain exhausted"))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert outcome.outcome is Outcome.COORDINATOR_FAILED
        assert session.hold_states() == [allowance_holds.STATE_REFUNDED]
        assert allowance_holds.STATE_RESERVED not in session.hold_states()

    def test_a_successful_run_leaves_the_hold_reserved_for_dispatch(self) -> None:
        # Redeeming happens when the specialists actually run, which is a later
        # phase. Until then the budget stays claimed.
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            outcome = _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert session.hold_states() == [allowance_holds.STATE_RESERVED]
        assert outcome.hold_key == outcome.decision_id


class TestPersistence:
    def test_the_log_line_carries_no_question_text(self) -> None:
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with patch.object(coordinator, "decide", agent):
            _run(
                session,
                question=PRESET.question,
                preset_id=PRESET.preset_id,
                moderate=moderate,
            )

        assert session.summaries()
        for summary in session.summaries():
            assert PRESET.question not in summary
            assert "self-host" not in summary


class TestRunStream:
    def _stream(self, body: dict) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        pending: str | None = None

        with client.stream("POST", "/api/orchestrated/run", json=body) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line.startswith("event:"):
                    pending = line.removeprefix("event:").strip()
                elif line.startswith("data:") and pending is not None:
                    events.append(
                        (pending, json.loads(line.removeprefix("data:").strip()))
                    )
                    pending = None
        return events

    def test_it_emits_exactly_one_delegation_event_then_closes(self) -> None:
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))

        with (
            patch.object(api, "async_session_factory", lambda: session),
            patch.object(coordinator, "decide", agent),
        ):
            events = self._stream(
                {"question": PRESET.question, "preset_id": PRESET.preset_id}
            )

        assert [name for name, _ in events] == ["delegation"]
        payload = events[0][1]
        assert len(payload["chosen_specialists"]) == 2
        assert len(set(payload["chosen_specialists"])) == 2
        assert set(payload["chosen_specialists"]) <= {
            entry.id for entry in SPECIALIST_ROSTER_CONFIG
        }
        assert payload["rationale"]
        assert len(payload["briefs"]) == 2
        assert payload["model_call_count"] == 3

    def test_zero_specialist_requests_are_issued_during_this_phase(self) -> None:
        """An explicit success criterion: dispatch waits for the visitor.

        Counted at the lane boundary, so *any* provider request beyond the
        single coordinator call would be caught — not only one that happened to
        be labelled "specialist".
        """
        session = _Session()
        moderate, _ = _moderator(ALLOWED)
        agent = _Coordinator(_draft(["technical", "financial"], briefs=_good_briefs()))
        lane_calls: list[str] = []

        async def counting_step(**kwargs: object) -> StepResult[CoordinatorDraft]:
            lane_calls.append(str(kwargs.get("label")))
            raise AssertionError("unreachable in this test")

        with (
            patch.object(api, "async_session_factory", lambda: session),
            patch.object(coordinator, "decide", agent),
            patch("backend.app.orchestrated.runtime.run_agent_step", counting_step),
        ):
            self._stream({"question": PRESET.question, "preset_id": PRESET.preset_id})

        assert agent.calls == 1, "exactly one coordinator call"
        assert lane_calls == [], "no further lane request was issued"

    def test_a_refusal_arrives_as_a_categorised_error_event(self) -> None:
        session = _Session()

        async def blocking(text: str, calling_context: str) -> ModerationVerdict:
            return BLOCKED

        with (
            patch.object(api, "async_session_factory", lambda: session),
            patch.object(api, "moderate", blocking),
        ):
            events = self._stream({"question": FREE_FORM, "preset_id": None})

        assert [name for name, _ in events] == ["error"]
        assert events[0][1]["outcome"] == "moderation_blocked"
        assert events[0][1]["message"] == BLOCKED.visitor_message

    def test_an_over_long_question_is_refused_by_the_schema(self) -> None:
        response = client.post(
            "/api/orchestrated/run", json={"question": "x" * 5000, "preset_id": None}
        )

        assert response.status_code == 422
