# Built with Spec4 AI - https://spec4.ai
"""Plain-mode single-call generation: validate, reserve, call once, log.

The whole point of the pattern being demonstrated is that there is nothing
between the prompt and the response -- no retrieval, no tool, no second call.
So this module is deliberately thin, and the thinness is the lesson: if
anything ever appears here that inspects the prompt and branches, the example
has stopped demonstrating a single call.

Structured mode is Phase 2. This module exposes plain mode only; the API layer
answers 501 for the rest of the capability's declared surface rather than
pretending it works.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services import shared
from backend.app.services.generation import GenerationServiceError, generate_text
from backend.app.single_call.presets import PresetPrompt, json_schema_for

logger = structlog.get_logger()

#: Tag on every shared_framework_services invocation this app makes, per the
#: ServiceLogEntry domain fields. Matches the directory entry's display name so
#: the cross-app request log reads the same as the landing page.
SINGLE_CALL_APP_NAME = "Single-Call Example App"

#: Longest prompt accepted. Well inside every chain model's context window --
#: this exists to stop a pasted novel from spending the day's token budget in
#: one request, not to constrain what the demo can express.
MAX_PROMPT_CHARS = 4000

#: The one instruction wrapped around the visitor's prompt.
#:
#: Deliberately almost empty. A demonstration of "one prompt in, one response
#: out" that quietly prepended a page of prompt engineering would be showing
#: the visitor something other than what it claims -- whatever comes back
#: should be attributable to the prompt they can see, plus this single visible
#: line. Task-specific instructions belong in the Phase 2 preset prompts,
#: where they are shown before submission.
PLAIN_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's prompt directly and concisely."
)

#: The structured-mode instruction. Restates the schema in the prompt even
#: though the request also carries a provider-native `json_schema` directive,
#: because the directive is not universally honoured: on this deployment's
#: chain, one model rejects the parameter and one accepts it and returns a
#: different shape anyway. For a model that ignores the directive, this text is
#: the only thing asking for the right shape; for one that enforces it, the
#: text is harmless redundancy. Neither layer is sufficient alone, which is why
#: `_validate` checks the result regardless.
STRUCTURED_SYSTEM_PROMPT_TEMPLATE = """\
You return data, not prose. Respond with a single JSON object that conforms to \
this JSON Schema:

{schema}

