# Built with Spec4 AI - https://spec4.ai

import os
from collections.abc import Iterator

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

# GROQ_API_KEY and OPENAI_API_KEY are deliberately NOT given defaults here.
# Both are required in every environment, tests included, with no placeholder:
# a pytest run needs the real keys in the shell or the repo-root .env, and
# Settings refuses to construct without them. Live use of those keys is kept
# out of the suite by fixtures instead -- see `_moderation_endpoint_offline`
# below and `tests/react/conftest.py` -- and by the `live` marker, which stays
# deselected by default.

# Give every *optional* routing provider a key, so chain-shape assertions do not
# depend on which providers the developer running the suite happens to have
# configured.
#
# `configured_chain()` drops the slugs of any provider with no key, so without
# this a machine lacking a provider's key sees a shorter chain than one that has it
# and tests like "active_chain returns the full chain" fail for a reason that
# has nothing to do with the code. That was latent while the only unkeyed
# provider was one most developers had, and it surfaced the moment a third
# provider was trialled.
#
# Derived from PROVIDER_CREDENTIALS rather than listed, so a third provider is
# covered by declaring it and nothing else. `setdefault`, not assignment: a real
# key stays usable for the probes, which are run deliberately and not by pytest.
# A provider whose Settings field is required (Groq) is skipped: faking it would
# be exactly the placeholder the required-credential contract rules out.
from backend.app.core.config import Settings  # noqa: E402
from backend.app.services.model_registry import PROVIDER_CREDENTIALS  # noqa: E402

for _credential in PROVIDER_CREDENTIALS.values():
    if Settings.model_fields[_credential.settings_attr].is_required():
        continue
    os.environ.setdefault(_credential.env_var, f"test-{_credential.env_var.lower()}")

import pytest  # noqa: E402


class _OfflineHttpx:
    """The `httpx` module as `services/moderation.py` sees it under pytest.

    Every attribute is the real one except `AsyncClient`, which refuses to be
    constructed. Installed on the moderation module only, so nothing else that
    uses httpx is affected, and a test that patches
    `backend.app.services.moderation.httpx.AsyncClient` itself still wins.
    """

    def __getattr__(self, name: str) -> object:
        import httpx

        return getattr(httpx, name)

    def AsyncClient(self, *_args: object, **_kwargs: object) -> object:  # noqa: N802
        raise RuntimeError(
            "the moderation endpoint is offline under pytest; override "
            "get_moderator or use the allow_all_moderation fixture"
        )


@pytest.fixture(autouse=True)
def _moderation_endpoint_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real OPENAI_API_KEY from reaching OpenAI during the suite.

    The suite used to force-clear the key for this, and learned why the hard
    way: a developer with a real key in .env had every test that posts free
    text make a live moderation call. Five tool-use tests did exactly that the
    moment the shared gate was wired in -- they still passed, and took 45
    seconds. The key is now required, so it cannot be cleared; the endpoint is
    made unreachable instead.

    The effect is the same as before: an un-overridden gate fails closed and
    refuses, which makes "this test forgot to override `get_moderator`" a
    visible failure rather than a silent network call.
    """
    from backend.app.services import moderation

    monkeypatch.setattr(moderation, "httpx", _OfflineHttpx())


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
