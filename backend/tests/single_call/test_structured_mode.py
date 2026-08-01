# Built with Spec4 AI - https://spec4.ai
"""Tests for structured mode, the preset set, and per-call persistence.

The provider is stubbed at its point of use in `backend.app.single_call.service`
and the DB session is the project's fake session with pre-queued canned
results, so nothing here needs a live model or a live Postgres.

The validation-failure tests are the important ones. Real evidence that they
guard something: probing this deployment's own eight-model chain with a strict
`json_schema` directive, `openrouter/poolside/laguna-s-2.1:free` accepted the
directive and returned `{classification, priority, ...}` instead of the
requested `{category, urgency, reasoning}`. Non-conformance is a live behaviour
of the shipped chain, not a hypothetical.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.db.models import UsageLimit
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.services import shared
from backend.app.services.generation import GenerationResult
from backend.app.single_call import service
from backend.app.single_call.presets import (
    DEFAULT_SCHEMA_MODEL,
    PRESET_PROMPTS,
    PRESET_SET_VERSION,
    ClassificationResult,
    SummaryResult,
    get_preset,
    json_schema_for,
)
from backend.app.single_call.service import run_structured_call
import pytest


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation):
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """



class _FakeResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class FakeSession:
    """Async-session stand-in that pops pre-queued results in call order."""

    def __init__(self, results: list[object] | None = None) -> None:
        self._results = list(results or [])
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, _statement: object) -> _FakeResult:
        return _FakeResult(self._results.pop(0) if self._results else None)

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


def _client(session: FakeSession) -> TestClient:
    app.dependency_overrides[get_db_session] = lambda: session
    return TestClient(app)


def _served(text: str, model: str = "groq/openai/gpt-oss-120b") -> GenerationResult:
    return GenerationResult(text=text, model=model)


CONFORMING_CLASSIFICATION = json.dumps(
    {
        "category": "bug",
        "urgency": "high",
        "reasoning": "The export button is unresponsive across browsers.",
    }
)


# --------------------------------------------------------------------------
# The preset set
# --------------------------------------------------------------------------


def test_presets_endpoint_ships_the_full_prompt_text_and_schema() -> None:
    """A visitor must see exactly what a chip will send before spending a call.

    The capability's mitigation for "user is unsure what a preset will produce"
    is showing the full prompt and its mode up front, which a truncated preview
    cannot satisfy -- so this asserts the whole text ships, not just a label.
    """
    with TestClient(app) as client:
        response = client.get("/api/single-call/presets")

    assert response.status_code == 200
    body = response.json()

    assert body["preset_set_version"] == PRESET_SET_VERSION
    assert body["default_response_schema"]["title"] == DEFAULT_SCHEMA_MODEL.__name__
    assert len(body["presets"]) == len(PRESET_PROMPTS)

    for entry, preset in zip(body["presets"], PRESET_PROMPTS):
        assert entry["id"] == preset.id
        assert entry["prompt_text"] == preset.prompt_text, "the full prompt must ship, untruncated"
        assert entry["intent"], "every preset is labelled with its intent"
        assert entry["response_schema"]["title"] == preset.schema_model.__name__


def test_every_preset_schema_forbids_extra_properties() -> None:
    """`additionalProperties: false` is a prerequisite, not a nicety.

    Providers need it to run strict constrained decoding, and Pydantic needs it
    to reject a response that returned the right keys plus invented extras.
    Without it, drift toward "more fields" would validate silently.
    """
    models = [DEFAULT_SCHEMA_MODEL, *(preset.schema_model for preset in PRESET_PROMPTS)]

    for model in models:
        schema = json_schema_for(model)
        assert schema["additionalProperties"] is False, model.__name__
        # Strict mode also requires every property to be required.
        assert set(schema["required"]) == set(schema["properties"]), model.__name__


def test_the_named_intents_from_the_specification_are_all_present() -> None:
    """summarize / classify / extract are named in the capability's Inputs."""
    assert {preset.id for preset in PRESET_PROMPTS} >= {"summarize", "classify", "extract"}


# --------------------------------------------------------------------------
# Structured mode, conforming
# --------------------------------------------------------------------------


