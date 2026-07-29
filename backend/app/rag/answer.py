# Built with Spec4 AI - https://spec4.ai
"""Builds the RAG generation call: prompt assembly, invocation, and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass

import structlog
from pydantic import ValidationError

from backend.app.rag.prompt_loader import load_prompt
from backend.app.rag.retriever import RetrievedPassage
from backend.app.rag.schemas import LlmAnswer
from backend.app.services.generation import GenerationServiceError, generate_text

#: v2 adds the "no citation markers when declining" rule that citations.py's
#: audit depends on to tell a grounded answer from a refusal.
PROMPT_VERSION = "answer_v2"

_SYSTEM_PROMPT = (
    "You are a careful, grounded question-answering assistant. Follow the "
    "user message's instructions exactly, including its required JSON "
    "output format."
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class GeneratedAnswer:
    """A validated answer, plus the chain model that actually produced it.

    The serving model rides along because the shared generation service walks
    a multi-model fallback chain: naming the chain's first entry in the
    request log would attribute the answer to a model that may never have run.
    """

    text: str
    model: str


def generate_answer(question: str, passages: list[RetrievedPassage]) -> GeneratedAnswer:
    """Generate a grounded answer to a question from its retrieved passages.

    Resolves the versioned prompt template, fills it with the numbered
    retrieved passages and the question, and validates the model's JSON
    response against the structured-output schema. The prompt version is
    logged alongside the retrieved passage ids so a generation can be
    reproduced or attributed to a specific prompt revision.

    Google-style docstring per project convention.

    Args:
        question: The visitor's natural-language question.
        passages: The retriever's top-N passages, already above the
            similarity threshold.

    Returns:
        The generated answer, citing passages by their `[N]` position in
        `passages`, together with the model that served it.

    Raises:
        GenerationServiceError: If the text-generation service fails, or its
            response doesn't conform to the structured-output schema.
    """
    template = load_prompt(PROMPT_VERSION)
    numbered_passages = "\n\n".join(
        f"[{index}] ({passage.source_title}) {passage.text_excerpt}"
        for index, passage in enumerate(passages, start=1)
    )
    prompt = template.replace("{{PASSAGES}}", numbered_passages).replace(
        "{{QUESTION}}", question
    )

    generated = generate_text(system_prompt=_SYSTEM_PROMPT, user_prompt=prompt)

    try:
        parsed = LlmAnswer.model_validate(json.loads(_extract_json_object(generated.text)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise GenerationServiceError(
            f"text-generation service returned a response that didn't match "
            f"the {PROMPT_VERSION} structured-output schema"
        ) from exc

    logger.info(
        "rag_answer_generated",
        prompt_version=PROMPT_VERSION,
        model=generated.model,
        passage_ids=[p.passage_id for p in passages],
    )
    return GeneratedAnswer(text=parsed.answer, model=generated.model)


def _extract_json_object(text: str) -> str:
    """Extract the first top-level JSON object from a model's raw response.

    Defensively tolerates models that wrap their JSON in prose or code
    fences despite being instructed not to.

    Args:
        text: The model's raw response text.

    Returns:
        The substring spanning the first `{` to its matching last `}`.

    Raises:
        json.JSONDecodeError: If no `{...}` span is present at all.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("no JSON object found in response", text, 0)
    return text[start : end + 1]
