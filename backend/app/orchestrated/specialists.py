# Built with Spec4 AI - https://spec4.ai
"""The four specialists: one prompt template, four modes, and no tools at all.

A specialist is not a class hierarchy here. All four share one prompt template
(`prompts/specialist_v1.md`) and differ only by the two strings the roster
already carries -- the cognitive mode and the angle-exclusion clause -- so
"adding a specialist" is a roster entry rather than a module. `SPECIALIST_AGENTS`
is the registry the dispatcher selects from **by id**, never by import, which is
what keeps the coordinator's enum-constrained choice the only thing that decides
who runs.

## Zero tools, and the reason is not only privacy

`run_typed_step` is called with no `tools` argument, so PydanticAI registers
none and the model is offered nothing but its output type. The specification
requires it for egress -- a specialist that cannot call anything cannot leak the
question anywhere -- but it also holds the run's arithmetic together. A tool-
using step takes an unpredictable number of provider requests (the planning
app's research steps take two or three), and this run's ceiling of four leaves
exactly one request per specialist. Tools would make the ceiling unmeetable
rather than merely tight.

## The brief is an instruction; the question is data

These are handled differently on purpose. The brief is what this specialist was
asked to do, so it belongs in the instructions. The question is visitor-authored
text to be answered, so it goes in a delimited untrusted block the prompt tells
the model never to take orders from.

The brief reaches this module from the client on the dispatch request, so it is
not fully trusted either -- see `service.confirm_dispatch`, which re-validates
the decision's structure and bounds the brief's length before anything is run.
What is done here is the remaining half: its delimiters are neutralised, so a
brief cannot forge the framing around the question.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import structlog

from backend.app.orchestrated.roster import SPECIALIST_ROSTER_CONFIG, RosterEntry
from backend.app.orchestrated.runtime import RunBudget, run_agent_step
from backend.app.orchestrated.schemas import (
    Brief,
    SpecialistAnswer,
    SpecialistId,
    SpecialistStatus,
    SubagentResult,
)
from backend.app.services.agent_runtime import StepResult
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import neutralise_delimiters, untrusted_block

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).parent / "prompts"

SPECIALIST_PROMPT_VERSION = "specialist_v1"

#: Key points a specialist may contribute, per the capability's schema.
#:
#: Applied here rather than in the output model: enforcing it in the schema
#: would make a model returning two key points a PydanticAI validation failure,
#: which re-prompts and spends a request the run cannot afford.
MIN_KEY_POINTS: Final[int] = 3
MAX_KEY_POINTS: Final[int] = 5

_USER_TEMPLATE = """Your brief for this question:
{brief}

{question_block}"""


class SpecialistAgent:
    """One roster member, ready to answer a brief.

    Holds no model and no client: the model is resolved per call from the
    shared registry, so a slug benched between two runs is skipped by the
    second without this object knowing anything about it.
    """

    def __init__(self, entry: RosterEntry) -> None:
        """Bind an agent to its roster entry.

        Args:
            entry: The roster entry supplying this specialist's mode and its
                angle-exclusion clause.
        """
        self.entry = entry
        self.specialist_id = SpecialistId(entry.id)

    def instructions(self) -> str:
        """Compose this specialist's system prompt.

        Three parts, in the order a reader would want them: the shared template
        that defines what a specialist is, then this one's mode of reasoning,
        then what it must leave to others. Composed at call time rather than
        baked into four prompt files, so a change to the shared rules reaches
        all four at once.

        Returns:
            The full system prompt.
        """
        return (
            f"{load_prompt(PROMPTS_DIR, SPECIALIST_PROMPT_VERSION)}\n\n"
            f"## Your mode of reasoning\n\n{self.entry.system_prompt_fragment}\n\n"
            f"## Out of scope for you\n\n{self.entry.angle_exclusion}"
        )

    async def answer(
        self, *, brief: str, question: str, budget: RunBudget
    ) -> StepResult[SpecialistAnswer]:
        """Run this specialist's single model call.

        No `tools` argument is passed, so the agent is built with none. That is
        the whole implementation of the no-egress requirement -- there is no
        list to accidentally add to later without noticing.

        Args:
            brief: What this specialist was asked to cover.
            question: The visitor's question, placed in an untrusted block.
            budget: The run's provider-request counter.

        Returns:
            The model's answer and the slug that served it.

        Raises:
            AgentLaneError: If every model in the chain failed.
            RunBudgetExceededError: If the run has no requests left.
        """
        return await run_agent_step(
            label=f"specialist-{self.entry.id}",
            instructions=self.instructions(),
            user_prompt=_USER_TEMPLATE.format(
                brief=neutralise_delimiters(brief),
                question_block=untrusted_block("visitor question", question),
            ),
            output_type=SpecialistAnswer,
            budget=budget,
        )


#: The registry the dispatcher selects from, keyed by roster id.
#:
#: Built from the roster rather than written out, so a fifth specialist is one
#: roster entry and no edit here. Selection by id is the tool-protocol
#: strategy's explicit requirement: the coordinator names an id, and nothing
#: imports a specialist directly.
SPECIALIST_AGENTS: Final[dict[SpecialistId, SpecialistAgent]] = {
    SpecialistId(entry.id): SpecialistAgent(entry) for entry in SPECIALIST_ROSTER_CONFIG
}


def get_specialist(specialist_id: SpecialistId) -> SpecialistAgent:
    """Look up a specialist by id.

    Args:
        specialist_id: The roster id to dispatch to.

    Returns:
        The agent for that id.

    Raises:
        KeyError: If no specialist has that id. A raise rather than None,
            unlike `roster.find()`: the id has already passed the validator by
            the time anything gets here, so a miss is a programming error
            rather than a model returning something unexpected.
    """
    return SPECIALIST_AGENTS[specialist_id]


def trim_key_points(points: list[str]) -> list[str]:
    """Bound a specialist's key points to the range the capability specifies.

    Truncates a long list and drops blanks; does **not** pad a short one. There
    is nothing to pad with that a model did not write, and inventing a key point
    to satisfy a count would be putting words in the specialist's mouth. A
    short list is reported as-is and the telemetry records it.

    Args:
        points: The key points as the model returned them.

    Returns:
        At most `MAX_KEY_POINTS` non-empty points, in order.
    """
    return [point.strip() for point in points if point.strip()][:MAX_KEY_POINTS]


def build_result(brief: Brief, step: StepResult[SpecialistAnswer]) -> SubagentResult:
    """Turn one completed specialist call into its column's result.

    Args:
        brief: The brief this specialist was given, which supplies the id.
        step: The completed model call.

    Returns:
        The result, with `specialist_id` and `status` stamped from what the
        server knows rather than from anything the model claimed.
    """
    points = trim_key_points(step.output.key_points)
    if len(points) < MIN_KEY_POINTS:
        logger.info(
            "orchestrated_specialist_returned_few_key_points",
            specialist_id=brief.specialist_id.value,
            count=len(points),
            model=step.model,
        )
    return SubagentResult(
        specialist_id=brief.specialist_id,
        status=SpecialistStatus.OK,
        answer=step.output.answer,
        key_points=points,
    )
