# Built with Spec4 AI - https://spec4.ai
"""GROQ_API_KEY and OPENAI_API_KEY are required in every environment.

Cites `nfr_the_service_refuses_to_start_when_a_required_credential_is_missing`.
There is no placeholder default and no opt-out flag, and the check is not
skipped under tests -- so what these tests assert is that startup configuration
fails, and that the operator is told *which* credential is missing rather than
handed a list of everything that could be.

The repo-root .env is disabled for each test, so the outcome depends only on the
process environment the test arranges. The values set here are not credentials;
they exist only to be removed one at a time.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings, get_settings

CREDENTIALS = ("GROQ_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Disable the .env file, set both keys, and keep the settings cache clean.

    Yields:
        None. The cache is cleared on teardown so later tests rebuild the real,
        .env-backed Settings rather than inheriting this test's.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in CREDENTIALS:
        monkeypatch.setenv(name, f"value-for-{name.lower()}")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _first_line_of_startup_error() -> str:
    with pytest.raises(RuntimeError) as excinfo:
        get_settings()
    return str(excinfo.value).splitlines()[0]


@pytest.mark.parametrize("missing", CREDENTIALS)
def test_startup_fails_naming_the_one_missing_key(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)

    first_line = _first_line_of_startup_error()

    assert first_line == f"Invalid or missing configuration: {missing}."


def test_startup_fails_naming_both_keys_when_both_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in CREDENTIALS:
        monkeypatch.delenv(name)

    first_line = _first_line_of_startup_error()

    assert first_line == (
        "Invalid or missing configuration: GROQ_API_KEY, OPENAI_API_KEY."
    )


@pytest.mark.parametrize("missing", CREDENTIALS)
@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_value_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str, blank: str
) -> None:
    """`.env.example` ships `NAME=`; copying it unfilled must not pass."""
    monkeypatch.setenv(missing, blank)

    first_line = _first_line_of_startup_error()

    assert first_line == f"Invalid or missing configuration: {missing}."


@pytest.mark.parametrize("missing", CREDENTIALS)
def test_settings_itself_refuses_to_construct(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """The check lives in Settings validation, not only in `get_settings`."""
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError) as excinfo:
        # Every field comes from the environment here, which mypy cannot see.
        Settings()  # type: ignore[call-arg]

    assert [error["loc"] for error in excinfo.value.errors()] == [(missing.lower(),)]


def test_the_message_states_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator learns the rule, not just the symptom."""
    monkeypatch.delenv("GROQ_API_KEY")

    with pytest.raises(RuntimeError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    assert "required in every environment" in message
    assert "no placeholder and no opt-out" in message


def test_both_keys_present_is_enough() -> None:
    settings = get_settings()

    assert settings.groq_api_key == "value-for-groq_api_key"
    assert settings.openai_api_key == "value-for-openai_api_key"
