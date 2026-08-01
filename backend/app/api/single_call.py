# Built with Spec4 AI - https://spec4.ai
"""Thin FastAPI handlers for the single_call_example_app, mirroring api/rag.py.

A structured response that failed schema validation is returned as **200**, not
as an error status. The call succeeded and the model answered; what failed is
the *content*, and the capability requires that non-conformance be shown to the
visitor with the raw output rather than presented as either a success or a
transport failure. A 4xx/5xx here would push the client's error branch and lose
the very output the visitor is supposed to see. `schema_conforming: false` is
the signal, and the frontend branches on it.
"""

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.services import text_gate
from backend.app.services.moderation import Moderator, get_moderator
from backend.app.single_call.presets import (
    DEFAULT_SCHEMA_MODEL,
    PRESET_PROMPTS,
    PRESET_SET_VERSION,
    PresetPrompt,
    get_preset,
    json_schema_for,
    schema_model_for_title,
)
from backend.app.single_call.schemas import (
    PresetPromptOut,
    PresetsResponse,
    SingleCallRequest,
    SingleCallResponse,
    StructuredRequestOut,
)
from backend.app.single_call.service import (
    GenerationUnavailableError,
    InvalidPromptError,
    UsageLimitReachedError,
    resolve_prompt,
    run_plain_call,
    run_structured_call,
)

logger = structlog.get_logger()

router = APIRouter()

#: Tag on this app's moderation calls.
SINGLE_CALL_APP_NAME = "Single-Call Example App"


@router.get("/api/single-call/presets")
async def get_presets() -> JSONResponse:
    """List the curated preset prompts and the default structured schema.

    Touches no database and calls no model -- the set is bundled in-repo, so
    this is a read of a versioned constant.

    Google-style docstring per project convention.

    Returns:
        A 200 JSON response with every preset's id, label, intent, full prompt
        text, and target schema, plus the set version and the default schema
        used for free-text structured requests.
    """
    response = PresetsResponse(
        presets=[
            PresetPromptOut(
                id=preset.id,
                label=preset.label,
                intent=preset.intent,
                prompt_text=preset.prompt_text,
                response_schema=json_schema_for(preset.schema_model),
            )
            for preset in PRESET_PROMPTS
        ],
        preset_set_version=PRESET_SET_VERSION,
        default_response_schema=json_schema_for(DEFAULT_SCHEMA_MODEL),
    )
    return JSONResponse(status_code=200, content=response.model_dump())


@router.post("/api/single-call/generate")
async def generate(
    payload: SingleCallRequest,
    session: AsyncSession = Depends(get_db_session),
    moderator: Moderator = Depends(get_moderator),
) -> JSONResponse:
    """Run one direct model call and return its response.

    Google-style docstring per project convention.

    Args:
        payload: The prompt (or preset id), the requested mode, and optionally
            the target schema for structured mode.
        session: An async DB session injected per-request, used for the shared
            usage-limit and request-logging bookkeeping.
        moderator: The shared safety gate, run over free text only. A preset is
            resolved to its canonical server-side wording by `get_preset`, so
            there is no claim to verify and nothing to moderate.

    Returns:
        A 200 JSON response carrying the response, the mode served, and the
        model that served it -- including when a structured response failed
        validation, which is reported as `schema_conforming: false` alongside
        the raw output. Otherwise a 422 for an unusable prompt or an
        unrecognised schema, or a 503 carrying a machine-readable `code` the
        frontend branches on -- `usage_limit_reached` (resets hourly) or
        `generation_unavailable` (the provider chain failed). Those two are
        reported separately because they are different operator problems.
    """
    preset = None
    if payload.preset_prompt_id:
        preset = get_preset(payload.preset_prompt_id)
        if preset is None:
            return _error(
                422,
                "unknown_preset",
                f"No preset prompt with id {payload.preset_prompt_id!r}. "
                "Fetch the current set from GET /api/single-call/presets.",
            )

    try:
        prompt = resolve_prompt(prompt_text=payload.prompt_text, preset=preset)
    except InvalidPromptError as exc:
        return _error(422, exc.code, str(exc))

    # A preset outranks free text server-side, so `prompt` is already the
    # canonical wording when one was named -- and canonical wording is
    # pre-vetted. Only a genuinely free-form prompt reaches the gate.
    if preset is None:
        gate = await text_gate.check_free_text(
            prompt,
            app_name=SINGLE_CALL_APP_NAME,
            session=session,
            moderator=moderator,
        )
        if not gate.allowed and gate.code is not None:
            return _error(
                text_gate.status_for(gate.code), gate.code, gate.message or ""
            )

    try:
        if payload.mode == "structured":
            schema_model = _schema_model_for(payload, preset)
            result = await run_structured_call(
                session, prompt_text=prompt, schema_model=schema_model
            )
        else:
            result = await run_plain_call(session, prompt_text=prompt)
    except _UnsupportedSchema as exc:
        return _error(422, "unsupported_response_schema", str(exc))
    except InvalidPromptError as exc:
        return _error(422, exc.code, str(exc))
    except (UsageLimitReachedError, GenerationUnavailableError) as exc:
        logger.error("single_call_failed", code=exc.code, error=str(exc))
        return _error(503, exc.code, str(exc))

    request_out = None
    if result.structured_request is not None:
        request_out = StructuredRequestOut(**vars(result.structured_request))

    response = SingleCallResponse(
        mode=result.mode,
        plain_text=result.plain_text,
        structured_object=result.structured_object,
        schema_conforming=result.schema_conforming,
        model=result.model,
        prompt_text=prompt,
        raw_output=result.raw_output,
        validation_error=result.validation_error,
        structured_request=request_out,
    )
    return JSONResponse(status_code=200, content=response.model_dump())


class _UnsupportedSchema(Exception):
    """Raised when a request names a schema this deployment does not validate."""


def _schema_model_for(
    payload: SingleCallRequest, preset: PresetPrompt | None
) -> type[BaseModel]:
    """Decide which curated schema a structured request targets.

    Precedence: an explicitly supplied `response_schema` wins, then the
    selected preset's own schema, then the default demo schema. An explicit
    schema outranks the preset because a caller who named one has stated an
    intent the preset's default cannot override.

    Args:
        payload: The validated request.
        preset: The resolved preset, or None.

    Returns:
        The Pydantic model to validate the response against.

    Raises:
        _UnsupportedSchema: If `response_schema` carries no `title`, or a title
            no curated schema uses. Not silently ignored -- falling back to the
            demo schema would validate the response against something the
            caller never asked for and report it as conforming.
    """
    if payload.response_schema is not None:
        title = payload.response_schema.get("title")
        model = schema_model_for_title(title) if isinstance(title, str) else None
        if model is None:
            raise _UnsupportedSchema(
                f"Unrecognised response_schema {title!r}. This demo validates against its "
                "curated schemas; fetch one from GET /api/single-call/presets and send it "
                "back, or omit response_schema to use the default."
            )
        return model
    if preset is not None:
        return preset.schema_model
    return DEFAULT_SCHEMA_MODEL


def _error(status: int, code: str, detail: str) -> JSONResponse:
    """Build the error body shape every route in this app returns.

    Args:
        status: The HTTP status code.
        code: The machine-readable code the frontend branches on.
        detail: A human-readable explanation.

    Returns:
        A JSONResponse carrying all three.
    """
    return JSONResponse(
        status_code=status, content={"status": "error", "code": code, "detail": detail}
    )
