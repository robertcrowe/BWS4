# Built with Spec4 AI - https://spec4.ai
"""The labelled golden set for the question-suitability check.

## Two different kinds of claim live in this file, and they are gated differently

**Code properties** — schema validity after at most one repair, the invariant
repairs, the derived preset verdicts, the shape an injection cannot change.
These hold whatever a model does, so they are hard failures.

**Model accuracy** — how often the check agreed with a human label. This can
only be measured against a *recording*: a suite that called live models would
pass on a laptop and fail in CI the day a slug is withdrawn, and a gate that
fails for reasons unrelated to the change is one people learn to ignore. So
`suitability_cases.json` carries what the live chain returned on one day, and
this scores that offline.

Instruction 11 draws the line: the multi-hop-versus-single-hop threshold and
schema validity fail the build; the softer accuracy numbers are printed with a
confusion matrix and reported rather than gating. That is deliberate — the
distinction the advisory actually hinges on is multi versus single, and the
rest is information for whoever next touches the prompt.

## The recording is a snapshot, and the file says so

Re-record with `uv run python -m backend.app.react.record_suitability` after a
prompt or chain change. A test asserts the recording carries a date, so a
fixture that has quietly aged is visible rather than assumed current.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from backend.app.react import presets, schemas, suitability
from backend.app.services import agent_runtime

GOLDEN = Path(__file__).resolve().parent / "golden"
DOC: dict[str, Any] = json.loads((GOLDEN / "suitability_cases.json").read_text())
CASES: list[dict[str, Any]] = DOC["cases"]
INJECTIONS: list[dict[str, Any]] = DOC["injections"]
RECORDED = [case for case in CASES if "recorded" in case]

#: The specification's own numbers. The first is a hard gate; the rest report.
THRESHOLD_VERDICT_AGREEMENT = 0.85
THRESHOLD_MULTI_VS_SINGLE = 0.90
THRESHOLD_LIVE_INFO = 0.85
THRESHOLD_LIVE_RECALL = 0.90


def _is_multi(verdict: str) -> bool:
    return verdict.startswith("multi_hop")


def _rate(hits: int, total: int) -> float:
    return 0.0 if total == 0 else hits / total


# ---------------------------------------------------------------------------
# The set itself
# ---------------------------------------------------------------------------


def test_the_set_has_the_composition_the_specification_names() -> None:
    """Sixty questions, spanning every verdict and both sides of the live axis."""
    assert len(CASES) == 60

    verdicts = Counter(case["label"]["verdict"] for case in CASES)
    assert set(verdicts) == {
        "multi_hop_live",
        "multi_hop_static",
        "single_hop",
        "unanswerable",
    }
    # The compound-but-single-hop traps the prompt's few-shot pairs exist for.
    compound = [c for c in CASES if c["class"] == "single_hop_compound"]
    assert len(compound) >= 4

    # Four questions are single-hop *and* live. Without them the verdict and
    # `requires_live_info` could be scored as one field and nobody would notice.
    crossover = [
        c
        for c in CASES
        if c["label"]["verdict"] == "single_hop" and c["label"]["requires_live_info"]
    ]
    assert len(crossover) >= 3


def test_every_label_is_internally_consistent() -> None:
    """A label that contradicts itself would make the whole score meaningless."""
    for case in CASES:
        label = case["label"]
        if _is_multi(label["verdict"]):
            assert label["estimated_hops"] >= 2, case["id"]
        else:
            assert label["estimated_hops"] == 1, case["id"]
        if label["verdict"] == "multi_hop_live":
            assert label["requires_live_info"], case["id"]


def test_disputed_labels_carry_their_argument() -> None:
    """Instruction 10: ground truth auditable in diff, not merely asserted."""
    documented = [c for c in CASES if c.get("rationale")]
    assert len(documented) >= 5
    for case in documented:
        assert len(case["rationale"]) > 40, case["id"]


def test_the_recording_is_dated_and_declared_as_a_snapshot() -> None:
    """A stale fixture must be visible rather than silently believed."""
    assert DOC["_recorded_at"]
    assert "not a standing measurement" in DOC["_recorded_is_not_a_label"]


# ---------------------------------------------------------------------------
# Accuracy over the recording — one hard gate, the rest reported
# ---------------------------------------------------------------------------


def test_the_multi_hop_versus_single_hop_distinction_is_gated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The distinction the advisory hinges on. A hard failure, per instruction 11.

    Everything the visitor is told turns on this one bit: whether the loop will
    engage. The four-way verdict can be wrong about *which kind* of multi-hop a
    question is and still give the visitor a true hint; being wrong about multi
    versus single gives them a false one.
    """
    scoreable = [c for c in RECORDED if c["label"]["verdict"] != "unanswerable"]
    hits = [
        c
        for c in scoreable
        if _is_multi(c["recorded"]["verdict"]) == _is_multi(c["label"]["verdict"])
    ]
    rate = _rate(len(hits), len(scoreable))

    with capsys.disabled():
        print(f"\n  multi_hop vs single_hop: {len(hits)}/{len(scoreable)} = {rate:.1%}")
        for case in scoreable:
            if _is_multi(case["recorded"]["verdict"]) != _is_multi(
                case["label"]["verdict"]
            ):
                print(
                    f"    MISS {case['id']}: labelled {case['label']['verdict']}, "
                    f"recorded {case['recorded']['verdict']}"
                )

    assert rate >= THRESHOLD_MULTI_VS_SINGLE, (
        f"{rate:.1%} is below the {THRESHOLD_MULTI_VS_SINGLE:.0%} the "
        "specification requires for the distinction the advisory hinges on"
    )


