# Built with Spec4 AI - https://spec4.ai
"""The preset catalogue, and the one property that must never stop holding.

**The catalogue stores questions and hop metadata only, and never an answer.**
That is what lets time-variable answers refresh from live search on every run,
and it is what stops anything quietly answering a preset from a stored string
while the trace claims the answer came from an observation. It is asserted here
structurally -- by walking the dataclass fields and the serialised payload --
rather than by reading the file, because the failure mode is a well-meant
future edit adding a convenience field, not a deliberate one.

The curation rules are asserted too. "At least one hop defeats memorised
knowledge" and "the later query cannot be written until the earlier result is
read" are what make the demonstration work at all, and a sixth preset added
without them would weaken the app silently.
"""

from __future__ import annotations

import dataclasses
import json

from backend.app.react.presets import (
    PRESET_IDS,
    PRESET_QUESTIONS,
    PRESETS,
    HopSource,
    Preset,
    PresetHop,
    get_preset,
)
from backend.app.react.service import public_presets

#: Any field name matching one of these would be somewhere an answer could be
#: parked. Substring matching, so `expected_answer` and `answer_text` are caught
#: as readily as `answer`.
_ANSWER_WORDS = ("answer", "solution", "result", "expected_value")


class TestTheCatalogueStoresNoAnswers:
    def test_no_dataclass_field_is_named_for_an_answer(self) -> None:
        """The structural half: there is nowhere to put one."""
        names = [field.name for field in dataclasses.fields(Preset)]
        names += [field.name for field in dataclasses.fields(PresetHop)]

        for name in names:
            for word in _ANSWER_WORDS:
                assert word not in name.lower(), f"{name} could hold a preset's answer"

    def test_no_published_field_is_named_for_an_answer(self) -> None:
        """The wire half: nothing an answer could ride on reaches the client."""
        payload = json.loads(public_presets().model_dump_json())

        for preset in payload["presets"]:
            for key in preset:
                for word in _ANSWER_WORDS:
                    assert word not in key.lower(), f"{key} is published"

    def test_a_hop_names_the_unknown_rather_than_resolving_it(self) -> None:
        """`fact` is maintainer metadata describing what a hop must establish.

        It is never published, so this is about the file staying readable
        without spoiling the demonstration -- but the check that matters is
        that it does not cross the wire, which is what the assertion covers.
        """
        payload = json.loads(public_presets().model_dump_json())

        published = json.dumps(payload)
        for preset in PRESETS:
            for hop in preset.expected_hops:
                assert hop.fact not in published
                assert hop.reason not in published


class TestTheCurationRules:
    def test_there_are_exactly_five_presets(self) -> None:
        assert len(PRESETS) == 5

    def test_the_ids_are_p1_through_p5_and_distinct(self) -> None:
        assert [preset.id for preset in PRESETS] == ["p1", "p2", "p3", "p4", "p5"]
        assert len(PRESET_IDS) == 5

    def test_every_preset_chains_at_least_two_facts(self) -> None:
        """The defining property: a later query cannot be written until the
        earlier result has been read. One hop is not a ReAct demonstration."""
        for preset in PRESETS:
            assert preset.hop_count >= 2, preset.id

    def test_every_preset_has_a_hop_that_defeats_memorised_knowledge(self) -> None:
        """Without one, the model can answer from training and the trace shows
        no observation doing any work -- the feature's first-named failure."""
        for preset in PRESETS:
            defeating = [
                hop
                for hop in preset.expected_hops
                if hop.source in (HopSource.TIME_VARIABLE, HopSource.OBSCURE)
            ]
            assert defeating, preset.id

    def test_a_hop_that_needs_observation_is_never_marked_parametric(self) -> None:
        """The two fields would otherwise be free to contradict each other,
        and the contradiction would read as a curation decision."""
        for preset in PRESETS:
            for hop in preset.expected_hops:
                if hop.requires_observation:
                    assert hop.source is not HopSource.PARAMETRIC, (
                        f"{preset.id} hop {hop.index}"
                    )

    def test_the_hops_are_numbered_in_order_from_one(self) -> None:
        for preset in PRESETS:
            assert [hop.index for hop in preset.expected_hops] == list(
                range(1, preset.hop_count + 1)
            )

    def test_exactly_three_presets_are_guaranteed_fully_observed(self) -> None:
        """p1-p3 are the demonstrations that every hop comes from an
        observation; p4 and p5 are the approachable entry points where the
        model may legitimately state hop 1 from its own knowledge."""
        guaranteed = [
            preset.id for preset in PRESETS if preset.guaranteed_fully_observed
        ]

        assert guaranteed == ["p1", "p2", "p3"]

    def test_a_guaranteed_preset_needs_an_observation_for_every_hop(self) -> None:
        """The flag is a claim, so something checks it. A preset marked
        guaranteed whose first hop is parametric would be the app promising a
        fully observed demonstration it cannot deliver."""
        for preset in PRESETS:
            if not preset.guaranteed_fully_observed:
                continue
            assert all(hop.requires_observation for hop in preset.expected_hops), (
                preset.id
            )

    def test_every_question_is_distinct_and_non_empty(self) -> None:
        assert len(PRESET_QUESTIONS) == 5
        for preset in PRESETS:
            assert preset.question.strip()

    def test_a_chip_label_does_not_give_away_a_hop(self) -> None:
        """p5's chip says 'a famous director', not the director's name --
        naming them would resolve hop 1 before the run began."""
        for preset in PRESETS:
            assert preset.label != preset.question
            assert len(preset.label) < len(preset.question)


class TestLookup:
    def test_a_known_id_resolves(self) -> None:
        preset = get_preset("p3")

        assert preset is not None
        assert preset.hop_count == 3

    def test_an_unknown_id_is_none_rather_than_a_default(self) -> None:
        """A silent fallback to the first preset would run a question the
        visitor did not choose."""
        assert get_preset("p99") is None
        assert get_preset("") is None
