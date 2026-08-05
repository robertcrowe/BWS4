# Built with Spec4 AI - https://spec4.ai
"""The labelled fixture-trace set for hop-source annotation.

## What is being measured, and why it is a hard gate

Not "how often does a model label a hop correctly" -- that would be model
weather. What this scores is `apply_cross_checks`: given what a model proposed,
does the deterministic re-derivation land on the human label? That is a property
of the code, true whatever a model does, so the zero-surviving-unsupported-claims
assertion fails the build per instruction 11.

**The adversarial traces label the corrected value, not the model's claim.** A
check that simply believed its input would fail them. That is the whole design:
the model's label is a proposal and what the trace can support is the verdict.

## The set covers what the specification names

All five presets, free-form questions, both endings, and each adversarial class:
over-crediting on `observation` *and* on `mixed`, index drift, a forward
citation, resolution language on an exhausted run, and a search that could not
be run at all. A spot check cannot prove an invariant, and the failure being
guarded against is the class nobody wrote a fixture for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.react import annotation, presets, schemas

GOLDEN = Path(__file__).resolve().parent / "golden"
DOC: dict[str, Any] = json.loads((GOLDEN / "annotation_traces.json").read_text())
TRACES: list[dict[str, Any]] = DOC["traces"]
TRACE_IDS = [trace["id"] for trace in TRACES]

#: The specification's own numbers, both hard gates here because both are
#: properties of the cross-checks rather than of a model.
THRESHOLD_LABEL_AGREEMENT = 0.90
THRESHOLD_RECALLED_RECALL = 0.95


def _checked(trace: dict[str, Any]) -> schemas.AnnotationResult:
    """Run the production cross-checks over one authored trace."""
    proposed = schemas.HopAnnotations(
        hops=[schemas.HopAnnotation(**hop) for hop in trace["model_output"]]
    )
    return annotation.apply_cross_checks(
        proposed, trace["cycles"], ending=trace["ending"]
    )


# ---------------------------------------------------------------------------
# The set itself
# ---------------------------------------------------------------------------


def test_the_set_covers_every_class_the_specification_names() -> None:
    """Presets, free-form, both endings, and each adversarial shape."""
    origins = {trace["question_origin"] for trace in TRACES}
    assert {preset.id for preset in presets.PRESETS} <= origins
    assert presets.CUSTOM_ORIGIN in origins

    endings = {trace["ending"] for trace in TRACES}
    assert endings == {
        schemas.ENDING_FINAL_ANSWER,
        schemas.ENDING_BUDGET_EXHAUSTED,
    }

    classes = {trace["class"] for trace in TRACES}
    assert {
        "adversarial_over_crediting",
        "adversarial_index_drift",
        "adversarial_forward_citation",
    } <= classes


def test_every_trace_carries_its_argument() -> None:
    """Instruction 10 again: the ground truth is reviewable in diff."""
    for trace in TRACES:
        assert len(trace.get("rationale", "")) > 40, trace["id"]


def test_the_file_says_what_it_can_and_cannot_establish() -> None:
    """The disclaimer is part of the evidence."""
    assert "NOT a measurement of how often a live model" in DOC["_how_it_was_built"]


# ---------------------------------------------------------------------------
# The hard gate — instruction 9 and instruction 11
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
def test_no_unsupported_grounding_claim_survives(trace: dict[str, Any]) -> None:
    """Zero surviving `observation` or `mixed` labels without real support.

    Re-derived here from the trace independently of the production code's own
    bookkeeping, so a check that stopped downgrading would fail on the
    assertion rather than on its own report of what it downgraded.
    """
    result = _checked(trace)
    by_index = {entry["cycle"]: entry for entry in trace["cycles"]}

    for hop in result.hops:
        if hop.source not in {"observation", "mixed"}:
            continue
        assert hop.supporting_cycle is not None, hop.fact
        supporting = by_index.get(hop.supporting_cycle)
        assert supporting is not None, hop.fact
        assert supporting["action"]["kind"] == "search", hop.fact
        assert supporting["observation"], hop.fact
        assert supporting["observation"]["results"], hop.fact
        # A later observation cannot be what an earlier hop rested on.
        assert hop.supporting_cycle <= hop.cycle_index, hop.fact


@pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
def test_every_surviving_annotation_names_a_cycle_in_its_own_trace(
    trace: dict[str, Any],
) -> None:
    """100% index validity after validation. A badge on a missing hop is worse."""
    result = _checked(trace)
    indices = {entry["cycle"] for entry in trace["cycles"]}

    for hop in result.hops:
        assert hop.cycle_index in indices


@pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
def test_at_most_one_annotation_per_cycle_survives(trace: dict[str, Any]) -> None:
    """One entry per numbered cycle, never two badges on one row."""
    result = _checked(trace)
    seen = [hop.cycle_index for hop in result.hops]

    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
def test_every_surviving_annotation_validates_against_the_shipped_schema(
    trace: dict[str, Any],
) -> None:
    """Schema validity, checked against production models rather than a copy."""
    result = schemas.AnnotationResult.model_validate(_checked(trace).model_dump())

    for hop in result.hops:
        assert hop.source in {"observation", "mixed", "model_knowledge"}
        assert len(hop.note) <= schemas.MAX_HOP_NOTE_CHARS


@pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
def test_a_budget_exhausted_run_is_never_annotated_as_resolved(
    trace: dict[str, Any],
) -> None:
    """The honesty panel is the worst place to imply an unfinished run finished."""
    if trace["ending"] != schemas.ENDING_BUDGET_EXHAUSTED:
        pytest.skip("this trace ends in an answer")
    result = _checked(trace)

    for hop in result.hops:
        assert not schemas.implies_resolution(hop.note), hop.note


@pytest.mark.parametrize("trace", TRACES, ids=TRACE_IDS)
def test_each_trace_matches_its_expected_outcome(trace: dict[str, Any]) -> None:
    """The per-trace expectations authored alongside the labels."""
    result = _checked(trace)
    expect = trace["expect"]

    if "all_hops_observed" in expect:
        assert result.all_hops_observed is expect["all_hops_observed"], trace[
            "rationale"
        ]
    if "dropped" in expect:
        assert len(result.dropped) == expect["dropped"]
    if "dropped_min" in expect:
        assert len(result.dropped) >= expect["dropped_min"], trace["rationale"]
    if "downgraded" in expect:
        assert len(result.downgraded) == expect["downgraded"]
    if "downgraded_min" in expect:
        assert len(result.downgraded) >= expect["downgraded_min"], trace["rationale"]


# ---------------------------------------------------------------------------
# Agreement with the human labels
# ---------------------------------------------------------------------------


def test_label_agreement_meets_the_specification_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """>=90% agreement on hops, over every trace in the set."""
    hits = 0
    total = 0
    misses: list[str] = []

    for trace in TRACES:
        result = _checked(trace)
        labels: dict[str, str] = trace["labels"]
        for hop in result.hops:
            expected = labels.get(str(hop.cycle_index))
            if expected is None:
                misses.append(
                    f"{trace['id']} cycle {hop.cycle_index}: survived unlabelled"
                )
                total += 1
                continue
            total += 1
            if hop.source == expected:
                hits += 1
            else:
                misses.append(
                    f"{trace['id']} cycle {hop.cycle_index}: "
                    f"labelled {expected}, produced {hop.source}"
                )

    rate = hits / total
    with capsys.disabled():
        print(f"\n  hop source agreement: {hits}/{total} = {rate:.1%}")
        for miss in misses:
            print(f"    MISS {miss}")

    assert rate >= THRESHOLD_LABEL_AGREEMENT


def test_recall_on_the_model_knowledge_class_meets_its_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """>=0.95 recall on `model_knowledge`, the costly class to miss.

    An unsourced hop labelled as observed is the app telling a visitor that
    evidence exists where none does -- which is the honesty claim this whole
    panel is built to support.
    """
    expected_recalled = 0
    found = 0

    for trace in TRACES:
        result = _checked(trace)
        by_index = {hop.cycle_index: hop for hop in result.hops}
        for index, label in trace["labels"].items():
            if label != "model_knowledge":
                continue
            expected_recalled += 1
            hop = by_index.get(int(index))
            # A dropped annotation counts as recalled: nothing was claimed.
            if hop is None or hop.source == "model_knowledge":
                found += 1

    recall = found / expected_recalled
    with capsys.disabled():
        print(f"  model_knowledge recall: {found}/{expected_recalled} = {recall:.1%}")

    assert recall >= THRESHOLD_RECALLED_RECALL


def test_the_presets_that_promise_a_fully_observed_run_have_one_on_record() -> None:
    """The product criterion presets 1-3 carry, checked against the derived flag."""
    grounded = {
        trace["question_origin"]
        for trace in TRACES
        if _checked(trace).all_hops_observed
    }
    promised = {
        preset.id for preset in presets.PRESETS if preset.guaranteed_fully_observed
    }

    assert promised <= grounded, (
        f"no fully observed run on record for {promised - grounded}"
    )


def test_the_set_would_not_pass_against_a_check_that_believed_the_model(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A guard on the guard: the adversarial traces must actually bite.

    A fixture set of only well-behaved traces would score perfectly against a
    cross-check that did nothing at all. This asserts the opposite -- that
    taking the model's proposal at face value disagrees with the labels -- so
    the agreement number above is evidence rather than arithmetic.
    """
    disagreements = 0
    for trace in TRACES:
        labels: dict[str, str] = trace["labels"]
        for hop in trace["model_output"]:
            expected = labels.get(str(hop["cycle_index"]))
            if expected is not None and hop["source"] != expected:
                disagreements += 1

    with capsys.disabled():
        print(f"  proposals the cross-checks had to correct: {disagreements}")

    assert disagreements >= 4