def test_the_verdict_confusion_matrix_is_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Printed, not gated. The matrix is what tells you *how* a prompt drifted."""
    labels = ["multi_hop_live", "multi_hop_static", "single_hop", "unanswerable"]
    matrix: Counter[tuple[str, str]] = Counter(
        (case["label"]["verdict"], case["recorded"]["verdict"]) for case in RECORDED
    )
    hits = sum(matrix[(label, label)] for label in labels)
    rate = _rate(hits, len(RECORDED))

    with capsys.disabled():
        print(f"\n  verdict confusion matrix (recorded {DOC['_recorded_at']}):")
        print(
            f"    {'label \\\\ recorded':<20}"
            + "".join(f"{c[:12]:>14}" for c in labels)
        )
        for label in labels:
            row = "".join(f"{matrix[(label, got)]:>14}" for got in labels)
            print(f"    {label:<20}{row}")
        print(f"    overall agreement: {hits}/{len(RECORDED)} = {rate:.1%}")

    if rate < THRESHOLD_VERDICT_AGREEMENT:
        # Reported, not failed: a four-way agreement dip is a prompt signal,
        # and failing the build on it would gate CI on model weather.
        print(
            f"  NOTE: verdict agreement {rate:.1%} is below the specification's "
            f"{THRESHOLD_VERDICT_AGREEMENT:.0%}"
        )


def test_the_live_information_accuracy_is_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reported with its recall, because a false negative is the costly error.

    Telling a visitor their question needs no live information when it does
    promises a static answer for something the model cannot answer offline.
    Telling them the opposite costs nothing but a hedge -- which is why the
    prompt biases toward "live" on doubt, and why the recorded misses are all
    in that safe direction.
    """
    hits = [
        c
        for c in RECORDED
        if c["recorded"]["requires_live_info"] == c["label"]["requires_live_info"]
    ]
    live_cases = [c for c in RECORDED if c["label"]["requires_live_info"]]
    recalled = [c for c in live_cases if c["recorded"]["requires_live_info"]]
    accuracy = _rate(len(hits), len(RECORDED))
    recall = _rate(len(recalled), len(live_cases))

    with capsys.disabled():
        total = len(RECORDED)
        print(f"\n  requires_live_info accuracy: {len(hits)}/{total} = {accuracy:.1%}")
        print(
            f"  requires_live_info recall:   "
            f"{len(recalled)}/{len(live_cases)} = {recall:.1%}"
        )
        for case in RECORDED:
            got = case["recorded"]["requires_live_info"]
            want = case["label"]["requires_live_info"]
            if got != want:
                direction = "over-flagged (safe)" if got else "MISSED live need"
                print(f"    {case['id']}: {direction}")

    if accuracy < THRESHOLD_LIVE_INFO:
        print(f"  NOTE: accuracy below the specification's {THRESHOLD_LIVE_INFO:.0%}")
    if recall < THRESHOLD_LIVE_RECALL:
        print(f"  NOTE: recall below the specification's {THRESHOLD_LIVE_RECALL:.0%}")


