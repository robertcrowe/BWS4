# Built with Spec4 AI - https://spec4.ai
"""Telling an agent what day it is, so "recent" means something.

A model has no clock. Left to itself it answers "what is recent?" from the only
temporal anchor it has -- the end of its training data -- and that anchor is
wrong by however long ago the model was trained.

## The failure this exists to prevent, observed live

The tool-use agent was asked *"Recent breakthroughs in agentic AI frameworks"*
and wrote itself the search query:

    recent breakthroughs in agentic AI frameworks 2024

It was 2026. The search then worked perfectly and returned exactly what was
asked for: 2024 papers. Nothing in the pipeline was broken -- the agent asked
the wrong question, because nobody had told it the date, and a search is only
as current as its query.

That failure is invisible from the outside. The trace shows a real tool call,
real results and a grounded answer; only the year buried in the model's own
query gives it away. It reads as "the demo is answering from training data"
when the truth is subtler and worse: the demo *searched* its training data's
idea of the present.

## Why this is framework-level

Every app whose model composes a search query has the same exposure -- the
tool-use agent and the planning agent's research steps today, anything that
searches tomorrow. It lives in `services/` for the same reason `web_search.py`
and `message_bus.py` do: the first caller is not the owner.

## What it deliberately does not do

It does not tell the model what to conclude, and it does not filter anything.
It supplies one fact the model cannot know and states the consequence for query
writing. Deciding what is worth searching for stays the model's job -- that is
the pattern this example exists to demonstrate.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

#: Months spelled out, so there is no ambiguity between day-first and
#: month-first orderings for a model reading the line.
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def today_utc() -> date:
    """Return today's date in UTC.

    UTC rather than local time so the answer does not depend on where the
    process happens to be running -- the same reason every usage window in this
    project is UTC.

    Returns:
        Today's date.
    """
    return datetime.now(UTC).date()


def current_date_note(today: date | None = None) -> str:
    """Build the dated preamble to prepend to a search-capable agent's prompt.

    Args:
        today: The date to state. Defaults to today in UTC; injectable so a
            test can pin it rather than asserting against a moving clock.

    Returns:
        A short block naming the date and spelling out what it means for query
        writing.
    """
    day = today or today_utc()
    written = f"{day.day} {_MONTHS[day.month - 1]} {day.year}"

    return (
        f"## Today's date is {written}\n"
        "\n"
        "Your training data ends well before this. When a question says "
        '"recent", "latest", "current" or "now", it means relative to today\'s '
        "date above, not to the most recent period you remember.\n"
        "\n"
        "**Do not put a year from your training data into a search query.** If "
        f"a year would help, use {day.year}. Better still, write the query "
        "without a year and let the search rank by relevance -- the results "
        "carry their own publication dates, and you should weigh those rather "
        "than assume the newest thing you know of is the newest thing there is."
    )


def with_current_date(instructions: str, today: date | None = None) -> str:
    """Prepend the dated preamble to an agent's system prompt.

    Prepended rather than appended: it is context the rest of the prompt is
    read against, and a model that has already been told how to behave is less
    likely to revisit that instruction on the strength of a footnote.

    Args:
        instructions: The agent's system prompt.
        today: The date to state. Defaults to today in UTC.

    Returns:
        The prompt with the date block in front of it.
    """
    return f"{current_date_note(today)}\n\n{instructions}"
