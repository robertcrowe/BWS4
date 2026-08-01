# Built with Spec4 AI - https://spec4.ai
"""Endpoint tests for the single_call_example_app router.

Lives in backend/tests/single_call/ because this phase and later ones verify
with `uv run pytest backend/tests/single_call/`.

No live database and no live provider: the DB session is the project's fake
session with pre-queued canned results (see test_shared_services.py) and the
provider call is stubbed at its point of use in
`backend.app.single_call.service`. Async entry points run through
`asyncio.run()` in sync test functions -- this repo has no pytest-asyncio, and
an `@pytest.mark.asyncio` here would silently skip.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.db.models import UsageLimit
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.services.generation import GenerationResult, GenerationServiceError
from backend.app.single_call import service
import pytest

from backend.app.single_call.service import (
    SINGLE_CALL_APP_NAME,
    UsageLimitReachedError,
    run_plain_call,
)


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation):
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """


class _FakeResult:
    """Stands in for a SQLAlchemy Result over one canned row."""

    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class FakeSession:
    """Async-session stand-in that pops pre-queued results in call order.

    Mirrors the convention in test_shared_services.py: the SQL is ignored and
    one queued result is returned per `execute()` the code under test issues.
    """

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
    """A TestClient whose DB dependency is the supplied fake session."""
    app.dependency_overrides[get_db_session] = lambda: session
    return TestClient(app)


def _generated(text: str = "A hash table maps keys to values.") -> GenerationResult:
    return GenerationResult(text=text, model="groq/llama-3.3-70b-versatile")