# ---------------------------------------------------------------------------
# Schema validity — the second hard gate
# ---------------------------------------------------------------------------


def test_every_recorded_payload_validates_against_the_production_model() -> None:
    """A hard gate. Zero out-of-enum verdicts may reach the frontend.

    Validated against the *production* `QuestionSuitability`, so a fixture that
    drifted from the shipped schema fails here rather than making the suite
    pass while the live system rejects the same shape.
    """
    for case in RECORDED + [p for p in INJECTIONS if "recorded" in p]:
        recorded = case["recorded"]
        model = schemas.QuestionSuitability(
            verdict=recorded["verdict"],
            estimated_hops=recorded["estimated_hops"],
            requires_live_info=recorded["requires_live_info"],
            live_hop_description=recorded["live_hop_description"],
            exercises_loop=recorded["exercises_loop"],
            confidence=recorded["confidence"],
            visitor_message="A sentence.",
        )
        assert model.verdict in {
            "multi_hop_live",
            "multi_hop_static",
            "single_hop",
            "unanswerable",
        }


def test_unknown_is_not_an_emittable_verdict() -> None:
    """The fail-open state is the frontend's, and a model may not claim it."""
    with pytest.raises(ValidationError):
        schemas.QuestionSuitability(
            verdict="unknown",  # type: ignore[arg-type]
            estimated_hops=1,
            requires_live_info=False,
            exercises_loop=False,
            confidence="low",
            visitor_message="x",
        )


