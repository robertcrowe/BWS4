# Built with Spec4 AI - https://spec4.ai
from collections.abc import AsyncGenerator
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.rag.answer import GeneratedAnswer
from backend.app.rag.retriever import SIMILARITY_THRESHOLD, RetrievedPassage
from backend.app.rag.service import (
    NO_STRONG_MATCH_MESSAGE,
    RagServiceError,
    build_answer,
)
from backend.app.services.generation import GenerationServiceError
import pytest


@pytest.fixture(autouse=True)
def _gate_allows_everything(allow_all_moderation):
    """Every request here carries free text, which the shared gate now checks.

    The gate is not this file's subject, and with no `OPENAI_API_KEY` in the
    test environment it fails closed and would refuse all of them. Overridden
    per module rather than globally, so a test that *should* exercise the gate
    cannot pass by accident.
    """


#: A stand-in for whichever chain model served the answer. Real runs walk
#: a fallback chain, so the served model is data, not a constant.
SERVED_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"

_STRONG_PASSAGE = RetrievedPassage(
    passage_id="voyager-1-1",
    source_title="Voyager 1",
    text_excerpt="Voyager 1 launched on September 5, 1977.",
    similarity_score=SIMILARITY_THRESHOLD + 0.2,
)
_WEAK_PASSAGE = RetrievedPassage(
    passage_id="apollo-11-1",
    source_title="Apollo 11",
    text_excerpt="Apollo 11 landed on the Moon in 1969.",
    similarity_score=SIMILARITY_THRESHOLD - 0.2,
)


def test_build_answer_returns_no_strong_match_message_below_threshold() -> None:
    with patch("backend.app.rag.service.generate_answer") as mocked_generate:
        result = build_answer("What's the best pizza topping?", [_WEAK_PASSAGE])

    mocked_generate.assert_not_called()
    assert result.status == "low_relevance"
    assert result.answer == NO_STRONG_MATCH_MESSAGE
    assert result.retrieved_passages == [_WEAK_PASSAGE]


def test_build_answer_returns_no_strong_match_message_with_no_passages() -> None:
    with patch("backend.app.rag.service.generate_answer") as mocked_generate:
        result = build_answer("What's the best pizza topping?", [])

    mocked_generate.assert_not_called()
    assert result.status == "low_relevance"


def test_build_answer_generates_a_grounded_answer_above_threshold() -> None:
    with patch(
        "backend.app.rag.service.generate_answer",
        return_value=GeneratedAnswer(text="Voyager 1 launched in 1977 [1].", model=SERVED_MODEL),
    ):
        result = build_answer("When did Voyager 1 launch?", [_STRONG_PASSAGE])

    assert result.status == "grounded"
    assert result.answer == "Voyager 1 launched in 1977 [1]."
    assert result.retrieved_passages == [_STRONG_PASSAGE]


def test_build_answer_raises_rag_service_error_when_generation_fails() -> None:
    """A mocked LiteLLM/generation failure must surface as an explicit error
    state -- no silent fallback that fabricates an answer."""
    with patch(
        "backend.app.rag.service.generate_answer",
        side_effect=GenerationServiceError("OpenRouter unavailable"),
    ):
        try:
            build_answer("When did Voyager 1 launch?", [_STRONG_PASSAGE])
        except RagServiceError as exc:
            assert "OpenRouter unavailable" in str(exc)
        else:
            raise AssertionError("expected RagServiceError to be raised")


class _FakeAskSession:
    async def execute(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("retrieval should be bypassed via answer_question mock")

    def add(self, _obj: object) -> None:
        pass

    async def commit(self) -> None:
        pass


async def _override_session() -> AsyncGenerator[_FakeAskSession, None]:
    yield _FakeAskSession()


def test_ask_endpoint_returns_503_when_generation_service_is_unavailable() -> None:
    app.dependency_overrides[get_db_session] = _override_session
    try:
        with patch(
            "backend.app.api.rag.answer_question",
            side_effect=RagServiceError("OpenRouter unavailable"),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/rag/ask", json={"user_question": "When did Voyager 1 launch?"}
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["status"] == "error"
