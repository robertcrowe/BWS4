# Built with Spec4 AI - https://spec4.ai
"""Record the live checker's verdicts into the golden set. Developer-invoked.

    uv run python -m backend.app.react.record_suitability

**Why a recording rather than a live suite.** Accuracy thresholds over a
free-tier chain are inherently flaky: a suite that calls live models passes on a
laptop and fails in CI the day a slug is rate-limited or withdrawn, and a gate
that fails for reasons unrelated to the change is a gate people learn to ignore.
So the check is run once, deliberately, and `test_react_suitability_golden.py`
scores that recording against the hand-assigned labels offline.

**What that costs in honesty, stated plainly.** The recorded numbers describe
one run of one chain on one day. They are evidence that the check *did* behave
this way, not a standing claim that it always will. `_recorded_at` is written
into the fixture so a stale recording is visible in diff, and re-running this
after a prompt or chain change is the maintenance this buys.

It spends provider quota -- one call per question, roughly sixty -- but no
`usage_limits` allowance: the suitability check is deliberately outside the
shared gate, so recording cannot take the gallery dark. It is paced anyway,
because a tightly-metered provider will otherwise report healthy slugs as
failures, which is the harness bug `discover_models.py` already paid for once.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.react import suitability

GOLDEN = Path(__file__).resolve().parents[3] / "backend/tests/react/golden"
CASES = GOLDEN / "suitability_cases.json"

#: Seconds between calls. The free tiers meter per minute as well as per day,
#: and a burst of sixty would measure the meter rather than the check.
STAGGER_SECONDS = 1.5


async def _record_one(case: dict[str, Any], index: int) -> dict[str, Any] | None:
    """Ask the real checker about one question.

    Args:
        case: The labelled case.
        index: Its position, used only to keep session ids distinct so the
            per-session cap of five does not silently truncate the run.

    Returns:
        The verdict's scoreable fields, or None when the check resolved neutral.
    """
    suitability.reset_state()
    verdict = await suitability.assess(case["question"], session_id=f"record-{index}")
    if verdict is None:
        return None
    return {
        "verdict": verdict.verdict,
        "estimated_hops": verdict.estimated_hops,
        "requires_live_info": verdict.requires_live_info,
        # Recorded because the model pairs it with `requires_live_info` under a
        # validator: a recording without it cannot be fed back through
        # `QuestionSuitability`, which is exactly what the golden suite does to
        # prove the payload was schema-valid.
        "live_hop_description": verdict.live_hop_description,
        "exercises_loop": verdict.exercises_loop,
        "confidence": verdict.confidence,
    }


async def main() -> None:
    """Record every case and rewrite the fixture in place.

    Pass `--missing-only` to retry just the cases that came back neutral. The
    6s timeout is a real property of this chain rather than a flake -- roughly
    half of a cold run times out -- so a second pass fills gaps without
    pretending the first pass did not happen. Nothing already recorded is
    overwritten by that mode.
    """
    doc = json.loads(CASES.read_text())
    missing_only = "--missing-only" in sys.argv
    neutral = 0

    for index, case in enumerate(doc["cases"]):
        if missing_only and "recorded" in case:
            continue
        recorded = await _record_one(case, index)
        if recorded is None:
            neutral += 1
            case.pop("recorded", None)
            print(f"{case['id']}: neutral (no verdict)")
        else:
            case["recorded"] = recorded
            agree = "OK " if recorded["verdict"] == case["label"]["verdict"] else "MISS"
            print(
                f"{case['id']}: {agree} {recorded['verdict']:<16} "
                f"hops={recorded['estimated_hops']} "
                f"live={recorded['requires_live_info']}"
            )
        await asyncio.sleep(STAGGER_SECONDS)

    # The injection probes are recorded the same way, because what has to be
    # shown is that a real model handed a real attack still returns something
    # of exactly the declared shape -- an assertion about the schema, checked
    # against output rather than argued from it.
    for index, probe in enumerate(doc["injections"]):
        if missing_only and "recorded" in probe:
            continue
        recorded = await _record_one(probe, 1000 + index)
        if recorded is None:
            probe.pop("recorded", None)
            print(f"{probe['id']}: neutral (no verdict)")
        else:
            probe["recorded"] = recorded
            print(f"{probe['id']}: shape held -> {recorded['verdict']}")
        await asyncio.sleep(STAGGER_SECONDS)

    doc["_recorded_at"] = datetime.now(UTC).date().isoformat()
    doc["_neutral_count"] = sum(1 for case in doc["cases"] if "recorded" not in case)
    CASES.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {CASES} ({neutral} neutral this pass)")


if __name__ == "__main__":
    asyncio.run(main())