def test_one_repair_retry_is_enough_to_reach_a_valid_payload() -> None:
    """First ask malformed, second ask valid: exactly one repair, then done."""
    suitability.reset_state()
    calls = {"n": 0}

    async def fake(**_kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise agent_runtime.AgentLaneError("react-suitability", "not valid")
        return agent_runtime.StepResult(
            output=schemas.QuestionSuitability(
                verdict="multi_hop_live",
                estimated_hops=3,
                requires_live_info=True,
                live_hop_description="the current officeholder",
                exercises_loop=True,
                confidence="high",
                visitor_message="This should exercise the loop.",
            ),
            model="fake/model",
            requests=1,
        )

    with patch.object(agent_runtime, "run_typed_step", fake):
        verdict = asyncio.run(
            suitability.assess(
                "A chained question about a current officeholder?", session_id="s"
            )
        )

    assert verdict is not None
    assert calls["n"] == 2


def test_a_second_failure_resolves_neutral_rather_than_raising() -> None:
    """Every failure path is the same `None`, which is the whole design."""
    suitability.reset_state()

    async def always_bad(**_kwargs: Any) -> Any:
        raise agent_runtime.AgentLaneError("react-suitability", "still not valid")

    with patch.object(agent_runtime, "run_typed_step", always_bad):
        verdict = asyncio.run(
            suitability.assess("A perfectly ordinary chained question?", session_id="s")
        )

    assert verdict is None


# ---------------------------------------------------------------------------
# Injection — instruction 7's last clause
# ---------------------------------------------------------------------------


def test_the_injection_probes_changed_the_output_shape_not_at_all() -> None:
    """Five attacks, five payloads of exactly the declared shape.

    This is a property of schema-constrained output rather than of the prompt:
    there is no field an injection could add and no type it could change. What
    the recording adds is that a real model, handed a real attack, still
    produced one -- the argument checked against output rather than asserted.
    """
    recorded = [p for p in INJECTIONS if "recorded" in p]
    assert len(recorded) == len(INJECTIONS) == 5

    expected_fields = {
        "verdict",
        "estimated_hops",
        "requires_live_info",
        "live_hop_description",
        "exercises_loop",
        "confidence",
    }
    for probe in recorded:
        assert set(probe["recorded"]) == expected_fields, probe["id"]
        assert 1 <= probe["recorded"]["estimated_hops"] <= schemas.MAX_ESTIMATED_HOPS
        assert isinstance(probe["recorded"]["requires_live_info"], bool)
        # inj01 asks for five hops and inj02 for ninety-nine; neither got them.
        assert probe["recorded"]["verdict"] in {
            "multi_hop_live",
            "multi_hop_static",
            "single_hop",
            "unanswerable",
        }


def test_the_injection_set_covers_distinct_attack_shapes() -> None:
    """One attack repeated five times would be one probe, not five."""
    attacks = {probe["attack"] for probe in INJECTIONS}
    assert len(attacks) == 5
    assert "direct_override" in attacks
    assert "delimiter_forgery" in attacks


def test_an_over_long_message_is_substituted_rather_than_rejected() -> None:
    """The cap is a substitution, not a validation failure.

    `visitor_message` carries `max_length`, and a field bound *rejects*. An
    over-long sentence would therefore spend the repair retry that exists for
    real schema breaches, and quite possibly resolve the whole check to neutral
    over a cosmetic fault. Sanitising in a `before` validator makes the bound a
    backstop that can no longer trip.
    """
    model = schemas.QuestionSuitability(
        verdict="single_hop",
        estimated_hops=1,
        requires_live_info=False,
        exercises_loop=False,
        confidence="high",
        visitor_message="x" * 400,
    )

    assert len(model.visitor_message) <= schemas.MAX_VISITOR_MESSAGE_CHARS


# ---------------------------------------------------------------------------
# The preset regression — instruction 8
# ---------------------------------------------------------------------------


def test_all_five_presets_return_a_loop_exercising_multi_hop_verdict() -> None:
    """The capability's own regression criterion, and it costs no model call.

    A preset's structure was characterised by hand when it was written, so the
    verdict is derived from `presets.py` rather than asked for -- which is what
    makes this a genuine hard assertion rather than a measurement of model
    weather.
    """
    for preset in presets.PRESETS:
        verdict = suitability.preset_verdict(preset.question)

        assert verdict is not None, preset.id
        assert verdict.verdict in {"multi_hop_live", "multi_hop_static"}, preset.id
        assert verdict.exercises_loop is True, preset.id
        assert verdict.estimated_hops >= 2, preset.id


def test_a_preset_verdict_spends_neither_a_model_call_nor_a_session_check() -> None:
    """Derived, not asked. The autouse lane guard makes a call fail loudly."""
    suitability.reset_state()
    question = presets.PRESETS[0].question

    # No lane patch at all: the conftest fixture refuses any real call, so this
    # passing is itself the evidence that none was made.
    verdict = asyncio.run(suitability.assess(question, session_id="preset-session"))

    assert verdict is not None
    assert verdict.exercises_loop is True


def test_an_edited_preset_is_treated_as_the_visitor_s_own_words() -> None:
    """Recognised by byte-match, never claimed. A lost exemption, not a bypass."""
    edited = presets.PRESETS[0].question + " Please answer quickly."

    assert suitability.preset_verdict(edited) is None
