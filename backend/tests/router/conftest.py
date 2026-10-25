# Built with Spec4 AI - https://spec4.ai
"""Shared fixtures for the Router suite.

The route descriptions are generated at startup from the titles the RAG
retriever indexes, which needs the database. The suite has none, so an autouse
fixture fills the holder from a fixed title list -- the eight subjects the
vision names -- and empties it again afterwards. A test about the not-ready
path empties it itself.

A second autouse fixture makes a forgotten model stub fail loudly rather than
reach a real provider -- the lesson `tests/react/conftest.py` records. It
patches the lane's model *builder*, not `run_typed_step`, so a test can still
drive the real step with a PydanticAI `FunctionModel` by patching the builder
itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest

from backend.app.db.models import (
    AllowanceHold,
    RouterAgreementRecord,
    RouterLatencyObservation,
    UsageLimit,
)
from backend.app.rag import retriever as rag_retriever
from backend.app.rag import service as rag_service
from backend.app.router import rerun, service, state
from backend.app.router.state import RouteDescriptions
from backend.app.services import agent_runtime, generation, web_search

#: The indexed titles the suite pretends the retriever holds.
STUB_TITLES: list[str] = [
    "Apollo 11",
    "Sputnik 1",
    "Space Shuttle",
    "International Space Station",
    "Hubble Space Telescope",
    "James Webb Space Telescope",
    "Curiosity (rover)",
    "SpaceX",
]


@pytest.fixture
def stub_titles() -> list[str]:
    """Return a copy of the indexed titles the suite pretends exist.

    Returns:
        The stub titles.
    """
    return list(STUB_TITLES)


@pytest.fixture(autouse=True)
def route_descriptions() -> Iterator[RouteDescriptions]:
    """Fill the route-description holder from `STUB_TITLES`.

    Yields:
        The generated descriptions.
    """
    descriptions = state.set_route_descriptions(STUB_TITLES)
    yield descriptions
    state.reset_route_descriptions()


@pytest.fixture(autouse=True)
def fresh_rerun_tickets() -> Iterator[None]:
    """Start and end every test with no re-run tickets in the process.

    Yields:
        None.
    """
    rerun.TICKETS.clear()
    yield
    rerun.TICKETS.clear()


@pytest.fixture(autouse=True)
def no_live_model_calls() -> Iterator[None]:
    """Refuse to build a real model or call real generation in this suite.

    Yields:
        None. A test that wants a model patches
        `agent_runtime.build_fallback_model`, `run_typed_step` or
        `generation.generate_text` itself.
    """

    def refuse(*_args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "This test reached the real model lane. Patch "
            "`agent_runtime.run_typed_step` or `build_fallback_model` -- a live "
            f"call spends provider quota. Label was {kwargs.get('label')!r}."
        )

    def refuse_generation(**kwargs: Any) -> Any:
        raise AssertionError(
            "This test reached the real LiteLLM generation service. Patch "
            "`generation.generate_text` -- a live call spends provider quota."
        )

    async def refuse_search(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "This test reached real Exa search. Use the `stub_search` fixture."
        )

    async def refuse_retrieval(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "This test reached the real retriever. Use the `stub_retrieval` fixture."
        )

    with (
        patch.object(agent_runtime, "build_fallback_model", refuse),
        patch.object(generation, "generate_text", refuse_generation),
        patch.object(web_search, "search", refuse_search),
        patch.object(rag_retriever, "retrieve_passages", refuse_retrieval),
    ):
        yield


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return [] if self._value is None else [self._value]

    def one(self) -> Any:
        return self._value


class RouterStore:
    """A fake session that behaves like a store: usage rows and holds persist.

    Which table a `select` wanted is recovered from the compiled statement, as
    `tests/react/conftest.py` does. Every method suspends, so teardown inside a
    cancelled task is exercised for real. One instance stands in for every
    session the service opens, so a test can read the end state.
    """

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.limits: dict[str, UsageLimit] = {}
        self.holds: dict[str, AllowanceHold] = {}
        self.added: list[Any] = []
        self.agreement_rows: list[RouterAgreementRecord] = []
        self.latency_rows: list[RouterLatencyObservation] = []
        self.commits = 0
        self.rollbacks = 0
        self._caps = caps or {}

    async def execute(self, statement: Any, *_a: object, **_k: object) -> _Result:
        await asyncio.sleep(0)
        text = str(statement)
        try:
            params: dict[str, Any] = dict(statement.compile().params)
        except Exception:  # noqa: BLE001 - fake session, best effort
            params = {}
        key = next((v for v in params.values() if isinstance(v, str)), None)
        if "allowance_holds" in text:
            return _Result(self.holds.get(key) if key else None)
        if "usage_limits" in text:
            return _Result(self.limits.get(key) if key else None)
        if "router_latency_observations" in text:
            # The baseline read: (median or None below five, sample size).
            durations = sorted(row.duration_ms for row in self.latency_rows)
            n = len(durations)
            median = None
            if n >= 5:
                mid = n // 2
                median = (
                    durations[mid]
                    if n % 2
                    else (durations[mid - 1] + durations[mid]) / 2
                )
            return _Result((median, n))
        return _Result(None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj
        elif isinstance(obj, AllowanceHold):
            self.holds[obj.hold_key] = obj
        elif isinstance(obj, RouterAgreementRecord):
            self.agreement_rows.append(obj)
        elif isinstance(obj, RouterLatencyObservation):
            self.latency_rows.append(obj)

    async def commit(self) -> None:
        await asyncio.sleep(0)
        self.commits += 1

    async def rollback(self) -> None:
        await asyncio.sleep(0)
        self.rollbacks += 1

    async def __aenter__(self) -> RouterStore:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def used(self, capability: str = "generation") -> int:
        row = self.limits.get(capability)
        return row.used if row else 0

    def hold(self) -> AllowanceHold | None:
        return next(iter(self.holds.values()), None)


@pytest.fixture
def router_store() -> Iterator[Callable[..., RouterStore]]:
    """Patch the service's session factory with a fake store.

    Yields:
        A factory taking optional caps; each call installs a fresh store and
        returns it.
    """
    stores: list[RouterStore] = []

    def install(caps: dict[str, int] | None = None) -> RouterStore:
        store = RouterStore(caps)
        stores.append(store)
        return store

    def factory() -> RouterStore:
        if not stores:
            install()
        return stores[-1]

    with patch.object(service, "async_session_factory", factory):
        yield install


class GenerationStub:
    """A stand-in for `generation.generate_text` that records its calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = "A stubbed answer."
        self.model = "stub/model"
        self.error: Exception | None = None

    def __call__(self, **kwargs: Any) -> generation.GenerationResult:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return generation.GenerationResult(text=self.text, model=self.model)


