---
{
  "phase_number": 4,
  "total_phases": 8,
  "phase_title": "Whole-Backend Ruff Gate",
  "phase_summary": "Remove every Ruff exclusion so all of backend/ (main.py, older routers, services, tests) is linted and formatted. Fix all findings and reformat the affected files without changing any behaviour.",
  "features": [
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "extended",
      "scope_note": "Full lint coverage (item 1, Ruff half); mypy is Phase 5."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "Ruff",
      "pytest",
      "uv"
    ],
    "configurations": "pyproject.toml [tool.ruff] must end with no extend-exclude entries. Real GROQ_API_KEY and OPENAI_API_KEY are needed for pytest runs."
  },
  "instructions": [
    "Open pyproject.toml and list every entry in tool.ruff extend-exclude (and any per-file or exclude settings that skip files). Record them in the review note under a 'Ruff exclusions removed' heading.",
    "Remove all the exclusions. Do not add noqa blanket comments, per-file-ignores or new exclusions to compensate. Keep the existing rule selection, line length 88 and double quotes.",
    "Run `uv run ruff check .` and record the finding count (about 366 are expected). Fix findings by category in small batches. After each batch run `uv run pytest -x -q` to catch behaviour changes early.",
    "Run `uv run ruff format .` to reformat the affected files (about 57 expected). Confirm that the formatting diff for each file contains only whitespace, quoting and wrapping changes.",
    "Prefer real fixes over suppression. A targeted `# noqa: <code>` with a one-line reason is allowed only where the fix would change behaviour, and each one is listed in the review note.",
    "Preserve contracts: do not change routes, response shapes, usage caps, visitor-facing strings, the Chained Calls 200 with 'critique_failed' status, or the Router route-id constants. If a lint fix would change visible behaviour or require editing a test, stop and list it in the review note as flagged instead.",
    "If a finding reveals a real bug (for example an unawaited coroutine, a mutable default argument that is actually shared, or a shadowed exception), do not fix it silently. List it under a separate 'Real bugs surfaced — owner decision' heading in the review note with file, line and a description, and apply only a behaviour-neutral lint resolution.",
    "Do not touch the single uvicorn worker setting or the streaming generator session rule. Do not add pre-commit hooks or CI."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "A mass reformat and several hundred fixes in one pass can hide a behaviour change, for example auto-fixes that reorder imports with side effects or alter exception handling.",
    "mitigation_strategy": "Fix in batches, run the full backend test suite after each, avoid `--unsafe-fixes` unless each result is reviewed, and keep a before/after pytest count. Flag rather than fix anything contract-affecting."
  },
  "verification": "`uv run ruff check .` exits 0 with no extend-exclude entries present (`grep -n \"extend-exclude\\|exclude\" pyproject.toml` shows none under [tool.ruff]); `uv run ruff format --check .` exits 0; `uv run pytest` passes with the same counts as the Phase 1 baseline (live tests deselected); the frontend Vitest suite is unaffected and passes. The review note lists all noqa suppressions and any flagged real bugs.",
  "references": [
    {
      "standard": "Ruff",
      "url": "https://docs.astral.sh/ruff/"
    }
  ]
}
---

# Phase 4 of 8: Whole-Backend Ruff Gate

Remove every Ruff exclusion so all of backend/ (main.py, older routers, services, tests) is linted and formatted. Fix all findings and reformat the affected files without changing any behaviour.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Codebase_Quality_And_Config_Cleanup — product feature — extended in this phase

*Scope for this phase: Full lint coverage (item 1, Ruff half); mypy is Phase 5.*

A behaviour-preserving cleanup that brings the whole codebase under full lint and type checking, makes the required credentials truly required, removes stale references to the retired host, and documents previously unrecorded edits.

**Invocation**

- Trigger: Maintainers run this one-time cleanup before the next release; the checks then run in the normal quality gate.

**Inputs**

- `Existing codebase` (set of source files, required) — All source, tests, docs and configuration, including older modules currently excluded from checks.
- `Unrecorded edits` (list of items, required) — Site metadata, the shared generation service, project documentation, assistant settings, project configuration and ReAct frontend test changes awaiting review.

**Outputs**

- Primary: A fully checked, consistently formatted codebase with no exclusions, updated documentation, and a written list of reviewed edits and any items flagged for the owner's decision.
- Format: Updated files plus a review note
- Schema notes: No visible behaviour change except that startup now fails when either required credential is missing. Chained Calls 'critique_failed' behaviour and the Router route-id contract are unchanged. Anything that looks unintended is flagged, not silently reverted.

**Success criteria**

