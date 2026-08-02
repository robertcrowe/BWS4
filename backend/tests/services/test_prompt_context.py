# Built with Spec4 AI - https://spec4.ai
"""The dated preamble, and the two prompts that must carry it.

The failure this guards against was reported from the running app: asked for
*"Recent breakthroughs in agentic AI frameworks"*, the tool-use agent wrote
itself the query `recent breakthroughs in agentic AI frameworks 2024` -- in
2026. The search then worked perfectly and returned exactly what was asked for.

That is why the assertions here are on the **wiring** as much as the text. A
prompt helper nobody calls fixes nothing, and the defect is invisible in the
trace: a real tool call, real results, a grounded answer, and one wrong year
buried in a query the model wrote for itself.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime

from backend.app.services.prompt_context import (
    current_date_note,
    today_utc,
    with_current_date,
)

PINNED = date(2026, 8, 2)


class TestTheNote:
    def test_it_states_the_date_unambiguously(self) -> None:
        """Month spelled out: `02/08/2026` reads as two different days
        depending on which side of the Atlantic the reader learned dates on,
        and a model is no better placed to guess."""
        note = current_date_note(PINNED)

        assert "2 August 2026" in note
        assert "02/08" not in note and "08/02" not in note

    def test_it_names_the_year_to_use_when_a_year_is_wanted(self) -> None:
        note = current_date_note(PINNED)

        assert "use 2026" in note

    def test_it_forbids_a_training_cutoff_year_in_a_query(self) -> None:
        """The exact reported failure, addressed by name."""
        note = current_date_note(PINNED).lower()

        assert "do not put a year from your training data into a search query" in note

    def test_it_redefines_the_words_that_caused_the_failure(self) -> None:
        note = current_date_note(PINNED)

        for word in ("recent", "latest", "current", "now"):
            assert f'"{word}"' in note

    def test_it_points_the_model_at_result_dates_rather_than_its_memory(self) -> None:
        """The other half of the fix: results now carry `published_date`, and
        the model is told to weigh those instead of assuming the newest thing
        it remembers is the newest thing there is."""
        note = current_date_note(PINNED)

        assert "publication dates" in note

    def test_it_prescribes_no_conclusion_and_filters_nothing(self) -> None:
        """It supplies a fact the model cannot know. Deciding what is worth
        searching for stays the model's job -- that is the pattern this example
        exists to demonstrate."""
        note = current_date_note(PINNED).lower()

        for overreach in ("you must search", "always search", "ignore results"):
            assert overreach not in note

    def test_the_date_defaults_to_utc_today(self) -> None:
        """UTC rather than local time, so the answer does not depend on where
        the process happens to be running."""
        assert today_utc() == datetime.now(UTC).date()
        assert str(today_utc().year) in current_date_note()


class TestItIsPrepended:
    def test_the_agent_s_own_instructions_follow_the_date(self) -> None:
        """Prepended, not appended: it is context the rest of the prompt is
        read against."""
        combined = with_current_date("BE A GOOD AGENT.", PINNED)

        assert combined.index("2 August 2026") < combined.index("BE A GOOD AGENT.")

    def test_the_original_instructions_survive_intact(self) -> None:
        combined = with_current_date("BE A GOOD AGENT.", PINNED)

        assert "BE A GOOD AGENT." in combined


class TestEveryPromptThatComposesASearchQueryIsDated:
    def test_the_tool_use_agent_dates_its_system_prompt(self) -> None:
        """The app the failure was reported against."""
        from backend.app.tools import agent

        source = inspect.getsource(agent)
        assert 'with_current_date(load_prompt("agent_v1"))' in source

    def test_the_planning_research_step_dates_its_prompt(self) -> None:
        """The other agent in the project that writes search queries. It had
        the same exposure and no report against it yet -- fixing one and not
        the other would leave the same defect waiting."""
        from backend.app.planning import agents as planning_agents

        source = inspect.getsource(planning_agents)
        assert "with_current_date(" in source
        assert "RESEARCH_PROMPT_VERSION" in source

    def test_the_steps_that_never_search_are_left_alone(self) -> None:
        """The planner and synthesis steps compose no query and reach no web,
        so dating them would be noise in a prompt that has no use for it.

        Asserted on the call text itself rather than by index arithmetic around
        the constant -- the first occurrence of each name is in the *import*
        block, which is how the first version of this test fooled itself.
        """
        from backend.app.planning import agents as planning_agents

        source = inspect.getsource(planning_agents)

        assert "load_prompt(PROMPTS_DIR, PLANNER_PROMPT_VERSION)" in source
        assert "load_prompt(PROMPTS_DIR, SYNTHESIS_PROMPT_VERSION)" in source
        wrapped = (
            "with_current_date(\n"
            "            load_prompt(PROMPTS_DIR, RESEARCH_PROMPT_VERSION)"
        )
        assert wrapped in source
