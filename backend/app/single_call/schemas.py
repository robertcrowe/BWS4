# Built with Spec4 AI - https://spec4.ai
"""Pydantic request/response models for the single_call_example_app endpoints.

The wire contract is written out in full here -- including the fields only
Structured mode uses -- so Phase 2 fills in behaviour rather than
renegotiating the shape. That is the same approach `embeddings/schemas.py`
took with `PlacementResponse` one phase ahead of its implementation.

`SingleCallRequest` mirrors the single_call_generation capability's Inputs
exactly (prompt_text, preset_prompt_id, mode, response_schema) and
`SingleCallResponse` mirrors the `Response` design entity's fields (mode,
plainText, structuredObject, schemaConforming), snake_cased per backend
convention.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator

#: The capability's declared modes. Both are accepted at the wire boundary even
#: though only "plain" is implemented: rejecting "structured" in the schema
#: would render it as a 422 indistinguishable from a typo, when the honest
#: answer is 501 -- a valid request for something not built yet.
SingleCallMode = Literal["plain", "structured"]


class SingleCallRequest(BaseModel):
    """Request body for POST /api/single-call/generate.

    Both prompt inputs are optional individually and required together: the
    capability's failure modes call for blocking submission when there is
    neither free text nor a preset, so that rule is enforced here rather than
    trusted to the client. The frontend blocks it too, which saves a round
    trip -- it does not make this check redundant.
    """

    prompt_text: str | None = None
    preset_prompt_id: str | None = None
    mode: SingleCallMode
    #: Target schema for Structured mode, identified by its `title`.
    #:
    #: The capability's own Inputs describe this as "either fixed per preset or
    #: a default demo schema" -- so the *values* it takes are the curated
    #: schemas, and a client obtains one from GET /api/single-call/presets and
    #: may post it straight back. Resolution is by title, so the round trip
    #: does not require reproducing every nested detail byte-for-byte.
    #:
    #: An arbitrary inline schema is deliberately **not** honoured. Validating
    #: caller-authored JSON Schema on a public unauthenticated endpoint means
    #: accepting user-controlled input into both a provider request and a
    #: validator -- `$ref` resolution and deeply nested definitions are the
    #: obvious hazards -- and no surface in this product sends one. An
    #: unrecognised title is answered with a clear 422 rather than silently
    #: falling back to the demo schema, which would validate a response
    #: against a schema the caller never asked for.
    response_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _require_a_prompt_or_a_preset(self) -> SingleCallRequest:
        """Reject a submission carrying neither free text nor a preset.

        Returns:
            The validated request, with blank-only `prompt_text` normalised to
            None so a preset-only submission is not mistaken for one that
            supplied both.

        Raises:
            ValueError: If neither input is present. FastAPI renders this as a
                422 with the message attached.
        """
        if self.prompt_text is not None and not self.prompt_text.strip():
            self.prompt_text = None

        if self.prompt_text is None and not self.preset_prompt_id:
            raise ValueError("Enter a prompt or choose a preset before submitting.")
        return self


class StructuredRequestOut(BaseModel):
    """The request as actually sent to the model, for the side-by-side display.

    The capability's Outputs require the submitted request and the returned
    response to be shown *together*. This is the server's record of what went
    out -- including the system prompt and the exact schema handed to the
    provider -- rather than the client's reconstruction of what it meant to
    send, which is the only version that can be trusted to match the response
    beside it.
    """

    system_prompt: str
    prompt_text: str
    response_schema: dict[str, Any]
    schema_name: str


class SingleCallResponse(BaseModel):
    """Response body for POST /api/single-call/generate.

    Attributes:
        mode: The mode actually served, so the client renders what it got
            rather than what it asked for.
        plain_text: The model's response in plain mode; None in structured mode.
        structured_object: The parsed structured response (Phase 2); None in
            plain mode.
        schema_conforming: Whether `structured_object` validated against the
            requested schema. **None means no schema check was performed at
            all** -- which is the case for every plain-mode response. False
            would be a different claim: that a check ran and failed. Phase 3's
            UI branches on that distinction to decide whether to show the
            validation-failure state, so the three-valued field is load-bearing
            rather than lazy typing.
        model: The chain slug that served the request, read off the response.
        prompt_text: The prompt as actually sent, echoed back. In structured
            mode the UI must show the submitted request beside the response;
            echoing it means that display comes from the server's record of
            what was sent, not the client's memory of what it typed. When a
            preset was selected this is the preset's text, not the empty box.
        raw_output: The model's unparsed response, present only when a
            structured call failed validation. Surfacing it is the
            capability's specified on_validation_failure behaviour -- a
            visitor learning what constrained decoding does needs to see what
            "didn't conform" actually looked like.
        validation_error: Why validation failed, in readable form.
        structured_request: What was sent, for the side-by-side display.
    """

    mode: SingleCallMode
    plain_text: str | None = None
    structured_object: dict[str, Any] | None = None
    schema_conforming: bool | None = None
    model: str
    prompt_text: str
    raw_output: str | None = None
    validation_error: str | None = None
    structured_request: StructuredRequestOut | None = None


class PresetPromptOut(BaseModel):
    """One preset prompt, as offered to the frontend.

    Carries the `PresetPrompt` design entity's fields (id, label, intent,
    promptText) plus the schema its structured answer must satisfy. The full
    prompt text ships rather than a teaser: the capability's mitigation for
    "user is unsure what a preset will produce" is to show exactly what will be
    sent *before* submission, which a truncated preview cannot do.
    """

    id: str
    label: str
    intent: str
    prompt_text: str
    response_schema: dict[str, Any]


class PresetsResponse(BaseModel):
    """Response body for GET /api/single-call/presets."""

    presets: list[PresetPromptOut] = []
    #: The version of the curated set these presets came from, so a stored
    #: response can be traced to the prompt text that produced it.
    preset_set_version: str
    #: The schema used for structured requests that supply free text instead of
    #: a preset. Shipped alongside so the UI can show a visitor what shape
    #: their own prompt will be held to.
    default_response_schema: dict[str, Any]
