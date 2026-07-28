# Built with Spec4 AI - https://spec4.ai
from collections.abc import AsyncGenerator

from fastapi.testclient import TestClient

from backend.app.db.session import get_db_session
from backend.app.main import app


class _FakeResult:
    def scalar_one(self) -> int:
        return 1


class _WorkingSession:
    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        return _FakeResult()


class _BrokenSession:
    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        raise ConnectionError("could not connect to server")


async def _override_working() -> AsyncGenerator[_WorkingSession, None]:
    yield _WorkingSession()


async def _override_broken() -> AsyncGenerator[_BrokenSession, None]:
    yield _BrokenSession()


def test_health_returns_ok_when_db_connected() -> None:
    app.dependency_overrides[get_db_session] = _override_working
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "connected"}


def test_health_returns_503_when_db_unreachable() -> None:
    app.dependency_overrides[get_db_session] = _override_broken
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["db"] == "disconnected"
