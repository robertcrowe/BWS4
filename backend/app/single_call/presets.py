# Built with Spec4 AI - https://spec4.ai
"""The curated PresetPrompt set and the Pydantic response schemas it targets.

Versioned in-repo data, following the same convention as
`rag/prompts/answer_v1.md`: **a shipped version is never edited in place.**
Changing a preset's `prompt_text` or its schema changes what a past response
can be reproduced from, so a real change means adding a `v2` set and bumping
PRESET_SET_VERSION -- exactly the rule that keeps `answer_v1.md` intact
alongside `answer_v2.md`. Wording fixes to a `label` or `intent`, which are
display-only and never sent to a model, are not version-bearing.

Two things live here rather than in schemas.py, deliberately: the preset's
prompt and the schema its answer must satisfy are one unit. Splitting them
would let a preset asking for a summary point at a classification schema, and
nothing would catch it -- the model would simply fail validation on every call.

Every schema is a Pydantic model with `extra="forbid"`, so
`model_json_schema()` emits `additionalProperties: false` and every field lands
in `required`. Both are prerequisites for providers' *strict* json_schema mode;
without them a provider that advertises constrained decoding will happily
return extra keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

#: Bumped when a preset's prompt_text or target schema changes. See the module
#: docstring: shipped versions are added alongside, never edited.
PRESET_SET_VERSION = "v1"


class _StrictSchema(BaseModel):
    """Base for every structured-mode target schema.

    `extra="forbid"` is what puts `additionalProperties: false` into the
    emitted JSON Schema. That matters twice over: providers need it to run
    strict constrained decoding, and Pydantic needs it to *reject* a model
    that returned the right keys plus invented extras. Without it, drift in
    the direction of "more fields" would validate silently.
    """

    model_config = ConfigDict(extra="forbid")


class SummaryResult(_StrictSchema):
    """Structured output for the `summarize` preset."""

    summary: str
    key_points: list[str]


class ClassificationResult(_StrictSchema):
    """Structured output for the `classify` preset."""

    category: Literal["bug", "feature_request", "question", "billing"]
    urgency: Literal["low", "medium", "high"]
    reasoning: str


class ExtractionResult(_StrictSchema):
    """Structured output for the `extract` preset."""

    people: list[str]
    organizations: list[str]
    dates: list[str]
    action_items: list[str]


class DemoResult(_StrictSchema):
    """The default structured schema for free-text prompts with no preset.

    Deliberately generic -- a visitor's own prompt could be about anything, so
    the schema asks only for something every response can supply: the answer
    itself plus the topics it touched. Shape follows the design mock's own
    structured-response example (`{response, topics}`).
    """

    response: str
    topics: list[str]


@dataclass(frozen=True)
class PresetPrompt:
    """One curated example prompt, offered as a one-click choice.

    Attributes:
        id: Stable identifier sent as `preset_prompt_id`. Part of the wire
            contract, so it outlives label rewording.
        label: Short display name for the chip.
        intent: What the preset demonstrates -- "Summarize", "Classify",
            "Extract". Shown on the chip because the capability's failure modes
            call for presets to be labelled by intent, so a visitor knows what
            a chip will do before spending a call on it.
        prompt_text: The complete prompt sent to the model, verbatim. Includes
            its own sample text: clicking a chip must not require the visitor
            to also supply material for it to work on. Shown in full before
            submission, per the capability's mitigation for preset uncertainty.
        schema_model: The Pydantic model a structured-mode response must
            validate against. Also the source of the JSON Schema sent to the
            provider for constrained decoding.
    """

    id: str
    label: str
    intent: str
    prompt_text: str
    schema_model: type[_StrictSchema]


PRESET_PROMPTS: list[PresetPrompt] = [
    PresetPrompt(
        id="summarize",
        label="Summarize a passage",
        intent="Summarize",
        prompt_text=(
            "Summarize the following passage in two sentences, then list its key points.\n\n"
            "The James Webb Space Telescope observes primarily in the infrared, which lets it "
            "see through the dust clouds that hide star formation from visible-light "
            "telescopes. Its 6.5-metre segmented mirror collects roughly six times the light "
            "of Hubble's, and it operates about 1.5 million kilometres from Earth at the "
            "second Lagrange point, where a five-layer sunshield keeps its instruments near "
            "40 kelvin. That combination has let it identify galaxies that formed within the "
            "first few hundred million years after the Big Bang, and measure the composition "
            "of atmospheres on planets orbiting other stars."
        ),
        schema_model=SummaryResult,
    ),
    PresetPrompt(
        id="classify",
        label="Classify a support ticket",
        intent="Classify",
        prompt_text=(
            "Classify the following support ticket by type and urgency, and explain your "
            "reasoning in one sentence.\n\n"
            "\"The export button does nothing when I click it. I've tried three different "
            "browsers and cleared my cache. I need to get this report to my client by "
            "Friday.\""
        ),
        schema_model=ClassificationResult,
    ),
    PresetPrompt(
        id="extract",
        label="Extract details from a note",
        intent="Extract",
        prompt_text=(
            "Extract the structured details from this meeting note.\n\n"
            "Priya Raman from Northwind Logistics called on 12 March 2026 to ask that the Q2 "
            "pilot be moved from 20 April to 4 May, since their warehouse system freeze runs "
            "until the end of April. She'll send revised volume figures by 19 March. I "
            "agreed to circulate an updated statement of work and to loop in Dan Okafor from "
            "our integrations team before the next call."
        ),
        schema_model=ExtractionResult,
    ),
]

#: Used for structured requests that supply free text instead of a preset.
DEFAULT_SCHEMA_MODEL: type[_StrictSchema] = DemoResult

_PRESETS_BY_ID = {preset.id: preset for preset in PRESET_PROMPTS}

#: Every schema a structured request may target, keyed by the `title` that
#: `model_json_schema()` emits. A caller who fetched a schema from
#: GET /api/single-call/presets can post it straight back and be understood.
_SCHEMAS_BY_TITLE: dict[str, type[_StrictSchema]] = {
    model.__name__: model
    for model in [DEFAULT_SCHEMA_MODEL, *(preset.schema_model for preset in PRESET_PROMPTS)]
}


def get_preset(preset_id: str) -> PresetPrompt | None:
    """Look up a preset by its wire identifier.

    Args:
        preset_id: The `preset_prompt_id` from the request.

    Returns:
        The matching preset, or None if no preset carries that id.
    """
    return _PRESETS_BY_ID.get(preset_id)


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Render a schema model as the JSON Schema sent to the provider.

    Args:
        model: One of the curated response-schema models.

    Returns:
        A JSON Schema object carrying `title`, `required`, and
        `additionalProperties: false`.
    """
    return model.model_json_schema()


def schema_model_for_title(title: str) -> type[_StrictSchema] | None:
    """Resolve a caller-supplied schema back to the model that validates it.

    Matching on `title` rather than on the whole schema body is what makes the
    round trip usable: a client can take a schema verbatim from
    GET /api/single-call/presets, post it back as `response_schema`, and have
    it recognised without reproducing every nested detail byte-for-byte.

    Arbitrary inline schemas are deliberately *not* supported -- see
    `schemas.SingleCallRequest.response_schema` for why.

    Args:
        title: The schema's `title` field.

    Returns:
        The curated model with that name, or None if the title is unknown.
    """
    return _SCHEMAS_BY_TITLE.get(title)
