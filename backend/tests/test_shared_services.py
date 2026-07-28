# Built with Spec4 AI - https://spec4.ai
import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.db.models import (
    LanguageGenerationRequest,
    ServiceLogEntry,
    StoredRecord,
    TextRepresentation,
    UsageLimit,
)
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.services import shared


class _FakeExecuteResult:
    """Mirrors the existing fake-session convention: ignores the actual
    statement and returns a canned result, since ordering/filtering happens
    in Postgres and isn't available here."""

    def __init__(self, scalar: object = None, all_rows: list[object] | None = None) -> None:
        self._scalar = scalar
        self._all_rows = all_rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> "_FakeExecuteResult":
        return self

    def all(self) -> list[object]:
        return self._all_rows


class _FakeSession:
    """Records ORM writes/commits in memory and returns pre-queued results
    for each execute() call in order, mirroring test_dataset_embeddings.py's
    _FakeAsyncSession pattern."""

    def __init__(self, queued_results: list[_FakeExecuteResult] | None = None) -> None:
        self._queue = list(queued_results or [])
        self.added: list[object] = []
        self.commit_count = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeExecuteResult:
        if self._queue:
            return self._queue.pop(0)
        return _FakeExecuteResult(scalar=None)

    async def commit(self) -> None:
        self.commit_count += 1


def test_generate_text_through_shared_interface_records_log_and_usage_rows() -> None:
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=None)])

    with patch(
        "backend.app.services.generation.generate_text",
        return_value="a generated response",
    ) as mocked_generate:
        text = asyncio.run(
            shared.generate_text(
                session, system_prompt="sys", user_prompt="prompt", app_name="Test App"
            )
        )

    mocked_generate.assert_called_once()
    assert text == "a generated response"

    usage_rows = [obj for obj in session.added if isinstance(obj, UsageLimit)]
    generation_rows = [obj for obj in session.added if isinstance(obj, LanguageGenerationRequest)]
    log_rows = [obj for obj in session.added if isinstance(obj, ServiceLogEntry)]

    assert len(usage_rows) == 1
    assert usage_rows[0].capability == "generation"
    assert usage_rows[0].used == 1
    assert len(generation_rows) == 1
    assert generation_rows[0].app_name == "Test App"
    assert generation_rows[0].response_excerpt == "a generated response"
    assert len(log_rows) == 1
    assert log_rows[0].capability == "generation"
    assert session.commit_count >= 1


def test_represent_text_through_shared_interface_records_log_and_usage_rows() -> None:
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=None)])

    with patch(
        "backend.app.services.embedding.embed_text", return_value=[0.1, 0.2, 0.3]
    ) as mocked_embed:
        vector = asyncio.run(shared.represent_text(session, text="hello world", app_name="Test App"))

    mocked_embed.assert_called_once_with("hello world")
    assert vector == [0.1, 0.2, 0.3]

    usage_rows = [obj for obj in session.added if isinstance(obj, UsageLimit)]
    representation_rows = [obj for obj in session.added if isinstance(obj, TextRepresentation)]
    log_rows = [obj for obj in session.added if isinstance(obj, ServiceLogEntry)]

    assert usage_rows[0].capability == "representation"
    assert usage_rows[0].used == 1
    assert len(representation_rows) == 1
    assert representation_rows[0].dimensions == 3
    assert log_rows[0].capability == "representation"


def test_set_record_through_shared_interface_records_log_and_usage_rows() -> None:
    session = _FakeSession(
        queued_results=[_FakeExecuteResult(scalar=None), _FakeExecuteResult(scalar=None)]
    )

    record = asyncio.run(
        shared.set_record(session, key="visitor_last_question", value="hello", app_name="Test App")
    )

    assert record.key == "visitor_last_question"
    assert record.value == "hello"

    usage_rows = [obj for obj in session.added if isinstance(obj, UsageLimit)]
    stored_rows = [obj for obj in session.added if isinstance(obj, StoredRecord)]
    log_rows = [obj for obj in session.added if isinstance(obj, ServiceLogEntry)]

    assert usage_rows[0].capability == "storage"
    assert usage_rows[0].used == 1
    assert len(stored_rows) == 1
    assert log_rows[0].capability == "storage"


def test_generate_text_raises_service_unavailable_once_capability_cap_is_reached() -> None:
    """A mocked low cap must reject the request before the provider is ever
    called -- the shared interface's clear-failure behavior."""
    exhausted_limit = UsageLimit(capability="generation", used=2, cap=2)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted_limit)])

    with patch("backend.app.services.generation.generate_text") as mocked_generate:
        try:
            asyncio.run(
                shared.generate_text(
                    session, system_prompt="sys", user_prompt="prompt", app_name="Test App"
                )
            )
        except shared.ServiceUnavailableError as exc:
            assert exc.capability == "generation"
        else:
            raise AssertionError("expected ServiceUnavailableError to be raised")

    mocked_generate.assert_not_called()
    assert not any(isinstance(obj, LanguageGenerationRequest) for obj in session.added)


def test_console_test_request_endpoint_returns_503_when_capability_cap_is_reached() -> None:
    exhausted_limit = UsageLimit(capability="generation", used=1, cap=1)
    session = _FakeSession(queued_results=[_FakeExecuteResult(scalar=exhausted_limit)])

    async def _override_session() -> AsyncGenerator[_FakeSession, None]:
        yield session

    app.dependency_overrides[get_db_session] = _override_session
    try:
        with patch("backend.app.services.generation.generate_text") as mocked_generate:
            with TestClient(app) as client:
                response = client.post(
                    "/api/console/test-request",
                    json={"request_type": "generation", "request_payload": "Summarize BWS4."},
                )
    finally:
        app.dependency_overrides.clear()

    mocked_generate.assert_not_called()
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert "generation" in body["detail"]


def test_console_status_endpoint_returns_usage_limits_and_log_entries() -> None:
    usage_row = UsageLimit(
        capability="generation", used=3, cap=100, window_start=shared.utc_today()
    )
    log_row = ServiceLogEntry(
        app_name="RAG Example App",
        capability="generation",
        summary="Generated a grounded RAG answer",
        timestamp=datetime.now(timezone.utc),
    )
    session = _FakeSession(
        queued_results=[
            _FakeExecuteResult(all_rows=[usage_row]),
            _FakeExecuteResult(all_rows=[log_row]),
        ]
    )

    async def _override_session() -> AsyncGenerator[_FakeSession, None]:
        yield session

    app.dependency_overrides[get_db_session] = _override_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/console/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["usage_limits"] == [
        {
            "capability": "generation",
            "used": 3,
            "cap": 100,
            "window_start": shared.utc_today().isoformat(),
        }
    ]
    assert len(body["log_entries"]) == 1
    assert body["log_entries"][0]["app_name"] == "RAG Example App"
    assert body["log_entries"][0]["capability"] == "generation"
