# Built with Spec4 AI - https://spec4.ai
"""Shared text-generation service, routed over the framework's model chain.

Model selection, provider credentials, and the withdrawn-model bench all live
in services/model_registry.py, which the tool-use agent uses too. This module
is the *synchronous* entry point onto that shared layer -- the RAG example's
build_answer()/generate_answer() call chain is sync by design and calls in
here directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import litellm
import structlog

from backend.app.services import model_registry

logger = structlog.get_logger()

REQUEST_TIMEOUT_SECONDS = 20


class GenerationServiceError(Exception):
    """Raised when the shared text-generation capability can't produce a response."""


@dataclass(frozen=True)
class GenerationResult:
    """One generation, plus the model that actually served it.

    The served model is returned rather than assumed because the request walks
    a fallback chain: recording the chain's first entry would attribute the
    response to a model that may never have been called.
    """

    text: str
    model: str


def generate_text(
    *,
    system_prompt: str,
    user_prompt: str,
    response_format: dict[str, Any] | None = None,
) -> GenerationResult:
    """Generate text over the shared free-model generation chain.

    Hands the whole chain to LiteLLM's `fallbacks`, which walks it on failure
    using the real request as the signal -- no hand-rolled retry logic, and no
    probing in the request path. A failure that names a withdrawn model
    benches it in the shared registry, so the next request skips it whichever
    example app makes it.

    Google-style docstring per project convention.

    Args:
        system_prompt: Instructions establishing the model's role and the
            output contract it must follow.
        user_prompt: The request-specific content (e.g. grounding passages
            and the visitor's question).
        response_format: Optional provider-native constrained-decoding
            directive, e.g. a `json_schema` block. Passed straight through
            when supplied and omitted entirely otherwise, so callers that
            don't want constrained decoding are unaffected.

            **Support across the chain is uneven, measured rather than
            assumed.** Of the eight entries, five return conforming JSON under
            a strict `json_schema`, one (`inclusionai/ling-3.0-flash:free`)
            rejects the parameter with an upstream 400, and one
            (`poolside/laguna-s-2.1:free`) accepts it and returns a *different*
            shape regardless. So this parameter reduces the odds of
            non-conformance -- it does not remove the need for the caller to
            validate what comes back.

            `drop_params=True` is deliberately NOT set. It does not help: the
            400 above comes from the upstream provider, not from LiteLLM's
            parameter check, so nothing gets dropped. What it would do is
            silently turn a constrained request into an unconstrained one, and
            a caller that asked for a schema is better served by a failure
            that trips the fallback chain than by a quiet downgrade.

    Returns:
        The model's raw text response and the slug that served it.

    Raises:
        GenerationServiceError: If every model in the chain fails, or the
            service returns no usable content.
    """
    chain = model_registry.active_chain(model_registry.GENERATION_MODEL_CHAIN)

    # Credentials go into the environment rather than onto the call: the
    # chain may span providers, and a single `api_key=` would be applied to
    # every fallback, including ones belonging to a different provider.
    model_registry.ensure_provider_credentials()

    optional: dict[str, Any] = {}
    if response_format is not None:
        optional["response_format"] = response_format

    try:
        response = litellm.completion(
            model=chain[0],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            fallbacks=chain[1:],
            num_retries=1,
            timeout=REQUEST_TIMEOUT_SECONDS,
            **optional,
        )
    except Exception as exc:  # noqa: BLE001 - any provider/transport failure
        model_registry.note_failure(exc)
        raise GenerationServiceError(str(exc)) from exc

    content = response.choices[0].message.content
    if not content:
        raise GenerationServiceError("text-generation service returned an empty response")

    served = model_registry.normalize(getattr(response, "model", "") or chain[0])
    logger.info("generation_completed", model=served, chars=len(content))
    return GenerationResult(text=content, model=served)
