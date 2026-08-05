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

**Nothing legacy is un-excluded, and that is asserted too.** The pre-v5 paths
keep exactly the exemption they had. Cleaning one up is a deliberate change,
not a side effect of this phase.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

RUFF_EXCLUDE: list[str] = CONFIG["tool"]["ruff"]["extend-exclude"]
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


def test_the_react_package_is_covered_by_a_wildcard_not_an_inventory() -> None:
    """So a module added later is gated on creation, not when someone remembers.

    The alternative -- naming each file -- is the arrangement that has to be
    maintained, and the failure mode is silent. Verified in Phase 2 by injecting
    a type error into a new module and confirming a bare `mypy` reported it.
    """
    enabled = [
        override for override in OVERRIDES if override.get("ignore_errors") is False
    ]
    named: set[str] = set()
    for override in enabled:
        named.update(_module_patterns(override))

    assert "backend.app.react.*" in named
    assert "backend.app.api.react" in named


def test_the_test_tree_is_in_the_checked_file_set() -> None:
    """`files` lists it, so the gate holds without an explicit path argument.

    It had never been checked before v7: `mypy backend` reported 406 errors
    across 45 files because the config's `files` covered only `backend/app`,
    and passing an explicit path overrode it. A gate nobody runs by default is
    a gate that decays.
    """
    assert MYPY["files"] == ["backend/app", "backend/tests"]


def test_no_legacy_path_was_un_excluded_by_this_phase() -> None:
    """Instruction 17's second half, and the reason the inventories are long.

    Widening the gate to a pre-v5 path would bury this revision's diff in a
    repo-wide reformat, which is the whole reason the scoping exists. These are
    the paths that must still be carrying their exemption.
    """
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
        assert legacy in RUFF_EXCLUDE, f"{legacy} lost its ruff exemption"


def test_the_files_this_phase_appended_to_kept_their_own_gating() -> None:
    """Appending to a file does not change which gate it is in, in either direction.

    `services/web_search.py` and `core/observability.py` were re-enabled for
    mypy when v7 wrote in them, and both are still on. `services/shared.py`,
    `db/models.py`, `core/config.py` and `main.py` were only appended to and
    keep exactly the exclusion they had -- deliberately, since re-enabling one
    would mean reformatting a legacy path inside a phase that owns none of it.
    """
    assert _mypy_verdict("backend.app.services.web_search") is True
    assert _mypy_verdict("backend.app.core.observability") is True

    assert _mypy_verdict("backend.app.services.shared") is False
    assert _mypy_verdict("backend.app.core.config") is False
    assert _mypy_verdict("backend.app.main") is False


def test_the_migration_is_where_alembic_and_the_gate_both_expect_it() -> None:
    """0013 lives under the excluded migrations tree, like every revision before it."""
    migration = REPO_ROOT / "backend/app/db/migrations/versions/0013_react_runs.py"

    assert migration.exists()
    assert _is_ruff_excluded(str(migration.relative_to(REPO_ROOT))) == "backend/app/db"