@pytest.fixture
def stub_generation() -> Iterator[GenerationStub]:
    """Replace the shared generation call with a recording stub.

    Yields:
        The stub; set `text`, `model` or `error` to shape its behaviour.
    """
    stub = GenerationStub()
    with patch.object(generation, "generate_text", stub):
        yield stub


class SearchStub:
    """A stand-in for `web_search.search` that records its queries."""

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.results: list[web_search.ExaResult] = [
            web_search.ExaResult(
                title=f"Result {n}",
                summary=f"Snippet {n} says something relevant.",
                source=f"https://example.test/{n}",
                published_date="2026-10-01",
            )
            for n in (1, 2)
        ]
        self.error: Exception | None = None

    async def __call__(self, query: str) -> list[web_search.ExaResult]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.results


@pytest.fixture
def stub_search() -> Iterator[SearchStub]:
    """Replace Exa search with a recording stub.

    Yields:
        The stub; set `results` or `error` to shape it.
    """
    stub = SearchStub()
    with patch.object(web_search, "search", stub):
        yield stub


class RetrievalStub:
    """Stand-ins for the RAG retriever and answer step, recording calls."""

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.passages = [
            rag_retriever.RetrievedPassage(
                passage_id="apollo_11-0",
                source_title="Apollo 11",
                text_excerpt="Armstrong and Aldrin spent 21.5 hours on the surface.",
                similarity_score=0.71,
            )
        ]
        self.answers: list[str] = []
        self.status = "grounded"
        self.error: Exception | None = None

    async def retrieve(self, _session: Any, question: str) -> Any:
        self.questions.append(question)
        return self.passages

    def build_answer(self, question: str, passages: Any) -> Any:
        self.answers.append(question)
        if self.error is not None:
            raise self.error
        if self.status == "low_relevance":
            return rag_service.AnswerResult(
                answer="none", retrieved_passages=passages, status="low_relevance"
            )
        return rag_service.AnswerResult(
            answer="They spent about 21.5 hours on the surface [1].",
            retrieved_passages=passages,
            status=self.status,  # type: ignore[arg-type]
            cited_passages=[1],
            model="stub/rag",
        )


@pytest.fixture
def stub_retrieval() -> Iterator[RetrievalStub]:
    """Replace the RAG retriever and answer step with recording stubs.

    Yields:
        The stub; set `status` or `error` to shape the answer step.
    """
    stub = RetrievalStub()
    with (
        patch.object(rag_retriever, "retrieve_passages", stub.retrieve),
        patch.object(rag_service, "build_answer", stub.build_answer),
    ):
        yield stub