def test_a_preset_driven_structured_call_returns_conforming_json() -> None:
    """The phase's core structured assertion, driven by a real preset."""
    session = FakeSession()
    try:
        with patch.object(
            service, "generate_text", return_value=_served(CONFORMING_CLASSIFICATION)
        ) as generate:
            response = _client(session).post(
                "/api/single-call/generate",
                json={"preset_prompt_id": "classify", "mode": "structured"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert body["mode"] == "structured"
    assert body["schema_conforming"] is True
    assert body["structured_object"] == json.loads(CONFORMING_CLASSIFICATION)
    assert body["plain_text"] is None
    # Raw output is withheld on success: the validated object says everything
    # it would, and showing both invites two copies of one answer.
    assert body["raw_output"] is None
    assert body["validation_error"] is None

    # Still exactly one model call -- structured mode must not become two.
    assert generate.call_count == 1


def test_a_structured_call_sends_the_provider_native_schema_directive() -> None:
    """Constrained decoding is requested at the API level, not just asked for.

    The capability's structured_outputs mechanism is explicit that enforcement
    should happen at the API/decoding level "rather than via prompt instruction
    alone", so the response_format directive must actually be on the call.
    """
    session = FakeSession()
    try:
        with patch.object(
            service, "generate_text", return_value=_served(CONFORMING_CLASSIFICATION)
        ) as generate:
            _client(session).post(
                "/api/single-call/generate",
                json={"preset_prompt_id": "classify", "mode": "structured"},
            )
    finally:
        app.dependency_overrides.clear()

    directive = generate.call_args.kwargs["response_format"]
    assert directive["type"] == "json_schema"
    assert directive["json_schema"]["strict"] is True
    assert directive["json_schema"]["schema"] == json_schema_for(ClassificationResult)

    # And the schema is restated in the prompt, because the directive is not
    # universally honoured -- one chain entry ignores it entirely.
    assert "category" in generate.call_args.kwargs["system_prompt"]


def test_the_response_carries_the_request_that_produced_it() -> None:
    """Outputs require the submitted request and response shown together."""
    session = FakeSession()
    try:
        with patch.object(
            service, "generate_text", return_value=_served(CONFORMING_CLASSIFICATION)
        ):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"preset_prompt_id": "classify", "mode": "structured"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    sent = body["structured_request"]
    preset = get_preset("classify")
    assert preset is not None
    assert sent["prompt_text"] == preset.prompt_text
    assert sent["schema_name"] == "ClassificationResult"
    assert sent["response_schema"] == json_schema_for(ClassificationResult)
    assert sent["system_prompt"], "the instruction sent must be shown, not just the prompt"
    # The echoed prompt is the preset's text, not the empty free-text box.
    assert body["prompt_text"] == preset.prompt_text


def test_free_text_structured_requests_use_the_default_demo_schema() -> None:
    session = FakeSession()
    payload = json.dumps({"response": "Kubernetes autoscales pods.", "topics": ["devops"]})
    try:
        with patch.object(service, "generate_text", return_value=_served(payload)):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"prompt_text": "Explain autoscaling.", "mode": "structured"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is True
    assert body["structured_request"]["schema_name"] == DEFAULT_SCHEMA_MODEL.__name__


def test_a_schema_fetched_from_the_presets_endpoint_can_be_posted_back() -> None:
    """The round trip the `response_schema` input is actually for."""
    session = FakeSession()
    summary = json.dumps({"summary": "Webb sees infrared.", "key_points": ["6.5m mirror"]})
    try:
        with patch.object(service, "generate_text", return_value=_served(summary)):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={
                        "prompt_text": "Summarize this.",
                        "mode": "structured",
                        "response_schema": json_schema_for(SummaryResult),
                    },
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is True
    assert body["structured_request"]["schema_name"] == "SummaryResult"


def test_an_unrecognised_schema_is_rejected_not_swapped_for_the_default() -> None:
    """Falling back would validate against a schema nobody asked for.

    That is the subtle version of the failure this app exists to teach: the
    response would be reported as conforming, and the claim would be true of
    the wrong schema.
    """
    session = FakeSession()
    try:
        with patch.object(service, "generate_text") as generate:
            response = _client(session).post(
                "/api/single-call/generate",
                json={
                    "prompt_text": "anything",
                    "mode": "structured",
                    "response_schema": {"title": "MyOwnSchema", "type": "object"},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_response_schema"
    assert generate.call_count == 0


# --------------------------------------------------------------------------
# Structured mode, non-conforming -- the on_validation_failure behaviour
# --------------------------------------------------------------------------


def test_a_non_conforming_response_is_flagged_with_its_raw_output() -> None:
    """The measured real failure: right idea, wrong field names.

    Taken from an actual probe of this deployment's chain, where
    poolside/laguna-s-2.1:free returned exactly this shape under a strict
    json_schema directive.
    """
    drifted = json.dumps({"classification": "bug", "priority": "high"})
    session = FakeSession()
    try:
        with patch.object(service, "generate_text", return_value=_served(drifted)) as generate:
            response = _client(session).post(
                "/api/single-call/generate",
                json={"preset_prompt_id": "classify", "mode": "structured"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, "a content failure is not a transport failure"
    body = response.json()

    assert body["schema_conforming"] is False, "must not be reported as conforming"
    assert body["structured_object"] is None
    assert body["raw_output"] == drifted, "the visitor must see what actually came back"
    assert body["validation_error"]
    # Not silently retried: exactly one model call, per the mechanism's
    # on_validation_failure ("surface ... rather than silently retrying").
    assert generate.call_count == 1


def test_a_non_json_response_is_flagged_distinctly_from_a_shape_mismatch() -> None:
    """Prose means the directive was ignored; wrong keys means it was loose.

    Different problems with different fixes, so they must not read alike.
    """
    session = FakeSession()
    try:
        with patch.object(
            service, "generate_text", return_value=_served("Sure! Here's the classification:")
        ):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"preset_prompt_id": "classify", "mode": "structured"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is False
    assert "not valid JSON" in body["validation_error"]
    assert body["raw_output"] == "Sure! Here's the classification:"


def test_a_json_array_is_rejected_rather_than_crashing() -> None:
    """Valid JSON that isn't an object at all."""
    session = FakeSession()
    try:
        with patch.object(service, "generate_text", return_value=_served('["bug", "high"]')):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"preset_prompt_id": "classify", "mode": "structured"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is False
    assert "JSON object" in body["validation_error"]


def test_an_out_of_enum_value_is_caught_even_though_the_shape_is_right() -> None:
    """All three keys present, one value outside the schema's enum."""
    session = FakeSession()
    wrong_enum = json.dumps(
        {"category": "urgent-thing", "urgency": "high", "reasoning": "because"}
    )
    try:
        with patch.object(service, "generate_text", return_value=_served(wrong_enum)):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"preset_prompt_id": "classify", "mode": "structured"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is False
    assert "category" in body["validation_error"]


def test_extra_properties_are_caught_even_when_every_required_field_is_present() -> None:
    """This is what extra="forbid" buys, and why the schema test above pins it."""
    session = FakeSession()
    padded = json.dumps(
        {
            "category": "bug",
            "urgency": "high",
            "reasoning": "because",
            "confidence_score": 0.91,
        }
    )
    try:
        with patch.object(service, "generate_text", return_value=_served(padded)):
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"preset_prompt_id": "classify", "mode": "structured"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is False
    assert "confidence_score" in body["validation_error"]


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_a_structured_call_writes_a_generation_row_and_a_log_entry() -> None:
    """Per-call persistence, tagged with the app and the mode."""
    limit = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    session = FakeSession([limit])

    with patch.object(service, "generate_text", return_value=_served(CONFORMING_CLASSIFICATION)):
        result = asyncio.run(
            run_structured_call(
                session,
                prompt_text="Classify this ticket.",
                schema_model=ClassificationResult,
            )
        )

    assert result.schema_conforming is True
    assert limit.used == 1, "a structured call spends a generation unit like any other"

    by_type = {type(row).__name__: row for row in session.added}
    assert "LanguageGenerationRequest" in by_type
    assert "ServiceLogEntry" in by_type
    assert by_type["LanguageGenerationRequest"].mode == shared.MODE_STRUCTURED
    assert by_type["LanguageGenerationRequest"].app_name == service.SINGLE_CALL_APP_NAME
    assert by_type["ServiceLogEntry"].capability == shared.CAPABILITY_GENERATION


def test_a_failed_validation_is_still_recorded_as_a_generation() -> None:
    """The quota was spent and the model did answer.

    Recording only conforming responses would make the request log disagree
    with the usage counter -- and would hide precisely the calls an operator
    investigating schema failures needs to find.
    """
    limit = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    session = FakeSession([limit])

    with patch.object(service, "generate_text", return_value=_served("not json at all")):
        result = asyncio.run(
            run_structured_call(
                session, prompt_text="Classify this.", schema_model=ClassificationResult
            )
        )

    assert result.schema_conforming is False
    assert limit.used == 1
    rows = {type(row).__name__ for row in session.added}
    assert "LanguageGenerationRequest" in rows

    log = next(r for r in session.added if type(r).__name__ == "ServiceLogEntry")
    assert "MISMATCH" in log.summary, "the log must say the response did not conform"


def test_the_recorded_mode_distinguishes_plain_from_structured() -> None:
    """Without this the two are indistinguishable in the log.

    Same app, same model, same prompt length -- `mode` is the only field that
    separates them, which is the whole reason migration 0008 adds it.
    """
    plain_limit = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    plain_session = FakeSession([plain_limit])
    with patch.object(service, "generate_text", return_value=_served("prose")):
        asyncio.run(service.run_plain_call(plain_session, prompt_text="hello"))

    structured_limit = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    structured_session = FakeSession([structured_limit])
    with patch.object(service, "generate_text", return_value=_served(CONFORMING_CLASSIFICATION)):
        asyncio.run(
            run_structured_call(
                structured_session,
                prompt_text="classify",
                schema_model=ClassificationResult,
            )
        )

    def mode_of(session: FakeSession) -> str:
        row = next(
            r for r in session.added if type(r).__name__ == "LanguageGenerationRequest"
        )
        return row.mode

    assert mode_of(plain_session) == shared.MODE_PLAIN
    assert mode_of(structured_session) == shared.MODE_STRUCTURED


def test_a_preset_can_also_be_run_in_plain_mode() -> None:
    """Mode and prompt source are independent choices."""
    session = FakeSession()
    try:
        with patch.object(service, "generate_text", return_value=_served("A summary.")) as gen:
            body = (
                _client(session)
                .post(
                    "/api/single-call/generate",
                    json={"preset_prompt_id": "summarize", "mode": "plain"},
                )
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["mode"] == "plain"
    assert body["plain_text"] == "A summary."
    assert body["schema_conforming"] is None, "no schema was demanded, so none was checked"
    # Plain mode must not smuggle in a constrained-decoding directive.
    assert "response_format" not in gen.call_args.kwargs
