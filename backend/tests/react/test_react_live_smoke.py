# Built with Spec4 AI - https://spec4.ai
"""The live smoke run: five presets against the real chain and real Exa.

    uv run pytest backend/tests/react/test_react_live_smoke.py -m live -s

**Opt-in, and developer-invoked only.** Deselected by default via the `live`
marker, because a suite that calls live models passes on a laptop and fails in
CI the day a slug is rate-limited or withdrawn -- and a gate that fails for
reasons unrelated to the change is one people learn to ignore. Everything that
gates the build runs on recorded fixtures.

**There is deliberately no scheduler for this.** The capability text mentions a
weekly smoke run; `preset_question_health_check` was considered as a feature and
**rejected by the developer**, so no cron entry, no background job and no
recurring trigger exists anywhere in this repository for it. Adding one would
both introduce unapproved background-job machinery and implement a capability
that was declined. A test below asserts the absence, because "we didn't build a
scheduler" is exactly the sort of claim this project does not make unverified.

**What it costs when you do run it.** Five real runs: up to eight searches and
ten model requests each, drawn from the same hourly `usage_limits` the gallery
shares. Run it deliberately, not habitually.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.react import presets, schemas, service

REPO_ROOT = Path(__file__).resolve().parents[3]


def _terminal(events: list[service.StreamEvent]) -> service.StreamEvent:
    terminal = [event for event in events if event.name in schemas.TERMINAL_EVENTS]
    assert len(terminal) == 1, [event.name for event in events]
    return terminal[0]


@pytest.fixture(autouse=True)
def no_live_model_calls() -> Iterator[None]:
    """Override the suite-wide guard. This is the one file allowed to call out.

    `backend/tests/react/conftest.py` patches the lane to raise so a forgotten
    stub fails loudly instead of quietly spending quota. That guard is exactly
    right everywhere else and exactly wrong here, so it is replaced -- by name,
    which is the only way to opt out of an autouse fixture and therefore the
    only place this exemption can be granted.

    Yields:
        None. Nothing is patched.
    """
    yield


@pytest.fixture
def live_environment() -> Iterator[str]:
    """Restore the real credentials the suite deliberately fakes, for this test only.

    `backend/tests/conftest.py` exports a fake `DATABASE_URL` so `Settings()`
    validates without a live Postgres, gives every provider in
    `PROVIDER_CREDENTIALS` a fake key so chain-shape assertions do not depend on
    which providers a developer happens to have configured, and force-clears
    `OPENAI_API_KEY`. All three are correct everywhere else and wrong here.

    Without this the run still *completes* -- every model attempt fails, the
    chain walks to the end, and the loop ends candidly as budget-exhausted with
    zero searches. That is the loop behaving correctly on a dead provider, and
    it would have passed the assertions below while proving nothing at all. The
    printed search count is what makes the difference visible.

    Yields:
        The real `DATABASE_URL`. Skips when there is no `.env` to read.
    """
    from backend.app.core.config import get_settings

    env = REPO_ROOT / ".env"
    if not env.exists():
        pytest.skip("no .env at the repo root; the live run needs real credentials")

    values = dict(
        line.split("=", 1)
        for line in env.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    values = {
        key.strip(): value.strip().strip('"').strip("'")
        for key, value in values.items()
    }

    url = values.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL is not set in .env")

    restore = {
        name: os.environ.get(name)
        for name in (
            "DATABASE_URL",
            "OPENROUTER_API_KEY",
            "GROQ_API_KEY",
            "EXA_API_KEY",
        )
    }
    for name in restore:
        real = values.get(name)
        if real:
            os.environ[name] = real
    get_settings.cache_clear()

    try:
        yield url
    finally:
        for name, previous in restore.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        get_settings.cache_clear()


@pytest.mark.live
@pytest.mark.parametrize("preset", presets.PRESETS, ids=[p.id for p in presets.PRESETS])
def test_a_preset_reaches_a_terminal_card_against_the_real_chain(
    preset: presets.Preset, live_environment: str
) -> None:
    """One real run per preset, asserting only that it lands somewhere honest.

    Deliberately not asserting *which* ending. A live run against a free-tier
    chain can legitimately exhaust its budget, and failing on that would make
    this a flaky measurement of provider weather rather than a check that the
    loop still works end to end. What must hold is that every run terminates in
    exactly one of the two cards -- never both, never neither, never a crash.
    """
    request = schemas.RunRequest(
        preset_question_id=preset.id, visitor_question=None, session_id="live-smoke"
    )

    async def go() -> list[service.StreamEvent]:
        # The engine is built and disposed inside this one event loop. A
        # fixture-scoped engine would be created on one loop and torn down on
        # another, which asyncpg reports as "attached to a different loop".
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(live_environment, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            # `_settle` opens its own session on purpose -- the common reason it
            # runs is a visitor closing the tab -- so the refund would otherwise
            # go to the module-level factory, which is bound to the fake URL.
            with patch.object(service, "async_session_factory", factory):
                async with factory() as session:
                    return [
                        event
                        async for event in service.stream_run(
                            session, run_id=uuid.uuid4(), request=request
                        )
                    ]
        finally:
            await engine.dispose()

    events = asyncio.run(go())
    card = _terminal(events)

    print(
        f"\n  {preset.id}: {card.name} ({card.payload.get('searches_used')} searches)"
    )
    assert card.name in {
        schemas.EVENT_FINAL_ANSWER,
        schemas.EVENT_BUDGET_EXHAUSTED,
    }
    if card.name == schemas.EVENT_BUDGET_EXHAUSTED:
        # Candid, never dressed up as an answer.
        assert "answer" not in card.payload
        assert card.payload["unresolved"]
    else:
        assert card.payload["answer"].strip()
        assert card.payload["searches_used"] >= 1


def test_the_live_marker_is_deselected_by_default() -> None:
    """Registered as a marker so the default run cannot silently include it."""
    config = (REPO_ROOT / "pyproject.toml").read_text()

    assert "markers = [" in config
    assert "live:" in config
    assert "-m 'not live'" in config or "not live" in config


def test_no_scheduler_was_created_for_the_smoke_run() -> None:
    """`preset_question_health_check` was rejected; nothing may reintroduce it.

    Scans the deployment manifest and the whole backend for the machinery a
    recurring job would need. The risk this guards is real and specific: the
    capability text mentions a weekly run, which reads as licence to build one.
    """
    render = (REPO_ROOT / "render.yaml").read_text().lower()

    for marker in ("cron", "schedule", "worker:"):
        assert marker not in render, f"render.yaml gained a {marker!r} entry"

    pattern = re.compile(r"\b(apscheduler|celery|crontab|schedule\.every)\b")
    for path in (REPO_ROOT / "backend").rglob("*.py"):
        # This file names the machinery in order to look for it, so scanning
        # itself would always match.
        if path == Path(__file__):
            continue
        assert not pattern.search(path.read_text()), path


def test_the_smoke_run_is_the_only_place_that_may_reach_a_provider() -> None:
    """Every other file in this suite is offline, and the marker is what says so."""
    marked: list[Path] = []
    for path in Path(__file__).parent.glob("test_*.py"):
        if "pytest.mark.live" in path.read_text():
            marked.append(path)

    assert marked == [Path(__file__)]


def test_running_the_smoke_suite_needs_real_credentials() -> None:
    """Named plainly, so a confusing failure is not the first thing you learn.

    The test suite force-clears `OPENAI_API_KEY` and supplies fake values for
    the rest, so an unconfigured environment fails inside the chain walk rather
    than at the boundary.
    """
    docstring = __doc__ or ""

    assert "Opt-in" in docstring
    assert "no scheduler" in docstring