Rules:
- Output the JSON object only. No prose before or after it, and no markdown \
code fences.
- Include every property listed in "required".
- Add no properties beyond those in the schema.
- Where a property lists "enum" values, use one of those values exactly."""


class SingleCallError(Exception):
    """Base class for single-call failures, carrying a machine-readable code."""

    code = "single_call_failed"


class InvalidPromptError(SingleCallError):
    """Raised when the submitted prompt is empty, blank, or over-long."""

    code = "invalid_prompt"


class UsageLimitReachedError(SingleCallError):
    """Raised when the shared generation capability's daily cap is spent.

    Kept distinct from GenerationUnavailableError on purpose: a spent cap is a
    quota problem that resets at 00:00 UTC, an unreachable provider is an
    outage. Reporting both with one message would tell the operator nothing
    about which of the two happened.
    """

    code = "usage_limit_reached"


class GenerationUnavailableError(SingleCallError):
    """Raised when every model in the shared generation chain failed."""

    code = "generation_unavailable"


@dataclass(frozen=True)
class StructuredRequest:
    """Exactly what was sent to the model for a structured call.

    Recorded and returned rather than reconstructed by the client, because the
    capability's Outputs require the request and response to be *shown
    together*: a client redrawing the request from what the visitor typed would
    be displaying its own intent, not what the server actually sent.

    Attributes:
        system_prompt: The instruction wrapped around the prompt.
        prompt_text: The prompt itself, as sent.
        response_schema: The JSON Schema demanded of the response, exactly as
            handed to the provider.
        schema_name: The schema's title, matching a curated schema model.
    """

    system_prompt: str
    prompt_text: str
    response_schema: dict[str, Any]
    schema_name: str


@dataclass(frozen=True)
class SingleCallResult:
    """One completed single call.

    Field names track the `Response` design entity (mode, plainText,
    structuredObject, schemaConforming).

    Attributes:
        mode: The mode actually served, "plain" or "structured".
        plain_text: The model's response in plain mode; None in structured mode.
        model: The chain slug that actually served the request -- read off the
            response, never assumed, since the request walks a fallback chain.
        structured_object: The validated response in structured mode, or None
            if the mode was plain or validation failed.
        schema_conforming: True when the response validated, False when a check
            ran and it did not, and **None when no check was performed at all**
            (every plain-mode call). Three-valued deliberately: False is a
            finding, None is the absence of one.
        raw_output: The model's unparsed text. Populated on a structured
            *failure* so the visitor can see what actually came back -- the
            capability's on_validation_failure behaviour is to surface the raw
            output, not to hide it behind an error message.
        validation_error: Why validation failed, in readable form.
        structured_request: What was sent, for the side-by-side display.
    """

    mode: str
    plain_text: str | None
    model: str
    structured_object: dict[str, Any] | None = None
    schema_conforming: bool | None = None
    raw_output: str | None = None
    validation_error: str | None = None
    structured_request: StructuredRequest | None = None


def normalize_prompt(raw: str) -> str:
    """Validate and trim a submitted prompt.

    Shared by the HTTP schema and the service so one rule governs both the
    wire boundary and any direct caller -- the same arrangement as
    `embeddings.placement.normalize_custom_text`.

    Google-style docstring per project convention.

    Args:
        raw: The prompt as submitted.

    Returns:
        The prompt with surrounding whitespace removed.

    Raises:
        InvalidPromptError: If the prompt is blank or exceeds MAX_PROMPT_CHARS.
    """
    prompt = raw.strip()
    if not prompt:
        raise InvalidPromptError("Enter a prompt before running the single call.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise InvalidPromptError(
            f"That prompt is {len(prompt)} characters -- the limit is {MAX_PROMPT_CHARS}."
        )
    return prompt


async def run_plain_call(session: AsyncSession, *, prompt_text: str) -> SingleCallResult:
    """Send one prompt to the shared generation service and return its response.

    Routes through the shared_framework_services primitives rather than
    calling the provider directly, so this app's spend is capped and logged
    like every other app's. The cap is not decoration: the endpoint is public
    and unauthenticated, and OpenRouter's free tier is a single account-wide
    daily pool shared with the RAG example -- an uncapped generation route
    would let one visitor take the whole showcase dark.

    A unit is reserved *before* the provider call, so a request that reaches
    the chain and fails still counts. That is deliberate and matches
    `rag/service.py`: the quota was spent whether or not a usable answer came
    back.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        prompt_text: The visitor's prompt. Validated here as well as at the
            HTTP boundary.

    Returns:
        The model's plain-text response and the slug that served it.

    Raises:
        InvalidPromptError: If the prompt is blank or over-long.
        UsageLimitReachedError: If the generation capability's daily cap is
            already spent.
        GenerationUnavailableError: If every model in the chain failed.
    """
    prompt = normalize_prompt(prompt_text)

    await _reserve(session)

    # One call. No retrieval before it, no tool during it, no second call
    # after it -- the fallback chain LiteLLM walks on transport failure is not
    # a second *call*, it is the same call reaching a different provider.
    try:
        generated = generate_text(system_prompt=PLAIN_SYSTEM_PROMPT, user_prompt=prompt)
    except GenerationServiceError as exc:
        raise GenerationUnavailableError(str(exc)) from exc

    await _record(
        session,
        prompt=prompt,
        response_excerpt=generated.text,
        model=generated.model,
        mode=shared.MODE_PLAIN,
        summary=f"Single call (plain mode), {len(generated.text)} chars via {generated.model}",
    )

    logger.info(
        "single_call_completed",
        mode=shared.MODE_PLAIN,
        model=generated.model,
        prompt_chars=len(prompt),
        response_chars=len(generated.text),
    )
    return SingleCallResult(
        mode=shared.MODE_PLAIN, plain_text=generated.text, model=generated.model
    )


async def run_structured_call(
    session: AsyncSession,
    *,
    prompt_text: str,
    schema_model: type[BaseModel],
) -> SingleCallResult:
    """Send one prompt demanding a schema-conforming response, then validate it.

    Enforcement is two-layered because one layer is not enough, and that is
    measured rather than cautious. The request carries a provider-native
    `json_schema` directive *and* the schema is restated in the system prompt;
    the response is then validated against the Pydantic model server-side.
    Across this deployment's eight-entry chain, five models return conforming
    JSON under the directive, one rejects the parameter outright (its 400 trips
    LiteLLM's fallback, so the request survives), and one accepts it and
    returns a different shape anyway. That last case is why the server-side
    check is load-bearing: without it the endpoint would report a
    non-conforming object as conforming, which is precisely the failure mode
    the capability names.

    On a validation failure this returns normally with
    `schema_conforming=False`, the raw output, and the error. It does **not**
    retry and does not raise: the capability's on_validation_failure behaviour
    is to surface the raw output rather than silently trying again, and a
    retry would also spend a second quota unit while contradicting the
    single-call pattern this app exists to demonstrate.

    Google-style docstring per project convention.

    Args:
        session: An async SQLAlchemy session for usage/logging bookkeeping.
        prompt_text: The prompt to send, already resolved from a preset or
            supplied as free text.
        schema_model: The curated Pydantic model the response must satisfy.

    Returns:
        A result whose `schema_conforming` is True with `structured_object`
        populated, or False with `raw_output` and `validation_error`
        populated. Either way `structured_request` carries what was sent.

    Raises:
        InvalidPromptError: If the prompt is blank or over-long.
        UsageLimitReachedError: If the generation capability's daily cap is
            already spent.
        GenerationUnavailableError: If every model in the chain failed.
    """
    prompt = normalize_prompt(prompt_text)
    schema = json_schema_for(schema_model)
    schema_name = schema_model.__name__
    system_prompt = STRUCTURED_SYSTEM_PROMPT_TEMPLATE.format(
        schema=json.dumps(schema, indent=2)
    )
    request = StructuredRequest(
        system_prompt=system_prompt,
        prompt_text=prompt,
        response_schema=schema,
        schema_name=schema_name,
    )

    await _reserve(session)

    try:
        generated = generate_text(
            system_prompt=system_prompt,
            user_prompt=prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        )
    except GenerationServiceError as exc:
        raise GenerationUnavailableError(str(exc)) from exc

    validated, error = _validate(generated.text, schema_model)
    conforming = error is None

    await _record(
        session,
        prompt=prompt,
        response_excerpt=generated.text,
        model=generated.model,
        mode=shared.MODE_STRUCTURED,
        summary=(
            f"Single call (structured mode, {schema_name}), "
            f"{'conforming' if conforming else 'SCHEMA MISMATCH'} via {generated.model}"
        ),
    )

    logger.info(
        "single_call_completed",
        mode=shared.MODE_STRUCTURED,
        model=generated.model,
        schema=schema_name,
        schema_conforming=conforming,
        prompt_chars=len(prompt),
    )

    return SingleCallResult(
        mode=shared.MODE_STRUCTURED,
        plain_text=None,
        model=generated.model,
        structured_object=validated,
        schema_conforming=conforming,
        # The raw text rides along only on failure. On success the validated
        # object says everything the raw text would, and echoing both would
        # invite the UI to show a visitor two copies of the same answer.
        raw_output=None if conforming else generated.text,
        validation_error=error,
        structured_request=request,
    )


def _validate(
    raw: str, schema_model: type[BaseModel]
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse and validate a model's structured response.

    Two failures are possible and are reported differently, because they point
    at different problems: text that is not JSON at all usually means the
    provider ignored the directive, while JSON with the wrong fields means it
    honoured the directive loosely.

    Args:
        raw: The model's response text.
        schema_model: The curated model to validate against.

    Returns:
        `(object, None)` on success, or `(None, message)` on failure.
    """
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        return None, f"The response was not valid JSON: {exc}."

    if not isinstance(parsed, dict):
        return None, f"Expected a JSON object, got {type(parsed).__name__}."

    try:
        return schema_model.model_validate(parsed).model_dump(), None
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors()
        )
        return None, f"The response did not match {schema_model.__name__} -- {problems}."