- No lint or type-check exclusions remain and all findings are fixed.
- Example app behaviour, routes, response shapes, usage caps and visitor messages are unchanged.
- Startup fails clearly when either required credential is missing, with no placeholders or opt-out; tests require real credentials and the live smoke run stays opt-in.
- No mention of the retired host remains in code, docs, configuration or release files, and the startup description matches the always-on instance.
- Each unrecorded edit is documented as kept or flagged for the owner.
- A one-time check confirms the Router code and tests are covered by the checks.
- A failure while preparing route descriptions is logged, startup still succeeds, and the Router shows its unavailable state with a retry action until preparation succeeds.

**Failure modes**

- Fixing findings accidentally changes behaviour (likelihood: medium) — mitigation: Run the full test suite and compare visible behaviour before and after.
- Stricter credential rule breaks test runs without credentials (likelihood: high) — mitigation: Document that real credentials are needed for every test run and communicate the change to maintainers.
- An unintended edit is kept without review (likelihood: medium) — mitigation: Inspect each unrecorded edit and flag doubtful ones for the owner.
- A stale reference to the retired host is missed (likelihood: medium) — mitigation: Sweep all code, docs, configuration and release files for it.

- depends on: shared_framework_services, router_example_app, self_hosted_deployment (build these no later than `codebase_quality_and_config_cleanup`)
- entities: Source File, Check Finding, Credential, Review Note

## Tech Stack

**Dependencies:**

- Ruff
- pytest
- uv

**Configurations:** pyproject.toml [tool.ruff] must end with no extend-exclude entries. Real GROQ_API_KEY and OPENAI_API_KEY are needed for pytest runs.

**Project-wide stack** (applies to every phase):

- FastAPI
- uvicorn
- SQLAlchemy
- asyncpg
- Alembic
- Pydantic
- tenacity
- pydantic-settings
- structlog
- sentry-sdk
- pytest
- Ruff
- mypy
- React
- react-dom
- Vite
- @vitejs/plugin-react
- React Router
- TanStack Query
- Tailwind CSS
- postcss
- autoprefixer
- typescript
- oxlint
- Vitest
- jsdom
- React Testing Library
- @testing-library/jest-dom
- @testing-library/user-event
- @types/node
- @types/react
- @types/react-dom
- @sentry/react

## Instructions

1. Open pyproject.toml and list every entry in tool.ruff extend-exclude (and any per-file or exclude settings that skip files). Record them in the review note under a 'Ruff exclusions removed' heading.
2. Remove all the exclusions. Do not add noqa blanket comments, per-file-ignores or new exclusions to compensate. Keep the existing rule selection, line length 88 and double quotes.
3. Run `uv run ruff check .` and record the finding count (about 366 are expected). Fix findings by category in small batches. After each batch run `uv run pytest -x -q` to catch behaviour changes early.
4. Run `uv run ruff format .` to reformat the affected files (about 57 expected). Confirm that the formatting diff for each file contains only whitespace, quoting and wrapping changes.
5. Prefer real fixes over suppression. A targeted `# noqa: <code>` with a one-line reason is allowed only where the fix would change behaviour, and each one is listed in the review note.
6. Preserve contracts: do not change routes, response shapes, usage caps, visitor-facing strings, the Chained Calls 200 with 'critique_failed' status, or the Router route-id constants. If a lint fix would change visible behaviour or require editing a test, stop and list it in the review note as flagged instead.
7. If a finding reveals a real bug (for example an unawaited coroutine, a mutable default argument that is actually shared, or a shadowed exception), do not fix it silently. List it under a separate 'Real bugs surfaced — owner decision' heading in the review note with file, line and a description, and apply only a behaviour-neutral lint resolution.
8. Do not touch the single uvicorn worker setting or the streaming generator session rule. Do not add pre-commit hooks or CI.

## Risk Assessment

**Potential bottlenecks:**

A mass reformat and several hundred fixes in one pass can hide a behaviour change, for example auto-fixes that reorder imports with side effects or alter exception handling.

**Mitigation strategy:**

Fix in batches, run the full backend test suite after each, avoid `--unsafe-fixes` unless each result is reviewed, and keep a before/after pytest count. Flag rather than fix anything contract-affecting.

## Verification

`uv run ruff check .` exits 0 with no extend-exclude entries present (`grep -n "extend-exclude\|exclude" pyproject.toml` shows none under [tool.ruff]); `uv run ruff format --check .` exits 0; `uv run pytest` passes with the same counts as the Phase 1 baseline (live tests deselected); the frontend Vitest suite is unaffected and passes. The review note lists all noqa suppressions and any flagged real bugs.

## References

- [Ruff](https://docs.astral.sh/ruff/)
