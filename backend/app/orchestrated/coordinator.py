# Built with Spec4 AI - https://spec4.ai
"""The coordinator's delegation turn: one model call, one draft decision.

Deliberately thin. It renders a prompt, asks for a typed draft, and returns it
unchecked -- validation and repair belong to `validator.py`, which is pure and
therefore cannot quietly turn a fix into a second model call.

The roster reaches the model as *data in the prompt* rather than as prose baked
into the template, so adding a fifth specialist later is a config change. What
does not reach the model is any freedom over the ids: `SpecialistId` is an enum
in the output schema, so an off-roster name is not expressible however the
question is worded.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.orchestrated.roster import SPECIALIST_ROSTER_CONFIG
from backend.app.orchestrated.runtime import RunBudget, run_agent_step
from backend.app.orchestrated.schemas import CoordinatorDraft
from backend.app.services.agent_runtime import StepResult
from backend.app.services.prompt_loader import load_prompt
from backend.app.services.untrusted import untrusted_block

PROMPTS_DIR = Path(__file__).parent / "prompts"

DELEGATION_PROMPT_VERSION = "delegation_v1"

_USER_TEMPLATE = """Roster of available specialists:
{roster}

{question_block}"""


def render_roster() -> str:
    """Render the roster as the coordinator sees it.

    The scope line and the cognitive mode both travel, because choosing between
    modes of reasoning is the decision being asked for -- a list of display
    names alone would make it a guess. The angle-exclusion clauses stay out:
    they instruct the *specialists*, and the coordinator's job is to write that
    boundary in its own words.

    Returns:
        One block per specialist, in roster order.
    """
    return "\n\n".join(
        f"- id: {entry.id}\n"
        f"  name: {entry.display_name}\n"
        f"  scope: {entry.scope}\n"
        f"  mode: {entry.system_prompt_fragment}"
        for entry in SPECIALIST_ROSTER_CONFIG
    )


async def decide(question: str, *, budget: RunBudget) -> StepResult[CoordinatorDraft]:
    """Ask the coordinator which two specialists should answer.

    Google-style docstring per project convention.

    Args:
        question: The visitor's question. Wrapped in an untrusted-data block
            before it reaches the model -- it is content to be classified, and
            never an instruction to the coordinator.
        budget: The run's provider-request counter, charged per request rather
            than per step so a framework-level retry cannot slip past the cap.

    Returns:
        The unvalidated draft and the slug that served it. Unvalidated on
        purpose: `validator.validate_and_repair()` is the only thing that turns
        a draft into a dispatchable decision, and it is pure.

    Raises:
        AgentLaneError: If every model in the chain failed.
        RunBudgetExceededError: If the run has no requests left.
    """
    return await run_agent_step(
        label="coordinator-delegation",
        instructions=load_prompt(PROMPTS_DIR, DELEGATION_PROMPT_VERSION),
        user_prompt=_USER_TEMPLATE.format(
            roster=render_roster(),
            question_block=untrusted_block("visitor question", question),
        ),
        output_type=CoordinatorDraft,
        budget=budget,
    )
