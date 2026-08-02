# Built with Spec4 AI - https://spec4.ai
"""Composing the request for quotation. Deterministically, with no model call.

Stage 1 of the six is a **template**, not an inference. That is a deliberate
teaching point as much as a budget one: not every step in an agent system needs
a model, and a step whose output is fully determined by its inputs should not
be paying for one. Composing this from a scenario and a weighting is string
assembly over closed enumerations -- a model would add latency, cost, a failure
mode, and non-determinism, in exchange for nothing.

That is also what keeps the negotiation at exactly six model calls: the two
opening bids, two counter-offers and two best-and-final bids are inference; the
RFQ and the routing of counter-offers are not.

## What the RFQ must never contain

The buyer's sealed position. `Scenario.buyer_position` holds its budget ceiling
and its BATNA, and a seller that knew either would price straight to it. This
module therefore builds from an explicit allowlist of public fields rather than
serialising the scenario and removing what should not be there -- an allowlist
fails closed when a field is added, a denylist fails open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.collab.scenarios import (
    AxisId,
    PriorityWeighting,
    Scenario,
    TermAxis,
)


@dataclass(frozen=True)
class RequestedTerm:
    """One axis as the RFQ states it to a seller.

    Attributes:
        axis: Which axis.
        label: What it is called in this scenario.
        unit: The unit to quote in.
        direction: Which way is better, so a seller knows what it is competing
            on without having to infer it.
        weight: How much the buyer says this axis matters, 0--100. Published
            deliberately: the buyer's *priorities* are not secret, only its
            ceiling is. A seller that knows warranty is what matters can offer
            the warranty, which is the negotiation working rather than failing.
    """

    axis: AxisId
    label: str
    unit: str
    direction: str
    weight: int


@dataclass(frozen=True)
class QuotationRequest:
    """The public request both sellers receive, identically.

    Both sellers get the same object. That symmetry is part of the design: any
    difference between their bids comes from their own sealed constraints, not
    from having been asked different questions.

    Attributes:
        scenario_id: Which scenario this is.
        goods: What is being bought.
        baseline_requirement: What the buyer needs, in prose.
        weighting_id: Which priority weighting the visitor chose.
        weighting_label: Its human-readable name.
        terms: The four axes, with the buyer's stated weights.
        text: The rendered request, ready to drop into a prompt.
    """

    scenario_id: str
    goods: str
    baseline_requirement: str
    weighting_id: str
    weighting_label: str
    terms: tuple[RequestedTerm, ...]
    text: str

    def as_payload(self) -> dict[str, Any]:
        """Project to a JSON-serialisable dict for persistence and the wire.

        Returns:
            The request as plain types, suitable for a JSONB column or an SSE
            event.
        """
        return {
            "scenario_id": self.scenario_id,
            "goods": self.goods,
            "baseline_requirement": self.baseline_requirement,
            "weighting_id": self.weighting_id,
            "weighting_label": self.weighting_label,
            "terms": [
                {
                    "axis": term.axis.value,
                    "label": term.label,
                    "unit": term.unit,
                    "direction": term.direction,
                    "weight": term.weight,
                }
                for term in self.terms
            ],
            "text": self.text,
        }


def _term_line(axis: TermAxis, weight: int) -> str:
    """Render one axis as a line of the request."""
    aim = (
        "lower is better"
        if axis.direction.value.startswith("lower")
        else "higher is better"
    )
    return f"- {axis.label} ({axis.unit}; {aim}) — buyer weight {weight}/100"


def compose_rfq(scenario: Scenario, weighting: PriorityWeighting) -> QuotationRequest:
    """Compose the request for quotation. **Consumes no model call.**

    Deterministic templating: the same scenario and weighting always produce a
    byte-identical request. That is what keeps this run's negotiation stage
    count at exactly six -- stage 1 is free -- and it demonstrates that not
    every step in an agent system needs a model. A step whose output is fully
    determined by its inputs should not be paying inference latency, inference
    cost and inference variance for a result a template already gives.

    Nothing here reads `scenario.buyer_position`. The request is assembled from
    an explicit allowlist of public fields, so a sealed field added later is
    excluded by default rather than included by oversight.

    Args:
        scenario: The scenario being bought.
        weighting: The visitor's stated priorities.

    Returns:
        The request, identical for both sellers.
    """
    terms = tuple(
        RequestedTerm(
            axis=axis.id,
            label=axis.label,
            unit=axis.unit,
            direction=axis.direction.value,
            weight=weighting.weights[axis.id],
        )
        for axis in scenario.axes
    )

    lines = [
        "REQUEST FOR QUOTATION",
        "",
        f"Goods: {scenario.goods}",
        f"Requirement: {scenario.baseline_requirement}",
        "",
        f"The buyer's stated priority is: {weighting.label} — {weighting.description}",
        "",
        "Quote against each of these terms:",
        *[_term_line(axis, weighting.weights[axis.id]) for axis in scenario.axes],
        "",
        (
            "Partial fulfilment is acceptable; quote the quantity you can "
            "actually commit."
            if scenario.partial_fulfilment_allowed
            else "Partial fulfilment is not acceptable."
        ),
        (
            "You are bidding against one other supplier whose identity, terms "
            "and constraints you will not be shown at any point."
        ),
    ]

    return QuotationRequest(
        scenario_id=scenario.id,
        goods=scenario.goods,
        baseline_requirement=scenario.baseline_requirement,
        weighting_id=weighting.id,
        weighting_label=weighting.label,
        terms=terms,
        text="\n".join(lines),
    )