def test_plain_mode_returns_the_models_text() -> None:
    """The phase's core assertion: a plain prompt yields 200 with non-empty text."""
    session = FakeSession()
    try:
        with patch.object(service, "generate_text", return_value=_generated()) as generate:
            response = _client(session).post(
                "/api/single-call/generate",
                json={"prompt_text": "What is a hash table?", "mode": "plain"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert body["plain_text"] == "A hash table maps keys to values."
    assert body["plain_text"].strip(), "plain mode must return non-empty text"
    assert body["mode"] == "plain"
    assert body["model"] == "groq/llama-3.3-70b-versatile"
    assert body["prompt_text"] == "What is a hash table?"

    # Exactly one model call: the pattern being demonstrated is a single call,
    # so a second one here would mean the demo has stopped being one.
    assert generate.call_count == 1


def test_plain_mode_reports_no_schema_check_rather_than_a_failed_one() -> None:
    """`schema_conforming` is None in plain mode, never False.

    False would claim a schema check ran and the response failed it. Nothing
    was checked, and Phase 3's UI branches on exactly this to decide whether to
    render the validation-failure state.
    """
    session = FakeSession()
    try:
        with patch.object(service, "generate_text", return_value=_generated()):
            body = (
                _client(session)
                .post("/api/single-call/generate", json={"prompt_text": "hi", "mode": "plain"})
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["schema_conforming"] is None
    assert body["structured_object"] is None


def test_the_served_model_is_reported_not_the_chains_first_entry() -> None:
    """A fallback answered, so the fallback must be what gets named."""
    session = FakeSession()
    served = GenerationResult(text="answered by the deep fallback", model="openrouter/x:free")
    try:
        with patch.object(service, "generate_text", return_value=served):
            body = (
                _client(session)
                .post("/api/single-call/generate", json={"prompt_text": "hi", "mode": "plain"})
                .json()
            )
    finally:
        app.dependency_overrides.clear()

    assert body["model"] == "openrouter/x:free"


def test_an_unknown_preset_id_is_rejected_rather_than_silently_ignored() -> None:
    """A stale chip must not quietly become an empty free-text prompt."""
    session = FakeSession()
    try:
        with patch.object(service, "generate_text") as generate:
            response = _client(session).post(
                "/api/single-call/generate",
                json={"preset_prompt_id": "no-such-preset", "mode": "plain"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_preset"
    assert generate.call_count == 0


def test_submission_with_neither_prompt_nor_preset_is_rejected() -> None:
    """The capability's failure-mode mitigation, enforced server-side too."""
    session = FakeSession()
    try:
        with patch.object(service, "generate_text") as generate:
            blank = _client(session).post(
                "/api/single-call/generate", json={"prompt_text": "   ", "mode": "plain"}
            )
            absent = _client(session).post("/api/single-call/generate", json={"mode": "plain"})
    finally:
        app.dependency_overrides.clear()

    assert blank.status_code == 422
    assert absent.status_code == 422
    assert generate.call_count == 0, "an empty submission must not reach the model"


def test_an_overlong_prompt_is_rejected_before_the_model_is_called() -> None:
    """The bound exists to stop one paste spending the day's token budget."""
    session = FakeSession()
    try:
        with patch.object(service, "generate_text") as generate:
            response = _client(session).post(
                "/api/single-call/generate",
                json={"prompt_text": "x" * (service.MAX_PROMPT_CHARS + 1), "mode": "plain"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert generate.call_count == 0


def test_a_provider_failure_is_reported_as_unavailable_not_as_an_answer() -> None:
    """No fabricated fallback content -- the capability's escalation path."""
    session = FakeSession()
    try:
        with patch.object(
            service, "generate_text", side_effect=GenerationServiceError("every model failed")
        ):
            response = _client(session).post(
                "/api/single-call/generate", json={"prompt_text": "hi", "mode": "plain"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "generation_unavailable"
    assert "plain_text" not in body


def test_a_spent_usage_cap_is_reported_differently_from_a_provider_outage() -> None:
    """Two different operator problems; one shared status code, distinct codes.

    A spent cap resets at the top of the hour and an unreachable provider does not, so
    reporting them identically would tell an operator nothing about which
    happened. The queued row is already at its cap, so reserve_capability
    raises before the provider is reached.
    """
    exhausted = UsageLimit(capability="generation", used=100, cap=100, window_start=None)
    session = FakeSession([exhausted])

    with patch.object(service, "generate_text") as generate:
        try:
            asyncio.run(run_plain_call(session, prompt_text="hi"))
        except UsageLimitReachedError as exc:
            assert exc.code == "usage_limit_reached"
        else:  # pragma: no cover - the cap must bite
            raise AssertionError("an exhausted cap must not reach the provider")

    assert generate.call_count == 0, "the cap must be checked before the provider is called"


def test_a_call_is_capped_and_logged_through_the_shared_services() -> None:
    """The public endpoint must not be an uncapped drain on a shared free tier.

    OpenRouter's free tier is one account-wide daily pool that the RAG example
    also draws from, and this route is unauthenticated. Asserting the
    bookkeeping rows here is what stops a later refactor from quietly routing
    around the cap.
    """
    fresh = UsageLimit(capability="generation", used=0, cap=100, window_start=None)
    session = FakeSession([fresh])

    with patch.object(service, "generate_text", return_value=_generated()):
        result = asyncio.run(run_plain_call(session, prompt_text="What is a hash table?"))

    assert result.plain_text
    assert fresh.used == 1, "a call must spend a generation unit"

    written = {type(row).__name__ for row in session.added}
    assert "LanguageGenerationRequest" in written
    assert "ServiceLogEntry" in written

    for row in session.added:
        assert getattr(row, "app_name", None) == SINGLE_CALL_APP_NAME, (
            "rows must be tagged with this app so the cross-app log can attribute them"
        )


def test_single_call_router_does_not_displace_the_existing_routes() -> None:
    """Mounting a fifth router leaves the established surface addressable.

    Registration order is the risk the phase flagged: a router added to main.py
    can shadow an existing path prefix. The RAG dataset route is the cheapest
    existing endpoint to prove it did not -- it touches no database.
    """
    with TestClient(app) as client:
        rag = client.get("/api/rag/dataset")
        presets = client.get("/api/embeddings/presets")

    assert rag.status_code == 200
    assert rag.json()["documents"]
    assert presets.status_code == 200
