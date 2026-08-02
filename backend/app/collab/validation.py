# Built with Spec4 AI - https://spec4.ai
"""Validating the two inputs this example accepts. Both are closed sets.

A visitor supplies a scenario id and a priority weighting, and that is all.
The first is an enum over the catalogue; the second is a numeric vector over
the four declared axes. **No free text reaches this slice at any point** --
which is why this is the one example app in the showcase with no moderation
gate in front of it, and the reason is worth stating rather than leaving as an
apparent omission.

Validation runs *before* any allowance is reserved. An invalid request should
cost nothing: refusing after a reservation would spend a run's budget on a
request that was never going to execute, and refunding it is a path that can be
forgotten.

The weighting is accepted either as a preset id or as an explicit vector. Both
are closed: a vector is checked to cover exactly the scenario's declared axes,
carry integers in range, and sum to 100. Anything else is refused by name --
never coerced, never normalised into something the visitor did not ask for,
because a silently renormalised weighting would change who wins the negotiation
and the visitor would have no way to tell.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from backend.app.collab.scenarios import (
    SCENARIOS_BY_ID,
    WEIGHT_TOTAL,
    WEIGHTINGS_BY_ID,
    AxisId,
    PriorityWeighting,
    Scenario,
)

#: Machine-readable refusal codes. Distinct because they call for different
#: fixes: an unknown id means the client is out of date, a malformed vector
#: means the client built the request wrongly.
CODE_UNKNOWN_SCENARIO: Final[str] = "unknown_scenario"
CODE_UNKNOWN_WEIGHTING: Final[str] = "unknown_weighting"
CODE_INVALID_WEIGHTING: Final[str] = "invalid_weighting"


class InvalidRequestError(Exception):
    """Raised when a run request is not valid.

    Attributes:
        code: A machine-readable refusal code.
    """

    def __init__(self, code: str, message: str) -> None:
        """Initialise with a refusal code and a visitor-readable message.

        Args:
            code: One of the `CODE_*` constants.
            message: What to show the visitor.
        """
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedRequest:
    """A run request that has been checked and resolved to real objects.

    Downstream code takes this rather than raw strings, so there is no second
    place where an unvalidated id could enter the run.

    Attributes:
        scenario: The resolved scenario.
        weighting: The resolved weighting, either a preset or one built from a
            supplied vector.
    """

    scenario: Scenario
    weighting: PriorityWeighting


def validate_request(
    *,
    scenario_id: str,
    weighting_id: str | None = None,
    weights: Mapping[str, int] | None = None,
) -> ValidatedRequest:
    """Validate and resolve a run request. Call before reserving anything.

    Exactly one of `weighting_id` or `weights` is used: a preset id is
    preferred when both are given, mirroring the single-call app's rule that a
    preset outranks free input server-side. A client that sends both gets the
    preset, and the resolved weighting is echoed back so the screen can never
    display one thing while the run used another.

    Args:
        scenario_id: The scenario the visitor chose.
        weighting_id: A preset weighting id, if they chose a preset.
        weights: An explicit per-axis vector, if they supplied one.

    Returns:
        The resolved scenario and weighting.

    Raises:
        InvalidRequestError: If the scenario id is not in the catalogue, the
            weighting id is not a preset, or the vector does not cover exactly
            the scenario's axes with integers in range summing to 100.
    """
    scenario = SCENARIOS_BY_ID.get(scenario_id)
    if scenario is None:
        raise InvalidRequestError(
            CODE_UNKNOWN_SCENARIO,
            f"{scenario_id!r} is not one of this example's procurement scenarios.",
        )

    if weighting_id is not None:
        preset = WEIGHTINGS_BY_ID.get(weighting_id)
        if preset is None:
            raise InvalidRequestError(
                CODE_UNKNOWN_WEIGHTING,
                f"{weighting_id!r} is not one of this example's priority weightings.",
            )
        return ValidatedRequest(scenario=scenario, weighting=preset)

    if weights is None:
        raise InvalidRequestError(
            CODE_INVALID_WEIGHTING,
            "A priority weighting is required: send a preset id or a set of "
            "per-term weights.",
        )

    return ValidatedRequest(
        scenario=scenario,
        weighting=_weighting_from_vector(scenario, weights),
    )


def _weighting_from_vector(
    scenario: Scenario, weights: Mapping[str, int]
) -> PriorityWeighting:
    """Build a weighting from a caller-supplied vector, or refuse it.

    Args:
        scenario: The scenario whose axes the vector must cover.
        weights: The supplied per-axis weights.

    Returns:
        A `PriorityWeighting` carrying the supplied weights.

    Raises:
        InvalidRequestError: If the keys are not exactly the scenario's axes,
            a value is not an integer in `0..100`, or the total is not 100.
    """
    declared = {axis.id.value for axis in scenario.axes}
    supplied = set(weights)

    if supplied != declared:
        missing = sorted(declared - supplied)
        unexpected = sorted(supplied - declared)
        raise InvalidRequestError(
            CODE_INVALID_WEIGHTING,
            "The priority weighting must cover exactly this scenario's terms "
            f"({', '.join(sorted(declared))}). "
            f"Missing: {missing or 'none'}. Unexpected: {unexpected or 'none'}.",
        )

    resolved: dict[AxisId, int] = {}
    for key, value in weights.items():
        # `bool` is an `int` subclass, and `True` would sail through a naive
        # isinstance check and score as 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidRequestError(
                CODE_INVALID_WEIGHTING,
                f"Weight for {key!r} must be a whole number.",
            )
        if not 0 <= value <= WEIGHT_TOTAL:
            raise InvalidRequestError(
                CODE_INVALID_WEIGHTING,
                f"Weight for {key!r} must be between 0 and {WEIGHT_TOTAL}.",
            )
        resolved[AxisId(key)] = value

    total = sum(resolved.values())
    if total != WEIGHT_TOTAL:
        raise InvalidRequestError(
            CODE_INVALID_WEIGHTING,
            f"The weights must add up to {WEIGHT_TOTAL}; these add up to {total}. "
            "They are not rescaled automatically, because a rescaled weighting "
            "can change which supplier wins.",
        )

    return PriorityWeighting(
        id="custom",
        label="Custom weighting",
        description="Per-term weights supplied with the request.",
        weights=resolved,
    )
