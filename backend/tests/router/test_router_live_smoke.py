# Built with Spec4 AI - https://spec4.ai
"""Live smoke: one real classification of preset 1. Opt in with `-m live`.

Spends one real model call. Deselected by default (see pyproject's addopts),
so it never gates the build on a provider's availability.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from backend.app.router.classifier import classify
from backend.app.router.decision import Malformed, decide
from backend.app.router.presets import get_preset

pytestmark = pytest.mark.live


@pytest.fixture
def no_live_model_calls() -> Iterator[None]:
    """Override the suite's guard: this module exists to call a real model."""
    yield


def test_preset_1_returns_a_valid_four_score_decision() -> None:
    preset = get_preset("p1")
    assert preset is not None

    result = asyncio.run(classify(preset.request))

    assert result.decision is not None, result.failure
    assert len(result.decision.scores.as_dict()) == 4
    assert not isinstance(decide(result), Malformed)
