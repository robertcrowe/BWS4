# Built with Spec4 AI - https://spec4.ai
"""Make a forgotten model stub fail loudly instead of calling a real provider.

**This suite made live provider calls the moment the cycle step landed**, and it
is the third time this project has hit it -- v5's dispatch suite and v6's
explanations suite both did the same thing, and both times the tell was the same:
the tests still passed, and the suite got slower. Here two tests exercised the
re-ask path without patching the lane, so every attempt walked the whole
`GENERATION_MODEL_CHAIN` against fake keys, collecting a 401 per slug. With real
keys in `.env` they would have spent real quota, silently, on every run of the
suite.

The autouse fixture below patches `agent_runtime.run_typed_step` at its point of
use to raise. A test that forgets its own stub therefore fails with a message
naming the problem, rather than quietly reaching the network -- the same shape as
`conftest.py` force-clearing `OPENAI_API_KEY` so an un-overridden moderation gate
fails closed.

Deliberately autouse rather than opt-in. The opposite arrangement puts the
burden on remembering, which is precisely what failed three times.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from backend.app.db.models import AllowanceHold, ReactRun, UsageLimit
from backend.app.react import service
from backend.app.services import agent_runtime


@pytest.fixture(autouse=True)
def no_live_model_calls() -> Any:
    """Refuse any model call this suite did not explicitly stub.

    Yields:
        None. The patch is removed on teardown. A test that wants a model
        patches `agent_runtime.run_typed_step` itself, which replaces this.
    """

    async def refuse(**kwargs: Any) -> Any:
        raise AssertionError(
            "This test reached the real PydanticAI lane. Patch "
            "`agent_runtime.run_typed_step` at its point of use -- a live call "
            f"spends provider quota. Label was {kwargs.get('label')!r}."
        )

    with patch.object(agent_runtime, "run_typed_step", refuse):
        yield


# ---------------------------------------------------------------------------
# The shared offline harness
#
# Phase 8's golden suites drive the *real* `stream_run` with only two things
# replaced: the model lane and Exa's HTTP transport. Everything else -- the
# budget ledger, the duplicate guard, the observation builder, the terminal-card
# decision, the allowance lifecycle -- is production code.
#
# These are fixtures rather than importable helpers because `backend/tests/`
# carries no `__init__.py`, so a sibling module is not importable by path. A
# fixture is the one sharing mechanism this layout offers, and it is why
# `test_react_loop.py`'s own near-identical copies were left in place rather
# than rewritten from under a passing suite.
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = Path(__file__).resolve().parent / "golden"

#: Captured before anything patches it. `web_search.httpx` *is* the httpx
#: module, so patching `httpx.AsyncClient` patches it globally -- a factory that
#: then called `httpx.AsyncClient(...)` would recurse into itself.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return [] if self._value is None else [self._value]


class ReactSession:
    """A fake session that behaves like a store, not a queue of canned rows.

    The loop reserves, releases and redeems against rows it expects to still be
    there, so the repo's usual "pop the next queued result" fake is not enough.
    Which table a `select` wanted is recovered from the compiled statement, the
    trick `test_planning_orchestrator.py` uses.

    Every method suspends. Cancellation is only delivered at a suspension
    point, so a fake that never yields cannot exercise a teardown running inside
    a cancelled task -- which is the bug a live run found in Phase 3.
    """

    def __init__(self, caps: dict[str, int] | None = None) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.limits: dict[str, UsageLimit] = {}
        self.holds: dict[str, AllowanceHold] = {}
        self.runs: list[ReactRun] = []
        self._caps = caps or {}

    async def execute(self, statement: Any, *_a: object, **_k: object) -> _Result:
        await asyncio.sleep(0)
        text = str(statement)
        try:
            params: dict[str, Any] = dict(statement.compile().params)
        except Exception:  # noqa: BLE001 - fake session, best effort
            params = {}
        if "allowance_holds" in text:
            key = next((v for v in params.values() if isinstance(v, str)), None)
            return _Result(self.holds.get(key) if key else None)
        if "usage_limits" in text:
            cap = next((v for v in params.values() if isinstance(v, str)), None)
            return _Result(self.limits.get(cap) if cap else None)
        if "react_runs" in text:
            return _Result(self.runs[0] if self.runs else None)
        return _Result(None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, UsageLimit):
            if obj.capability in self._caps:
                obj.cap = self._caps[obj.capability]
            self.limits[obj.capability] = obj
        elif isinstance(obj, AllowanceHold):
            self.holds[obj.hold_key] = obj
        elif isinstance(obj, ReactRun):
            self.runs.append(obj)

    async def commit(self) -> None:
        await asyncio.sleep(0)
        self.commits += 1

    async def __aenter__(self) -> ReactSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    def used(self, capability: str) -> int:
        row = self.limits.get(capability)
        return row.used if row else 0

    def hold_state(self) -> str | None:
        return next(iter(self.holds.values())).state if self.holds else None

    def hold_units(self) -> int | None:
        return next(iter(self.holds.values())).units if self.holds else None


@pytest.fixture
def react_session() -> Callable[..., ReactSession]:
    """Build a fake session that accumulates usage rows and holds.

    Returns:
        A factory taking an optional capability-cap mapping.
    """

    def make(caps: dict[str, int] | None = None) -> ReactSession:
        return ReactSession(caps)

    return make


class ExaReplay:
    """Serves recorded Exa responses in order, the last one repeating.

    A *sequence* rather than one response, because the loop's interesting cases
    are mixtures: results then nothing, or results then an outage. Requests are
    counted so a test can assert that a refused run issued zero searches.
    """

    def __init__(self, names: list[str]) -> None:
        self._recorded = [json.loads((FIXTURES / name).read_text()) for name in names]
        self.calls = 0

    def _handler(self, _request: httpx.Request) -> httpx.Response:
        recorded = self._recorded[min(self.calls, len(self._recorded) - 1)]
        self.calls += 1
        return httpx.Response(recorded["status_code"], json=recorded["body"])

    def factory(self, *_a: object, **_k: object) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(self._handler))

    def recorded_results(self, call: int) -> list[dict[str, Any]]:
        """The raw results the recording carries for the nth search."""
        recorded = self._recorded[min(call, len(self._recorded) - 1)]
        body: dict[str, Any] = recorded["body"]
        results: list[dict[str, Any]] = body.get("results", [])
        return results


@pytest.fixture
def exa_replay() -> Callable[..., Any]:
    """Replay recorded Exa responses *through the real wrapper*.

    Not a stub of `web_search.search`: the wrapper's own status handling, error
    mapping and field extraction stay in the path, so the observations under
    test are built from the shape Exa really sends rather than the shape this
    project would have chosen.

    Returns:
        A factory taking one or more fixture filenames and returning a context
        manager that also exposes the call count and the raw recordings.
    """

    @contextmanager
    def replay(*names: str) -> Iterator[ExaReplay]:
        state = ExaReplay(list(names) or ["exa_search_multi_result.json"])
        with patch("backend.app.services.web_search.httpx.AsyncClient", state.factory):
            yield state

    return replay


@pytest.fixture
def settle_session() -> Callable[[Any], Any]:
    """Point `_settle`'s own session factory at the test's fake.

    `_settle` deliberately does not reuse the run's session -- the common reason
    it runs is a visitor closing the tab, at which point the streaming
    response's session is being torn down around it. A test that patched only
    the caller's session would watch the refund happen somewhere it cannot see.

    Returns:
        A factory taking the fake session and returning the patch.
    """

    def point_at(session: Any) -> Any:
        return patch.object(service, "async_session_factory", lambda: session)

    return point_at
