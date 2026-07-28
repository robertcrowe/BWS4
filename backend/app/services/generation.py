# Built with Spec4 AI - https://spec4.ai
"""Shared text-generation service: LiteLLM over OpenRouter's free model family."""

from __future__ import annotations

import litellm

from backend.app.core.config import get_settings

#: OpenRouter free-tier model family for the rag tier, per the stack's
#: provider entry -- named here rather than pinned to a dated snapshot.
#:
#: OpenRouter's free catalogue churns: the stack spec's original pair
#: (meta-llama/llama-3.3-70b-instruct:free, google/gemini-2.0-flash-exp:free)
#: was withdrawn from the free tier and now 404s. These two replacements were
#: chosen by probing the live catalogue with this app's own answer_v1 prompt --
#: both return schema-valid JSON with correct citations. They deliberately come
#: from different vendors so a single provider outage can't take out both.
#: Re-probe against https://openrouter.ai/api/v1/models when generation starts
#: 404ing again; the only hard constraint is that both stay `:free`.
PRIMARY_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
FALLBACK_MODEL = "openrouter/inclusionai/ling-3.0-flash:free"

REQUEST_TIMEOUT_SECONDS = 20


class GenerationServiceError(Exception):
    """Raised when the shared text-generation capability can't produce a response."""


def generate_text(*, system_prompt: str, user_prompt: str) -> str:
    """Generate text via LiteLLM against OpenRouter's primary/fallback model.

    Relies on LiteLLM's built-in fallback (to FALLBACK_MODEL) and a single
    retry on transient errors, rather than hand-rolled retry logic, per the
    shared_framework_services generation capability.

    Google-style docstring per project convention.

    Args:
        system_prompt: Instructions establishing the model's role and the
            output contract it must follow.
        user_prompt: The request-specific content (e.g. grounding passages
            and the visitor's question).

    Returns:
        The model's raw text response.

    Raises:
        GenerationServiceError: If the primary and fallback model both fail,
            or the service returns no usable content.
    """
    settings = get_settings()

    try:
        response = litellm.completion(
            model=PRIMARY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            api_key=settings.openrouter_api_key,
            fallbacks=[FALLBACK_MODEL],
            num_retries=1,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - any provider/transport failure
        raise GenerationServiceError(str(exc)) from exc

    content = response.choices[0].message.content
    if not content:
        raise GenerationServiceError("text-generation service returned an empty response")

    return content
