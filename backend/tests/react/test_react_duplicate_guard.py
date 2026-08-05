# Built with Spec4 AI - https://spec4.ai
"""The near-duplicate query guard, asserted in **both** directions.

The phase's named tuning risk is that a single number decides two opposite
failures, and only one of them is visible if you test one way:

- Too **high** and rephrased repeats sail through; the loop circles until the
  budget is gone and the run ends with nothing.
- Too **low** and a genuine follow-up is refused. That is the worse failure and
  the easier one to miss, because hop two of a multi-hop question is *by design*
  closely related to hop one -- a guard tuned by "block anything that looks
  similar" breaks the app outright while every blocking test still passes.

So the file asserts a rephrased repeat is blocked **and** that a real
next-hop query on the same subject is allowed, against the same threshold, using
real embeddings from the shared model. Real vectors rather than hand-authored
ones on purpose: hand-picked numbers would prove the comparison arithmetic works
and say nothing about whether 0.95 is the right place to draw the line, which is
the entire question.
"""

from __future__ import annotations

import pytest

from backend.app.core.config import get_settings
from backend.app.react import duplicate_guard
from backend.app.services.embedding import embed_text

THRESHOLD = get_settings().react_duplicate_similarity_threshold


@pytest.fixture(scope="module")
def issued() -> duplicate_guard.IssuedQueries:
    """A run that has already issued one query, embedded for real."""
    log = duplicate_guard.IssuedQueries()
    query = "most recent country to join the United Nations"
    log.remember(query, embed_text(query))
    return log


def _decide(
    candidate: str, log: duplicate_guard.IssuedQueries, threshold: float = THRESHOLD
) -> duplicate_guard.DuplicateDecision:
    return duplicate_guard.evaluate_query(
        candidate, embed_text(candidate), log, threshold
    )


