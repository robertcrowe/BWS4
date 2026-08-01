# Built with Spec4 AI - https://spec4.ai
"""The orchestrated-subagents roster endpoint and the config it serves.

The endpoint itself is trivial -- two module constants, no model, no database --
so what is actually worth pinning is the *config*, because later phases build on
assumptions about it that nothing else will check:

- the coordinator's delegation is validated against these ids, so a typo here
  would reject every valid decision
- the preset set is the offline key for whether the coordinator reads the
  question at all, which needs several distinct pairings to be measurable
- the roster's four entries must be four modes of reasoning, not four topics,
  or the merge step has nothing to reconcile

`TestClient(app)` is used without its context manager so the lifespan never
runs: entering it would load sentence-transformers for a route that touches
neither a model nor a database.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.orchestrated.presets import CURATED_PRESETS, DISTINCT_PAIRINGS
from backend.app.orchestrated.roster import (
    ROSTER_IDS,
    SPECIALIST_ROSTER_CONFIG,
    SPECIALISTS_PER_RUN,
)

client = TestClient(app)

EXPECTED_IDS = {"technical", "financial", "historical", "practical"}


def _roster() -> dict:
    response = client.get("/api/orchestrated/roster")
    assert response.status_code == 200
    return response.json()


class TestTheRosterEndpoint:
    def test_it_returns_exactly_the_four_specified_specialists(self) -> None:
        body = _roster()

        assert len(body["specialists"]) == 4
        assert {item["id"] for item in body["specialists"]} == EXPECTED_IDS

    def test_every_specialist_id_is_unique(self) -> None:
        ids = [item["id"] for item in _roster()["specialists"]]

        assert len(ids) == len(set(ids))

    def test_each_specialist_carries_the_four_wire_fields(self) -> None:
        # camelCase on purpose: these are the design entity names and the
        # TypeScript client reads them directly.
        for item in _roster()["specialists"]:
            assert set(item) == {"id", "displayName", "scope", "color"}
            assert all(str(value).strip() for value in item.values())

    def test_it_does_not_publish_the_prompt_fragments(self) -> None:
        """The instructions that govern a specialist stay server-side.

        They are how a specialist is kept in its lane; publishing them would
        hand anyone shaping a question the exact text to work around.
        """
        body = _roster()
        serialised = str(body)

        for entry in SPECIALIST_ROSTER_CONFIG:
            assert entry.system_prompt_fragment not in serialised
            assert entry.angle_exclusion not in serialised

    def test_it_returns_the_curated_presets(self) -> None:
        body = _roster()

        assert len(body["presets"]) == len(CURATED_PRESETS)
        for item in body["presets"]:
            assert set(item) == {"id", "text", "expectedPairing"}


class TestTheConfigItServes:
    def test_every_preset_pairing_references_only_roster_ids(self) -> None:
        """A label naming a specialist that does not exist is unusable.

        The pairing is the offline eval's key; if it can point at an id the
        coordinator could never return, the eval measures nothing.
        """
        for preset in CURATED_PRESETS:
            assert set(preset.expected_pairing) <= ROSTER_IDS, preset.preset_id

    def test_every_preset_pairs_two_distinct_specialists(self) -> None:
        for preset in CURATED_PRESETS:
            assert len(preset.expected_pairing) == SPECIALISTS_PER_RUN
            assert len(set(preset.expected_pairing)) == SPECIALISTS_PER_RUN, (
                preset.preset_id
            )

    def test_the_preset_set_spans_at_least_four_distinct_pairings(self) -> None:
        """Different presets must lead to visibly different pairings.

        A coordinator returning the same two specialists for everything would
        satisfy every runtime rule and have stopped demonstrating delegation.
        A preset set that only ever expected one pairing could not tell.
        """
        assert len(DISTINCT_PAIRINGS) >= 4

    def test_every_specialist_appears_in_more_than_one_preset(self) -> None:
        # One appearance cannot distinguish "the coordinator ignores this
        # specialist" from "that single question was labelled optimistically".
        counts = {
            specialist_id: sum(
                1
                for preset in CURATED_PRESETS
                if specialist_id in preset.expected_pairing
            )
            for specialist_id in ROSTER_IDS
        }

        assert all(count >= 2 for count in counts.values()), counts

    def test_preset_ids_are_unique(self) -> None:
        ids = [preset.preset_id for preset in CURATED_PRESETS]

        assert len(ids) == len(set(ids))

    def test_each_specialist_states_a_distinct_cognitive_mode(self) -> None:
        """Four modes of reasoning, not four topics.

        The roster is what makes this orchestration rather than routing: split
        by subject, two specialists asked the same question return overlapping
        answers and the merge has nothing to reconcile. This checks the
        structural half of that -- every entry carries its own instruction and
        its own exclusion clause, and none of them are shared.
        """
        fragments = [entry.system_prompt_fragment for entry in SPECIALIST_ROSTER_CONFIG]
        exclusions = [entry.angle_exclusion for entry in SPECIALIST_ROSTER_CONFIG]

        assert len(set(fragments)) == 4
        assert len(set(exclusions)) == 4
        assert all(fragment.strip() for fragment in fragments)
        assert all(exclusion.strip() for exclusion in exclusions)

    def test_every_specialist_has_keyword_affinities_for_the_fallback(self) -> None:
        for entry in SPECIALIST_ROSTER_CONFIG:
            assert entry.keyword_affinities, entry.id
            assert len(set(entry.keyword_affinities)) == len(entry.keyword_affinities)

    def test_the_roster_ids_constant_matches_the_roster(self) -> None:
        # Derived rather than restated, so the validator and the roster cannot
        # disagree about which names are allowed.
        assert ROSTER_IDS == {entry.id for entry in SPECIALIST_ROSTER_CONFIG}
        assert ROSTER_IDS == EXPECTED_IDS


class TestRoutingUnchanged:
    def test_mounting_the_new_router_left_the_other_apps_reachable(self) -> None:
        """The seventh router must not displace the six already mounted."""
        paths = set(app.openapi()["paths"])

        assert {
            "/health",
            "/api/rag/ask",
            "/api/embeddings/place",
            "/api/single-call/generate",
            "/api/chained-calls/generate",
            "/api/planning/plan",
            "/api/orchestrated/roster",
        } <= paths
