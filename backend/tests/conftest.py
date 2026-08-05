# Built with Spec4 AI - https://spec4.ai

from collections.abc import Iterator
import os

# Local test defaults so Settings() validates without a real Neon connection.
# The DB itself is stubbed out per-test via a dependency override.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("CORS_ORIGIN", "http://localhost:5173")
os.environ.setdefault("PORT", "8000")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("EXA_API_KEY", "test-exa-key")

# Force-disable Sentry for the whole suite. Importing backend.app.main runs
# configure_sentry() at import time, and Settings reads the repo-root .env
# regardless of cwd -- so without this, a developer with a real SENTRY_DSN in
# .env ships test errors to the live Sentry project (and pays a network flush
# on every run). Assigned, not setdefault: an exported DSN must not win either.
os.environ["SENTRY_DSN"] = ""

# Force-clear the moderation key for the whole suite, for the same reason as
# SENTRY_DSN above and one the suite learned the hard way: a developer with a
# real OPENAI_API_KEY in .env would have every test that posts free text make a
# live call to OpenAI's moderation endpoint. Five tool-use tests did exactly
# that the moment the shared gate was wired in -- they still passed, and took
# 45 seconds. Assigned, not setdefault: an exported key must not win either.
#
# With it cleared the gate fails closed, so any endpoint that reaches the real
# moderator refuses. That is deliberate: it makes "this test forgot to override
# `get_moderator`" a visible failure rather than a silent network call.
os.environ["OPENAI_API_KEY"] = ""

# Give every routing provider a key, so chain-shape assertions do not depend on
# which providers the developer running the suite happens to have configured.
#
# `configured_chain()` drops the slugs of any provider with no key, so without
# this a machine lacking GROQ_API_KEY sees a shorter chain than one that has it
# and tests like "active_chain returns the full chain" fail for a reason that
# has nothing to do with the code. That was latent while the only unkeyed
# provider was one most developers had, and it surfaced the moment a third
# provider was trialled.
#
# Derived from PROVIDER_CREDENTIALS rather than listed, so a third provider is
# covered by declaring it and nothing else. `setdefault`, not assignment: a real
# key stays usable for the probes, which are run deliberately and not by pytest.
from backend.app.services.model_registry import PROVIDER_CREDENTIALS  # noqa: E402

for _credential in PROVIDER_CREDENTIALS.values():
    os.environ.setdefault(_credential.env_var, f"test-{_credential.env_var.lower()}")

import pytest  # noqa: E402


@pytest.fixture
def allow_all_moderation() -> Iterator[None]:
    """Override the moderation gate app-wide with an always-allow stub.

    For tests whose subject is something else entirely and which would
    otherwise be refused at the gate. A fixture rather than an autouse default,
    so a test that *should* be checking the gate cannot pass by accident.

    Yields:
        None. The overrides are removed on teardown.
    """
    from backend.app.main import app
    from backend.app.services.moderation import (
        ModerationCategory,
        ModerationVerdict,
        get_moderator,
        get_stateless_moderator,
    )

    async def _allow(_text: str, _context: str) -> ModerationVerdict:
        return ModerationVerdict(
            allowed=True, category=ModerationCategory.OK, visitor_message="allowed"
        )

    async def _provider() -> object:
        return _allow

    app.dependency_overrides[get_moderator] = _provider
    app.dependency_overrides[get_stateless_moderator] = _provider
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_moderator, None)
        app.dependency_overrides.pop(get_stateless_moderator, None)
