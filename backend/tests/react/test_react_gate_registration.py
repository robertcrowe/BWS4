# Built with Spec4 AI - https://spec4.ai
"""Every file this revision wrote is inside the lint and type gates.

**A green lint run proves nothing on its own**, and that is this phase's own
named change risk. `pyproject.toml`'s exclusion inventories are per-file, so a
new module dropped inside an already-excluded package is silently ungated --
`uv run ruff check .` exits zero either way, and `mypy` prints a success summary
having never looked at it. The sweep can therefore be "completed" without
changing anything, which is exactly the shape of an audit that is never done.

So the sweep is a test rather than an inspection. It reads the real
`pyproject.toml`, walks the real files, and fails if any file this revision
added falls inside a ruff exclusion or under a mypy override that turns errors
off. Adding a file to the ReAct slice keeps it honest automatically; adding one
somewhere excluded fails here with the path named.

**v10 Phase 4 removed every ruff exclusion**, so the ruff half of the sweep
now asserts that the inventory is gone rather than that legacy paths keep it.
**v10 Phase 5 did the same for mypy**: every `ignore_errors` override is gone
and `files` covers the whole `backend` package, so the mypy half now asserts
that nothing switches errors off rather than that particular paths stay on.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

RUFF_EXCLUDE: list[str] = CONFIG["tool"]["ruff"].get("extend-exclude", [])
MYPY = CONFIG["tool"]["mypy"]
OVERRIDES: list[dict[str, object]] = MYPY.get("overrides", [])

#: Everything v7 created. Modified legacy files are handled separately below --
#: appending to an excluded file does not un-exclude it, and instruction 17
#: forbids doing so in this phase.
NEW_PATHS = [
    "backend/app/api/react.py",
    "backend/app/react",
    "backend/tests/react",
]


def _is_ruff_excluded(relative: str) -> str | None:
    """Return the exclusion entry covering this path, or None."""
    for entry in RUFF_EXCLUDE:
        if relative == entry or relative.startswith(entry.rstrip("/") + "/"):
            return entry
    return None


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_patterns(override: dict[str, object]) -> list[str]:
    """The `module` field of one override, normalised to a list."""
    patterns = override.get("module")
    if isinstance(patterns, str):
        return [patterns]
    if isinstance(patterns, list):
        return [str(name) for name in patterns]
    return []


def _mypy_verdict(module: str) -> bool | None:
    """Whether errors are reported for this module. Later overrides win.

    Returns:
        True when checked, False when `ignore_errors` is on, None when no
        override matches and the file-level `strict` default applies.
    """
    verdict: bool | None = None
    for override in OVERRIDES:
        names = _module_patterns(override)
        for name in names:
            if name.endswith(".*"):
                stem = name[:-2]
                matched = module == stem or module.startswith(stem + ".")
            else:
                matched = module == name
            if matched:
                verdict = not bool(override.get("ignore_errors", False))
    return verdict


def _python_files(relative: str) -> list[Path]:
    target = REPO_ROOT / relative
    if target.is_file():
        return [target]
    return sorted(
        path for path in target.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_the_sweep_actually_has_files_to_sweep() -> None:
    """A sweep over an empty list is the audit that passes by doing nothing."""
    found = [path for target in NEW_PATHS for path in _python_files(target)]

    assert len(found) >= 15, f"only found {len(found)} files to check"


def test_no_file_this_revision_added_sits_inside_a_ruff_exclusion() -> None:
    """The documented trap: a new file inside an already-excluded package."""
    for target in NEW_PATHS:
        for path in _python_files(target):
            relative = str(path.relative_to(REPO_ROOT))
            entry = _is_ruff_excluded(relative)
            assert entry is None, f"{relative} is excluded from ruff by {entry!r}"


def test_every_file_this_revision_added_is_type_checked() -> None:
    """`ignore_errors = false`, or the strict default with nothing turning it off."""
    for target in NEW_PATHS:
        for path in _python_files(target):
            module = _module_name(path)
            verdict = _mypy_verdict(module)
            assert verdict is not False, f"{module} has mypy errors switched off"


def test_no_mypy_override_switches_errors_off() -> None:
    """So a module added later is gated on creation, not when someone remembers.

    v7 met this with a `backend.app.react.*` wildcard re-enabling errors inside
    a config that exempted its neighbours. v10 Phase 5 removed every exemption,
    so the strict default now covers the ReAct package -- and everything else
    -- with no override naming it, and none may toggle `ignore_errors` again.
    """
    for override in OVERRIDES:
        assert "ignore_errors" not in override, f"override {override!r}"

    assert _mypy_verdict("backend.app.react.service") is None
    assert _mypy_verdict("backend.app.api.react") is None


def test_the_test_tree_is_in_the_checked_file_set() -> None:
    """`files` lists it, so the gate holds without an explicit path argument.

    It had never been checked before v7: `mypy backend` reported 406 errors
    across 45 files because the config's `files` covered only `backend/app`,
    and passing an explicit path overrode it. A gate nobody runs by default is
    a gate that decays. Since v10 Phase 5 it is the whole `backend` package.
    """
    assert MYPY["files"] == ["backend"]
    assert MYPY["strict"] is True
    assert "exclude" not in MYPY


def test_no_legacy_path_is_excluded_from_ruff() -> None:
    """v10 Phase 4 un-excluded every pre-v5 path; none may creep back in.

    These are the paths that carried an exemption until then. The inventory
    itself must be empty too, and no `exclude` may replace `extend-exclude`.
    """
    assert RUFF_EXCLUDE == []
    assert "exclude" not in CONFIG["tool"]["ruff"]
    for legacy in (
        "backend/app/planning",
        "backend/app/rag",
        "backend/app/tools",
        "backend/app/chained_calls",
        "backend/app/single_call",
        "backend/app/embeddings",
        "backend/app/db",
        "backend/app/main.py",
        "backend/app/core/config.py",
        "backend/app/services/shared.py",
    ):
        assert _is_ruff_excluded(legacy) is None, f"{legacy} is excluded from ruff"


def test_the_files_this_phase_appended_to_are_type_checked() -> None:
    """The files v7 appended to are under the strict default like everything else.

    v7 left `services/shared.py`, `core/config.py` and `main.py` with the
    exclusion they had and re-enabled `services/web_search.py` and
    `core/observability.py`. v10 Phase 5 removed every exclusion, so all five
    now fall to the strict default with no override matching them.
    """
    for module in (
        "backend.app.services.web_search",
        "backend.app.core.observability",
        "backend.app.services.shared",
        "backend.app.core.config",
        "backend.app.main",
    ):
        assert _mypy_verdict(module) is None, f"{module} is matched by an override"


def test_the_migration_is_where_alembic_and_the_gate_both_expect_it() -> None:
    """0013 lives under the migrations tree, which ruff now lints like the rest."""
    migration = REPO_ROOT / "backend/app/db/migrations/versions/0013_react_runs.py"

    assert migration.exists()
    assert _is_ruff_excluded(str(migration.relative_to(REPO_ROOT))) is None