def resolve_prompt(
    *, prompt_text: str | None, preset: PresetPrompt | None
) -> str:
    """Pick the prompt actually sent, given free text and/or a preset.

    A preset wins over free text when both arrive. That is the honest reading
    of a one-click chip: the visitor's last action was choosing the preset, and
    the UI puts the preset's text into the box anyway, so silently
    concatenating the two would send something neither the chip nor the box
    displayed.

    Args:
        prompt_text: Free text from the request, if any.
        preset: The resolved preset, if one was selected.

    Returns:
        The prompt to send.

    Raises:
        InvalidPromptError: If neither source supplied anything.
    """
    if preset is not None:
        return preset.prompt_text
    if prompt_text:
        return prompt_text
    raise InvalidPromptError("Enter a prompt or choose a preset before submitting.")


async def _reserve(session: AsyncSession) -> None:
    """Spend one generation unit, or refuse the call.

    Args:
        session: An async SQLAlchemy session.

    Raises:
        UsageLimitReachedError: If today's generation cap is already spent.
    """
    try:
        await shared.reserve_capability(
            session, shared.CAPABILITY_GENERATION, app_name=SINGLE_CALL_APP_NAME
        )
    except shared.ServiceUnavailableError as exc:
        raise UsageLimitReachedError(str(exc)) from exc


async def _record(
    session: AsyncSession,
    *,
    prompt: str,
    response_excerpt: str,
    model: str,
    mode: str,
    summary: str,
) -> None:
    """Write this call's generation row and cross-app log entry.

    A structured call whose response failed validation is still recorded as a
    generation: the quota was spent and the model did answer. Recording only
    conforming responses would make the log disagree with the usage counter.

    Args:
        session: An async SQLAlchemy session.
        prompt: The prompt as sent.
        response_excerpt: The model's response text.
        model: The chain slug that served it.
        mode: shared.MODE_PLAIN or shared.MODE_STRUCTURED.
        summary: One line for the cross-app request log.
    """
    await shared.record_generation_request(
        session,
        app_name=SINGLE_CALL_APP_NAME,
        prompt_excerpt=prompt,
        response_excerpt=response_excerpt,
        model_name=model,
        mode=mode,
    )
    await shared.log_invocation(
        session,
        app_name=SINGLE_CALL_APP_NAME,
        capability=shared.CAPABILITY_GENERATION,
        summary=summary,
    )
