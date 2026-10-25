---
{
  "phase_number": 7,
  "total_phases": 8,
  "phase_title": "Unrecorded Edits Review Note",
  "phase_summary": "Inspect each edit made outside any plan (SEO and site metadata, the shared generation service, README, Claude Code settings, pyproject.toml and the ReAct frontend test), and document each in the review note as kept or flagged for the owner. Nothing is reverted silently.",
  "features": [
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "extended",
      "scope_note": "Unrecorded edits review (item 5)."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "git",
      "pytest",
      "Vitest"
    ],
    "configurations": "No environment changes. Read-only inspection except for documenting."
  },
  "instructions": [
    "For each item, use `git log -p --follow` and `git diff` against the last tagged or planned commit to see exactly what changed: frontend/index.html, frontend/public/sitemap.xml, frontend/src/seo/siteMeta.ts, backend/app/services/generation.py, README.md, .claude/settings.json, pyproject.toml and frontend/tests/react-loop.test.tsx. If history is unavailable, describe the present state and say so.",
    "In docs/v10-cleanup-review-note.md add an 'Unrecorded edits' section with one subsection per item containing: what changed (a short factual summary), apparent intent, evidence for that intent (commit message, related feature, consistency with the stack spec), and a verdict of 'kept' or 'flagged for owner decision' with the reason.",
    "SEO and site metadata: check that canonical URLs, sitemap entries and per-route metadata match the single VPS origin and the current ten-app roster with labels that match navigation exactly ('ReAct Loop', 'Router'). Flag any stale hostname or missing or extra route.",
    "generation.py: check that the change is compatible with the single-call, RAG, Router single_call and search_generation routes calling it through unchanged entry points, and that all model calls still pass the usage gate. Flag any behavioural change that bypasses the allowance gate, changes caps or alters visitor-facing messages. Run the relevant tests (`uv run pytest backend/tests/services backend/tests/single_call backend/tests/router -q`) and record the result.",
    "README, .claude/settings.json and pyproject.toml: check that README matches the real commands (uv run pytest, ruff, mypy, deploy) and the Phase 1 env contract. Check that .claude/settings.json contains no secrets or over-broad permissions (flag anything that does). Check that pyproject.toml changes are consistent with the Phase 4 and 5 gate changes and add no dependency outside the approved stack. Flag any unapproved dependency.",
    "ReAct frontend test: run `npx vitest run tests/react-loop.test.tsx` from frontend/ and confirm it passes. Check that its assertions match the spec (2-run session limit wording, cycle counter, budget-exhausted card, the distinction between the 2-run limit and the shared cap) and were not weakened. Flag any weakened or skipped assertion.",
    "Do not revert or rewrite any inspected change in this phase. The only edits are the review note itself, plus trivial documentation fixes explicitly listed in the note as 'documentation only'. Anything doubtful goes under 'Flagged for owner decision' at the top of the note, together with the flags carried over from Phases 4-6."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "The diffs for some edits were not shown in the code review, and git history may be squashed or missing, so intent can be guesswork. A real defect may be kept by accident.",
    "mitigation_strategy": "State uncertainty explicitly, base verdicts on evidence (tests, spec consistency), default to 'flagged' when the intent is unclear, and never revert silently."
  },
  "verification": "docs/v10-cleanup-review-note.md contains a subsection for each of the six edit groups (SEO/site metadata, generation.py, README, .claude/settings.json, pyproject.toml, react-loop.test.tsx), each with a kept or flagged verdict, plus a consolidated 'Flagged for owner decision' list. `git diff --stat` shows no source changes other than the note and listed documentation-only fixes. `uv run pytest` and the frontend Vitest suite pass.",
  "references": []
}
---

# Phase 7 of 8: Unrecorded Edits Review Note

Inspect each edit made outside any plan (SEO and site metadata, the shared generation service, README, Claude Code settings, pyproject.toml and the ReAct frontend test), and document each in the review note as kept or flagged for the owner. Nothing is reverted silently.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Codebase_Quality_And_Config_Cleanup — product feature — extended in this phase

*Scope for this phase: Unrecorded edits review (item 5).*

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

- git
- pytest
- Vitest

**Configurations:** No environment changes. Read-only inspection except for documenting.

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

1. For each item, use `git log -p --follow` and `git diff` against the last tagged or planned commit to see exactly what changed: frontend/index.html, frontend/public/sitemap.xml, frontend/src/seo/siteMeta.ts, backend/app/services/generation.py, README.md, .claude/settings.json, pyproject.toml and frontend/tests/react-loop.test.tsx. If history is unavailable, describe the present state and say so.
2. In docs/v10-cleanup-review-note.md add an 'Unrecorded edits' section with one subsection per item containing: what changed (a short factual summary), apparent intent, evidence for that intent (commit message, related feature, consistency with the stack spec), and a verdict of 'kept' or 'flagged for owner decision' with the reason.
3. SEO and site metadata: check that canonical URLs, sitemap entries and per-route metadata match the single VPS origin and the current ten-app roster with labels that match navigation exactly ('ReAct Loop', 'Router'). Flag any stale hostname or missing or extra route.
4. generation.py: check that the change is compatible with the single-call, RAG, Router single_call and search_generation routes calling it through unchanged entry points, and that all model calls still pass the usage gate. Flag any behavioural change that bypasses the allowance gate, changes caps or alters visitor-facing messages. Run the relevant tests (`uv run pytest backend/tests/services backend/tests/single_call backend/tests/router -q`) and record the result.
5. README, .claude/settings.json and pyproject.toml: check that README matches the real commands (uv run pytest, ruff, mypy, deploy) and the Phase 1 env contract. Check that .claude/settings.json contains no secrets or over-broad permissions (flag anything that does). Check that pyproject.toml changes are consistent with the Phase 4 and 5 gate changes and add no dependency outside the approved stack. Flag any unapproved dependency.
6. ReAct frontend test: run `npx vitest run tests/react-loop.test.tsx` from frontend/ and confirm it passes. Check that its assertions match the spec (2-run session limit wording, cycle counter, budget-exhausted card, the distinction between the 2-run limit and the shared cap) and were not weakened. Flag any weakened or skipped assertion.
7. Do not revert or rewrite any inspected change in this phase. The only edits are the review note itself, plus trivial documentation fixes explicitly listed in the note as 'documentation only'. Anything doubtful goes under 'Flagged for owner decision' at the top of the note, together with the flags carried over from Phases 4-6.

## Risk Assessment

**Potential bottlenecks:**

The diffs for some edits were not shown in the code review, and git history may be squashed or missing, so intent can be guesswork. A real defect may be kept by accident.

**Mitigation strategy:**

State uncertainty explicitly, base verdicts on evidence (tests, spec consistency), default to 'flagged' when the intent is unclear, and never revert silently.

## Verification

docs/v10-cleanup-review-note.md contains a subsection for each of the six edit groups (SEO/site metadata, generation.py, README, .claude/settings.json, pyproject.toml, react-loop.test.tsx), each with a kept or flagged verdict, plus a consolidated 'Flagged for owner decision' list. `git diff --stat` shows no source changes other than the note and listed documentation-only fixes. `uv run pytest` and the frontend Vitest suite pass.
