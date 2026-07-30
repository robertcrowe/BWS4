# Built with Spec4 AI - https://spec4.ai
"""Unit tests for the chained-calls app's personas and its overlap signal.

The lane itself -- provider adapters, chain resolution, cooldowns, probe
exclusions -- moved to `services/agent_runtime.py` and is covered by
`test_agent_runtime.py`. What remains here is what belongs to *this app*: that
its personas load and carry their specified tone and safety constraints, that
its role labels match the wire contract, and that the overlap signal behaves.
Nothing in this file calls a model or touches a database.
"""

from __future__ import annotations

from backend.app.chained_calls import overlap
from backend.app.chained_calls.pipeline import (
    CHAIN_LENGTH,
    CRITIC_PROMPT_VERSION,
    ROLE_CRITIC,
    ROLE_WRITER,
    WRITER_PROMPT_VERSION,
)
from backend.app.chained_calls.prompt_loader import load_persona_prompt


def test_the_chain_length_is_two() -> None:
    """The demo's budget decision, stated once so the UI can quote it."""
    assert CHAIN_LENGTH == 2


def test_both_persona_prompts_load_and_carry_their_tone_constraints() -> None:
    """Persona bleed is mitigated at the prompt level, so the prompts must say so."""
    writer = load_persona_prompt(WRITER_PROMPT_VERSION).lower()
    critic = load_persona_prompt(CRITIC_PROMPT_VERSION).lower()

    assert "self-doubting" in writer and "hedg" in writer
    assert "exemplars" in writer, "few-shot exemplars are the specified mitigation"

    assert "blunt" in critic and "dismissive" in critic
    assert "exemplars" in critic
    # The critique-does-not-reference-the-story failure mode's mitigation.
    assert "quote" in critic and "quoted_detail" in critic
    # The safety constraint, enforced by prompt design rather than a filter.
    assert "protected characteristic" in critic


def test_the_role_labels_are_the_capabilitys_declared_values() -> None:
    """The wire contract names these exact strings."""
    assert ROLE_WRITER == "struggling_writer"
    assert ROLE_CRITIC == "harsh_critic"


# --- the overlap signal -------------------------------------------------------

_STORY = (
    "The lighthouse keeper found a bottle wedged in the rocks. Inside was a "
    "note in handwriting he almost recognised. He read it twice and then, "
    "maybe foolishly, threw it back."
)


def test_a_verbatim_quote_is_found() -> None:
    signal = overlap.measure(_STORY, "a bottle wedged in the rocks")
    assert signal.quoted_detail_found
    assert signal.references_story
    assert signal.match_ratio == 1.0


def test_punctuation_and_line_wrapping_do_not_defeat_the_match() -> None:
    """A model re-quoting across a line break is quoting, not inventing."""
    signal = overlap.measure(_STORY, "  He read it TWICE -- and then,\n maybe foolishly ")
    assert signal.quoted_detail_found


def test_a_close_paraphrase_still_counts_as_anchored() -> None:
    """The capability asks for a quote *or* a paraphrase, so both must pass."""
    signal = overlap.measure(_STORY, "the keeper threw the note back into the rocks")
    assert not signal.quoted_detail_found
    assert signal.match_ratio >= overlap.STRONG_MATCH_RATIO
    assert signal.references_story


def test_generic_commentary_does_not_count_as_anchored() -> None:
    """The failure mode this signal exists to catch: a critique of no story."""
    signal = overlap.measure(_STORY, "the prose is flat and the ending is unearned")
    assert not signal.quoted_detail_found
    assert not signal.references_story


def test_a_blank_quoted_detail_scores_zero_rather_than_raising() -> None:
    """The critic returning nothing to check is a result, not a crash."""
    signal = overlap.measure(_STORY, "   ")
    assert signal == overlap.OverlapSignal(
        quoted_detail_found=False, match_ratio=0.0, references_story=False
    )