class TestTheGuardBlocksRepeats:
    def test_the_identical_query_is_refused(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        decision = _decide("most recent country to join the United Nations", issued)

        assert decision.allowed is False
        assert decision.reason == "exact_match"

    def test_punctuation_and_case_do_not_disguise_a_repeat(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """Stage 1's whole job. Caught with certainty and without touching a
        vector, which is why it runs first."""
        decision = _decide("Most Recent Country To Join The United Nations?", issued)

        assert decision.allowed is False
        assert decision.reason == "exact_match"

    def test_a_reordering_with_stopwords_added_is_still_a_repeat(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        decision = _decide(
            "what is the most recent country to join the United Nations", issued
        )

        assert decision.allowed is False
        assert decision.reason == "exact_match"

    def test_a_synonym_swap_stage_one_cannot_see_is_caught_by_similarity(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """The case stage 1 misses by construction: one word changed, so the
        token sets differ and the request does not. Measured at **0.976**
        against the shipped threshold."""
        decision = _decide("most recent nation to join the United Nations", issued)

        assert decision.allowed is False
        assert decision.reason == "near_duplicate"
        assert decision.similarity is not None and decision.similarity >= THRESHOLD

    def test_a_grammatical_restructuring_is_caught(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """ "country most recently joining" against "most recent country to
        join" -- different tokens (`joining`/`join`), same request. Measured at
        0.958."""
        decision = _decide("country most recently joining the United Nations", issued)

        assert decision.allowed is False
        assert decision.reason == "near_duplicate"

    def test_a_blocked_query_names_the_observation_that_covers_it(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        decision = _decide("most recent country to join the United Nations", issued)

        assert decision.matched_index == 1
        assert decision.note is not None

    def test_the_note_says_what_to_do_instead(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """A refusal with no alternative invites the model to rephrase again and
        spend the retry for nothing."""
        decision = _decide("most recent country to join the United Nations", issued)

        assert decision.note is not None
        assert "already issued" in decision.note
        assert "observation 1" in decision.note.lower()
        assert "different" in decision.note or "answer" in decision.note


class TestTheGuardAllowsGenuineFollowUps:
    """The direction that breaks the app when it is wrong, and is easy to miss."""

    def test_the_next_hop_on_the_same_subject_is_allowed(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """Hop two is *about* hop one's answer. A guard that refused this would
        make every multi-hop preset unanswerable while every blocking test above
        still passed."""
        decision = _decide("South Sudan highest mountain elevation", issued)

        assert decision.allowed is True
        assert decision.reason == "novel"

    def test_a_narrowing_follow_up_is_allowed(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        decision = _decide("Kinyeti peak height metres above sea level", issued)

        assert decision.allowed is True

    def test_a_related_but_distinct_question_is_allowed(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        decision = _decide("United Nations Security Council permanent members", issued)

        assert decision.allowed is True

    def test_the_first_query_of_a_run_is_always_allowed(self) -> None:
        empty = duplicate_guard.IssuedQueries()

        decision = _decide("anything at all", empty)

        assert decision.allowed is True
        assert decision.similarity is None

    def test_an_allowed_query_still_reports_how_close_it_came(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """Reported even on the allowed path, so an operator can see the guard's
        margin rather than only its verdicts."""
        decision = _decide("South Sudan highest mountain elevation", issued)

        assert decision.similarity is not None
        assert decision.similarity < THRESHOLD


class TestTheThresholdIsWhatDecides:
    def test_lowering_it_far_enough_would_block_a_genuine_follow_up(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """States the failure the shipped value avoids, so "0.95 is a real
        choice" is something the suite demonstrates rather than asserts. A
        threshold near zero refuses everything -- which is exactly the broken
        demo the tuning risk describes."""
        follow_up = "South Sudan highest mountain elevation"

        assert _decide(follow_up, issued, threshold=THRESHOLD).allowed is True
        assert _decide(follow_up, issued, threshold=0.05).allowed is False

    def test_raising_it_above_one_would_let_every_rephrasing_through(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """The opposite miscalibration. Stage 1 still catches literal repeats,
        which is why the two stages are not interchangeable."""
        rephrased = "most recent nation to join the United Nations"

        assert _decide(rephrased, issued, threshold=THRESHOLD).allowed is False
        assert _decide(rephrased, issued, threshold=1.01).allowed is True

    def test_the_shipped_threshold_is_the_specification_s(self) -> None:
        assert THRESHOLD == 0.95

    def test_a_heavy_rewording_of_the_same_request_is_allowed_through(
        self, issued: duplicate_guard.IssuedQueries
    ) -> None:
        """**The guard's real limit, recorded rather than papered over.**

        "newest member state admitted to the United Nations" asks for exactly
        what the prior query asked for, and it measures **0.714** -- nowhere
        near 0.95, so it is issued. At this threshold the guard catches
        *near*-duplicates and not paraphrases.

        That is the right trade and not a defect to tune away. Everything
        between 0.71 and 0.95 also contains the genuine next hop (measured at
        0.21 here, but a follow-up phrased around the same subject sits much
        closer), so lowering the threshold to catch this case would start
        refusing the queries the multi-hop loop is built on -- and a refused hop
        is unrecoverable, while one extra search costs one of eight.

        The guard therefore *bounds* circling rather than eliminating it. The
        fixed cycle budget is the backstop, and the budget-exhausted card is
        what a run that circles anyway ends in, candidly.
        """
        paraphrase = "newest member state admitted to the United Nations"

        decision = _decide(paraphrase, issued)

        assert decision.allowed is True
        assert decision.similarity is not None
        assert 0.6 < decision.similarity < THRESHOLD


class TestTheGuardIsPure:
    def test_it_reaches_no_database_no_model_and_no_network(self) -> None:
        """Asserted on the module's imports with `ast` rather than by grepping
        prose -- "search" and "model" appear legitimately throughout this
        slice's docstrings, and an earlier version of this check in the
        orchestrated app failed on exactly that."""
        import ast
        from pathlib import Path

        forbidden = {
            "backend.app.db",
            "backend.app.db.session",
            "backend.app.services.web_search",
            "backend.app.services.embedding",
            "backend.app.services.agent_runtime",
            "httpx",
            "sqlalchemy",
        }

        source = Path(duplicate_guard.__file__).read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""}
            else:
                continue
            assert not names & forbidden, f"duplicate_guard imports {names}"

    def test_the_candidate_embedding_is_an_argument(self) -> None:
        """The one thing that makes the module pure. If the guard embedded
        internally it would pull the model in and stop being unit-testable
        against a threshold, which is what the tuning risk needs most."""
        import inspect

        params = inspect.signature(duplicate_guard.evaluate_query).parameters

        assert "candidate_embedding" in params
        assert "threshold" in params


class TestWhatTheRunRemembers:
    def test_only_issued_queries_are_remembered(self) -> None:
        """A refused query was never sent, so nothing should be measured
        against it -- remembering one would let a single rejection poison every
        later cycle's comparison."""
        log = duplicate_guard.IssuedQueries()

        assert len(log) == 0

        log.remember("issued query", embed_text("issued query"))

        assert len(log) == 1
        assert log.queries == ["issued query"]

    def test_the_record_is_per_run_and_starts_empty(self) -> None:
        """Scoped to one run, created at its start and dropped at its end.
        Two fresh logs sharing state would leak one visitor's queries into
        another's run."""
        first = duplicate_guard.IssuedQueries()
        first.remember("q", embed_text("q"))
        second = duplicate_guard.IssuedQueries()

        assert len(second) == 0
        assert second.matrix().size == 0


class TestNormalisation:
    def test_it_drops_grammar_but_keeps_the_words_that_carry_a_hop(self) -> None:
        """ "current", "most", "recent" and "first" are exactly what distinguishes
        one hop's query from another's, so none of them may be a stopword."""
        tokens = duplicate_guard.normalise("the most recent current first winner")

        for word in ("most", "recent", "current", "first", "winner"):
            assert word in tokens
        assert "the" not in tokens

    def test_word_order_does_not_distinguish_two_phrasings(self) -> None:
        assert duplicate_guard.normalise(
            "Tokyo tallest building"
        ) == duplicate_guard.normalise("tallest building Tokyo")

    def test_possessives_and_punctuation_collapse(self) -> None:
        assert duplicate_guard.normalise(
            "Tokyo's skyline!"
        ) == duplicate_guard.normalise("tokyo skyline")
