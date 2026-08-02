# Built with Spec4 AI - https://spec4.ai
"""One structured summary per collaboration run.

Following the shape v5 settled on for the orchestrated app: a single
`collab_run_summary` event emitted on **every** terminal path, rather than one
event per stage. Answering "what did that run do?" by joining six per-stage
records on a run id is the kind of query nobody actually runs, and a failed run
ends up less legible than a successful one precisely when legibility matters
most.

## The field that must always be zero

`seller_to_seller_messages`. It is computed from the run's own message log
rather than assumed, because the app's headline claim is that no such message
exists and a claim nothing measures is the defect this project keeps finding.
`opacity.deliver` makes a non-zero value impossible; this is what would say so
if that stopped being true.

## What is never emitted

No sealed constraint value, no bid figure, and no reveal prose. A leak into an
operator's log is still a leak -- it has only changed audience. What is
recorded is shape and cost: how many calls, how long each stage took, which
track degraded.

The visitor supplies no free text to this app at all (a scenario enum and a
numeric vector), so unlike the other examples there is nothing here that needs
hashing before it can be logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class RunTelemetry:
    """What one run did, accumulated as it runs and emitted once at the end.

    Mutable by design: stages fill it in as they complete, so a run that dies
    halfway still emits everything that had happened by then.

    Attributes:
        run_id: The run's identifier, shared with its allowance hold and its
            `negotiation_runs` row.
        scenario_id: Which scenario was negotiated.
        weighting_id: Which priority weighting was applied.
        outcome: How the run ended.
        negotiation_stage_calls: How many of the six negotiation stages spent
            a model call.
        total_model_calls: Every provider request the run made, including any
            the framework re-issued inside one logical step.
        hold_units: How many units were reserved up front.
        stage_latency_ms: Per-stage wall-clock, keyed by stage name.
        degradation: Per-seller degradation flags -- which track failed, timed
            out, or returned non-conforming output.
        seller_to_seller_messages: Must be zero. Measured, not assumed.
        leak_lint_hits: How many outbound messages the leak lint stopped.
            Non-zero means a real defect and an aborted run.
        explanation_fallbacks: Which post-award panels were rendered from the
            deterministic template rather than written. Read as a *rate* across
            runs: a panel occasionally falling back is the design working, and
            every panel falling back means the validators are rejecting
            everything the models produce, which is a defect in one or the
            other.
        explanation_violations: What the checks flagged, per panel. The signal
            that says *which* check is rejecting -- a stance mismatch and an
            invented numeral call for different fixes.
    """

    run_id: str
    scenario_id: str
    weighting_id: str
    outcome: str = "unknown"
    negotiation_stage_calls: int = 0
    total_model_calls: int = 0
    hold_units: int = 0
    stage_latency_ms: dict[str, int] = field(default_factory=dict)
    degradation: dict[str, str] = field(default_factory=dict)
    seller_to_seller_messages: int = 0
    leak_lint_hits: int = 0
    explanation_fallbacks: dict[str, bool] = field(default_factory=dict)
    explanation_violations: dict[str, list[str]] = field(default_factory=dict)

    def record_stage(self, stage: str, latency_ms: int) -> None:
        """Record how long one stage took.

        Args:
            stage: The stage's name.
            latency_ms: Its wall-clock duration in milliseconds.
        """
        self.stage_latency_ms[stage] = latency_ms

    def record_degradation(self, agent_id: str, reason: str) -> None:
        """Record that one track did not complete normally.

        Args:
            agent_id: Whose track degraded.
            reason: A short machine-readable reason -- never model output,
                which could carry sealed material.
        """
        self.degradation[agent_id] = reason

    def record_explanation(
        self, panel: str, *, fallback: bool, violations: list[str]
    ) -> None:
        """Record how one post-award panel was produced.

        Args:
            panel: `reveal` or `sensitivity`.
            fallback: True when the deterministic template produced it.
            violations: What the checks flagged, if anything.
        """
        self.explanation_fallbacks[panel] = fallback
        self.explanation_violations[panel] = list(violations)

    def as_event(self) -> dict[str, Any]:
        """Project to the fields the log line carries.

        Returns:
            The event body. Contains no bid figures, no sealed values and no
            generated prose -- see this module's docstring.
        """
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "weighting_id": self.weighting_id,
            "outcome": self.outcome,
            "negotiation_stage_calls": self.negotiation_stage_calls,
            "total_model_calls": self.total_model_calls,
            "hold_units": self.hold_units,
            "stage_latency_ms": dict(self.stage_latency_ms),
            "degradation": dict(self.degradation),
            "seller_to_seller_messages": self.seller_to_seller_messages,
            "leak_lint_hits": self.leak_lint_hits,
            "explanation_fallbacks": dict(self.explanation_fallbacks),
            "explanation_violations": dict(self.explanation_violations),
        }

    def emit(self) -> None:
        """Emit the run summary. Called on every terminal path.

        A run that failed is as worth summarising as one that succeeded --
        arguably more so, which is why this is not conditional on success.
        """
        logger.info("collab_run_summary", **self.as_event())
