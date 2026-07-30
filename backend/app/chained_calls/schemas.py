# Built with Spec4 AI - https://spec4.ai
"""Pydantic request/response models for the chained_calls_example_app endpoints.

The response shape is the capability's Schema notes taken literally --
`intermediate_output` and `final_output`, each a `{role, text}` block -- with
two additions that carry information the model genuinely produced (the draft's
`title`, the critique's `quoted_detail`) and the request-level fields the
failure modes require (`status`, `notice`, `quality_signal`).

`role` is populated by the server from the prompt that was sent, never by the
model. Which persona produced a block is a fact about which call ran, so asking
a model to assert it would be a claim with nothing behind it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: The two terminal states of a request. "critique_failed" is a 200, not an
#: error status: call 1 succeeded and its output is in the body, which is
#: precisely what the capability's escalation path requires be shown.
ChainStatus = Literal["complete", "critique_failed"]


class ChainedCallsRequest(BaseModel):
    """Request body for POST /api/chained-calls/generate."""

    story_prompt: str


class IntermediateOutputIn(BaseModel):
    """The already-generated story, handed back for a critique-only retry.

    The story travels through the client because nothing about it is stored
    server-side -- that is the capability's privacy requirement, and this is the
    cost of honouring it. `role` is accepted and ignored: the server decides
    which persona runs, and echoing a client-supplied role back as if it were
    established would be the same unverified claim the field is stamped to
    avoid.
    """

    title: str = ""
    text: str
    role: str | None = None


class RetryCritiqueRequest(BaseModel):
    """Request body for POST /api/chained-calls/retry-critique."""

    intermediate_output: IntermediateOutputIn


class IntermediateOutput(BaseModel):
    """Call 1's labeled output block."""

    role: Literal["struggling_writer"] = "struggling_writer"
    title: str
    text: str


class FinalOutput(BaseModel):
    """Call 2's labeled output block.

    Attributes:
        role: Stamped by the server.
        text: The critique.
        quoted_detail: The specific phrase from the story the critic anchored
            itself to. Returned rather than kept internal so the UI can show
            what the second call actually took from the first -- the visible
            evidence that the hand-off happened.
    """

    role: Literal["harsh_critic"] = "harsh_critic"
    text: str
    quoted_detail: str


class QualitySignal(BaseModel):
    """The automated check on whether the critique read the story.

    A signal, not a verdict. It establishes that the quoted detail is present
    in the story; it establishes nothing about whether the critique is apt.
    Any surface rendering this must say which of the two it is.
    """

    quoted_detail_found: bool
    match_ratio: float
    references_story: bool


class ChainStep(BaseModel):
    """One declared step of the chain, described before it runs.

    Serves the feature's success criterion that the visitor is told what each
    call is meant to do *before* submitting -- so the roles come from the
    server that will run them rather than from copy the frontend keeps in sync
    by hand.
    """

    position: int
    role: str
    label: str
    description: str


class ChainPlanResponse(BaseModel):
    """Response body for GET /api/chained-calls/plan."""

    steps: list[ChainStep]
    chain_length: int
    #: Why this demo stops at two calls. The feature requires the visitor be
    #: told that the limit is a budget decision and not a property of the
    #: pattern, and the sentence lives here so both statements come from one
    #: place.
    length_note: str


class ChainedCallsResponse(BaseModel):
    """Response body for both chained-calls POST endpoints.

    Attributes:
        status: "complete", or "critique_failed" when call 2 did not finish.
        intermediate_output: Call 1's block. Always present.
        final_output: Call 2's block, or None when it failed.
        quality_signal: The overlap check, or None when there is no critique.
        notice: Plain-language explanation of a partial result, or None.
        writer_model: The slug that served call 1, read off its response.
        critic_model: The slug that served call 2, or None.
    """

    status: ChainStatus
    intermediate_output: IntermediateOutput
    final_output: FinalOutput | None = None
    quality_signal: QualitySignal | None = None
    notice: str | None = None
    writer_model: str = Field(default="unknown")
    critic_model: str | None = None
