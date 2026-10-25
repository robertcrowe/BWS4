---
{
  "phase_number": 5,
  "total_phases": 8,
  "phase_title": "Whole-Backend Mypy Strict Gate",
  "phase_summary": "Remove every mypy exclusion so the whole backend, including main.py, older routers, services and tests, is type-checked under strict mode. All findings are fixed without changing behaviour. Test-requiring fixes and real bugs are flagged, not made silently.",
  "features": [
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "extended",
      "scope_note": "Full type coverage (item 1, mypy half); Ruff was done in Phase 4."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "mypy",
      "Ruff",
      "pytest",
      "uv"
    ],
    "configurations": "pyproject.toml [tool.mypy] stays strict with no exclude, no per-module ignore_errors overrides and no files list that omits parts of backend/."
  },
  "instructions": [
    "Open pyproject.toml and list every mypy scoping mechanism: exclude patterns, `files`, per-module `ignore_errors` or `follow_imports` overrides. Record them in the review note under a 'mypy exclusions removed' heading.",
    "Remove them so `uv run mypy` checks all of backend/ (including backend/app/main.py, backend/tests/ and every older slice) in strict mode. Third-party stub gaps may use a narrow per-module `ignore_missing_imports` override only for that library, and each is listed in the review note.",
    "Run `uv run mypy` and record the error count. Fix errors slice by slice: add precise annotations, narrow Optional values, and type the dependency-override helpers in tests. Avoid `Any` and `# type: ignore`. A `# type: ignore[code]` is allowed only with a reason comment, and each is listed in the review note.",
    "After each slice run `uv run pytest -x -q` and `uv run ruff check . && uv run ruff format --check .` so Phase 4's gate stays green.",
    "Do not change a test to satisfy mypy. If a type fix would require changing a test's logic or assertions, leave the test and record it under 'Flagged: type fix requires test change' in the review note with file and error.",
    "Do not change runtime behaviour. Preserve get_settings, run_typed_step, get_db_session and moderate signatures and semantics, the Chained Calls 200 with 'critique_failed' contract and the Router route-id constants.",
    "If mypy surfaces a real bug (for example a value that can be None at runtime, or a wrong return type), list it under 'Real bugs surfaced — owner decision' and add only a behaviour-neutral annotation or narrowing."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Strict mode over untyped legacy code can produce hundreds of errors, and annotation fixes that add runtime `assert` or `cast` calls can alter behaviour. Third-party library typing gaps (litellm, sentence-transformers, pydantic-ai) can cause noisy errors.",
    "mitigation_strategy": "Work slice by slice with tests after each batch. Use typing-only changes (annotations, TypedDict, Protocol, narrowing via existing conditionals). Keep every suppression minimal and documented. Flag anything that touches tests."
  },
  "verification": "`uv run mypy` exits 0 with no exclusions in pyproject.toml; `uv run ruff check .` and `uv run ruff format --check .` still exit 0; `uv run pytest` passes with the Phase 1 baseline counts. The review note lists every type: ignore, stub override, flagged test-affecting fix and surfaced real bug.",
  "references": [
    {
      "standard": "mypy",
      "url": "https://mypy.readthedocs.io/en/stable/"
    },
    {
      "standard": "mypy strict mode",
      "url": "https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict"
    }
  ]
}
---

# Phase 5 of 8: Whole-Backend Mypy Strict Gate

Remove every mypy exclusion so the whole backend, including main.py, older routers, services and tests, is type-checked under strict mode. All findings are fixed without changing behaviour. Test-requiring fixes and real bugs are flagged, not made silently.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Codebase_Quality_And_Config_Cleanup — product feature — extended in this phase

*Scope for this phase: Full type coverage (item 1, mypy half); Ruff was done in Phase 4.*

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

- mypy
- Ruff
- pytest
- uv

**Configurations:** pyproject.toml [tool.mypy] stays strict with no exclude, no per-module ignore_errors overrides and no files list that omits parts of backend/.

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

1. Open pyproject.toml and list every mypy scoping mechanism: exclude patterns, `files`, per-module `ignore_errors` or `follow_imports` overrides. Record them in the review note under a 'mypy exclusions removed' heading.
2. Remove them so `uv run mypy` checks all of backend/ (including backend/app/main.py, backend/tests/ and every older slice) in strict mode. Third-party stub gaps may use a narrow per-module `ignore_missing_imports` override only for that library, and each is listed in the review note.
3. Run `uv run mypy` and record the error count. Fix errors slice by slice: add precise annotations, narrow Optional values, and type the dependency-override helpers in tests. Avoid `Any` and `# type: ignore`. A `# type: ignore[code]` is allowed only with a reason comment, and each is listed in the review note.
4. After each slice run `uv run pytest -x -q` and `uv run ruff check . && uv run ruff format --check .` so Phase 4's gate stays green.
5. Do not change a test to satisfy mypy. If a type fix would require changing a test's logic or assertions, leave the test and record it under 'Flagged: type fix requires test change' in the review note with file and error.
6. Do not change runtime behaviour. Preserve get_settings, run_typed_step, get_db_session and moderate signatures and semantics, the Chained Calls 200 with 'critique_failed' contract and the Router route-id constants.
7. If mypy surfaces a real bug (for example a value that can be None at runtime, or a wrong return type), list it under 'Real bugs surfaced — owner decision' and add only a behaviour-neutral annotation or narrowing.

## Risk Assessment

**Potential bottlenecks:**

Strict mode over untyped legacy code can produce hundreds of errors, and annotation fixes that add runtime `assert` or `cast` calls can alter behaviour. Third-party library typing gaps (litellm, sentence-transformers, pydantic-ai) can cause noisy errors.

**Mitigation strategy:**

Work slice by slice with tests after each batch. Use typing-only changes (annotations, TypedDict, Protocol, narrowing via existing conditionals). Keep every suppression minimal and documented. Flag anything that touches tests.

## Verification

`uv run mypy` exits 0 with no exclusions in pyproject.toml; `uv run ruff check .` and `uv run ruff format --check .` still exit 0; `uv run pytest` passes with the Phase 1 baseline counts. The review note lists every type: ignore, stub override, flagged test-affecting fix and surfaced real bug.

## References

- [mypy](https://mypy.readthedocs.io/en/stable/)
- [mypy strict mode](https://mypy.readthedocs.io/en/stable/command_line.html#cmdoption-mypy-strict)
