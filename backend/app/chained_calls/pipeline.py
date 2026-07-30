# Built with Spec4 AI - https://spec4.ai
"""The chained-calls app's personas, typed outputs, and step invocation.

Everything here is specific to *this* example: which personas exist, what shape
their outputs take, and how many calls the demo makes. The machinery underneath
-- constructing a cross-provider PydanticAI model, walking the fallback chain,
benching withdrawn slugs, reading the served model off the response -- lives in
`services/agent_runtime.py`, because the next example app that coordinates typed
agents needs all of it and none of this.

That split is what "pipeline_runner infrastructure" means in practice: the
runner is framework-level and shared; the pipeline is the app's.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.chained_calls.prompt_loader import load_persona_prompt
from backend.app.services import agent_runtime
from backend.app.services.agent_runtime import AgentLaneError, StepResult

#: The persona template versions this build ships. Bumped by adding
#: `writer_v2.md` alongside `writer_v1.md`, never by editing a shipped file:
#: changing a persona changes what a past output can be reproduced from.
WRITER_PROMPT_VERSION = "writer_v1"
CRITIC_PROMPT_VERSION = "critic_v1"

#: Role labels for the two steps. These are stamped by the server from the
#: prompt that was sent, and are deliberately **not** asked of the model. The
#: role is a fact about which call ran, so having the model assert it would be
#: an unverified claim dressed up as structured output -- the exact pattern
#: this project has had to remove three times.
ROLE_WRITER = "struggling_writer"
ROLE_CRITIC = "harsh_critic"

#: The chain's fixed length. Two calls, always, to conserve a shared free tier.
#: The *pattern* has no such limit and the UI says so; this constant is the
#: demo's budget decision, not a property of chained calls.
CHAIN_LENGTH = 2

#: How the writer's output is framed as the critic's input.
#:
#: The story travels in the **user** message, not in the critic's system
#: instructions. Two reasons, and both matter: it is the most literal possible
#: demonstration of the pattern (call 2's user message *is* call 1's output),
#: and it keeps model-generated text -- which is downstream of visitor text --
#: out of the system role, where instructions carry the most weight.
CRITIC_INPUT_TEMPLATE = """\
Title: {title}

{story}"""


class StoryDraft(BaseModel):
    """Call 1's typed output: the struggling writer's draft.

    Only fields the model genuinely authors live here. The role label does not,
    because the server already knows it.
    """

    title: str = Field(description="A tentative, hedged title for the story.")
    story: str = Field(description="The story itself, 150-250 words.")


class StoryCritique(BaseModel):
    """Call 2's typed output: the harsh critic's verdict on that draft.

    `quoted_detail` is the load-bearing field. The capability's named failure
    mode is a generic critique that could have been written without reading the
    story, and asking for the specific detail *as its own field* is what makes
    that failure mechanically checkable afterwards (see `overlap.py`) instead
    of only visible to a human reading both blocks.
    """

    quoted_detail: str = Field(
        description=(
            "One short phrase, image, or plot beat taken from the story, quoted "
            "or closely paraphrased."
        )
    )
    critique: str = Field(description="The critique itself, 250 words or fewer.")


async def run_step[T: BaseModel](
    *,
    role: str,
    prompt_version: str,
    user_prompt: str,
    output_type: type[T],
) -> StepResult[T]:
    """Run one persona's call through the shared PydanticAI lane.

    A thin adapter, and deliberately so: it resolves a versioned persona file to
    the agent's instructions and hands everything else to
    `agent_runtime.run_typed_step`. Nothing about failover, providers, or the
    model chain is decided here.

    Google-style docstring per project convention.

    Args:
        role: ROLE_WRITER or ROLE_CRITIC. Used as the step's label on logs and
            on the failure raised; it is not sent to the model.
        prompt_version: The persona template to load as system instructions.
        user_prompt: The call's user message -- the visitor's idea for the
            writer, the writer's finished draft for the critic.
        output_type: The Pydantic model the response is bound to.

    Returns:
        The validated output and the slug that served it.

    Raises:
        AgentLaneError: If the call could not be completed.
    """
    return await agent_runtime.run_typed_step(
        label=role,
        instructions=load_persona_prompt(prompt_version),
        user_prompt=user_prompt,
        output_type=output_type,
    )


__all__ = [
    "AgentLaneError",
    "CHAIN_LENGTH",
    "CRITIC_INPUT_TEMPLATE",
    "CRITIC_PROMPT_VERSION",
    "ROLE_CRITIC",
    "ROLE_WRITER",
    "StepResult",
    "StoryCritique",
    "StoryDraft",
    "WRITER_PROMPT_VERSION",
    "run_step",
]
