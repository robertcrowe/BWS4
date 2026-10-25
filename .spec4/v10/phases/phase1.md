---
{
  "phase_number": 1,
  "total_phases": 8,
  "phase_title": "Integration Thread: Baseline Gates and Required Credential Contract",
  "phase_summary": "Confirm the existing BWS4 codebase builds, tests and runs as-is, then make GROQ_API_KEY and OPENAI_API_KEY genuinely required in every environment. CLAUDE.md, config.py and .env.example are aligned to one contract with no placeholders and no opt-out.",
  "features": [
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "introduced",
      "scope_note": "Baseline verification and the required-credential contract land here; lint/type gates, Render sweep, edit review and acceptance land in Phases 4-8."
    },
    {
      "id": "shared_framework_services",
      "role": "extended",
      "scope_note": "Only the startup credential enforcement is changed in this phase; Router warm-up resilience lands in Phase 2."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "pydantic-settings",
      "pytest",
      "structlog",
      "uv"
    ],
    "configurations": "Required in every environment: DATABASE_URL, CORS_ORIGIN, OPENROUTER_API_KEY, EXA_API_KEY, GROQ_API_KEY, OPENAI_API_KEY. Optional: SENTRY_DSN, SENTRY_ENVIRONMENT, MODERATION_HASH_SALT, PORT, EMBEDDING_MODEL_NAME and the existing limit variables. Frontend build-time only: VITE_API_BASE_URL, VITE_SENTRY_DSN. Real GROQ_API_KEY and OPENAI_API_KEY values must be present in the shell or repo-root .env for every pytest run."
  },
  "instructions": [
    "Record a baseline before changing anything: run `uv run pytest`, `uv run ruff check .`, `uv run mypy` and, in frontend/, `npm run build` and the Vitest suite. Save the pass/fail counts in a new file docs/v10-cleanup-review-note.md under a 'Baseline' heading. This file is extended in later phases.",
    "Confirm the app still boots: `uv run uvicorn backend.app.main:app` (single worker) and GET /api/health returns success. This verifies the Neon DATABASE_URL connection.",
    "In backend/app/core/config.py, change GROQ_API_KEY and OPENAI_API_KEY from optional to required (non-optional) pydantic-settings fields. Preserve the get_settings contract: cached Settings instance, env file resolved from REPO_ROOT, and RuntimeError with an operator-facing message when required config is missing.",
    "Make the startup error name the specific missing credential(s). Do not add a placeholder default or an opt-out flag (such as ALLOW_MISSING_KEYS), and do not skip the check under tests.",
    "Search backend/ for code or test fixtures that set placeholder values for either key, or that rely on them being optional (for example monkeypatching to empty or None, or a conftest default). Remove the placeholders. Where a unit test depended on the key being absent, assert the new fail-fast behaviour instead. If a test cannot be adapted without changing what it asserts, list it in the review note as flagged and do not change it quietly.",
    "Add a new test, backend/tests/core/test_required_credentials.py, with a Spec4 header comment. It constructs Settings with each key removed in turn (via monkeypatch.delenv with the .env file disabled) and asserts startup configuration fails with a message naming that key. It also covers both keys missing.",
    "Update CLAUDE.md, .env.example and the config.py field descriptions to state the same contract: both keys are required in every environment (production, local development and tests), with no placeholders and no opt-out. State that every pytest run needs real credentials and that `-m live` smoke tests remain opt-in and deselected by default.",
    "Confirm the pytest marker configuration still deselects `-m live` by default. Do not change it.",
    "Leave the single uvicorn worker requirement and the rule that streaming endpoints open their own DB session inside the generator untouched."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Making the keys required breaks every test run or local run that lacked real credentials. Existing tests may silently depend on empty or absent keys.",
    "mitigation_strategy": "Run the full suite with real keys before and after, and list any test that needed a change in the review note rather than editing it silently. Document the real-credentials requirement in CLAUDE.md. Keep the check inside Settings validation so it fails at startup with a clear message."
  },
  "verification": "With both keys set: `uv run pytest` passes with the same counts as the baseline and the new test passes. With GROQ_API_KEY unset, `uv run uvicorn backend.app.main:app` exits immediately with an error naming GROQ_API_KEY; repeat with OPENAI_API_KEY unset. `grep -n \"GROQ_API_KEY\\|OPENAI_API_KEY\" CLAUDE.md .env.example backend/app/core/config.py` shows the same 'required' wording in all three. Cites nfr_the_service_refuses_to_start_when_a_required_credential_is_missing.",
  "references": [
    {
      "standard": "pydantic-settings",
      "url": "https://docs.pydantic.dev/latest/concepts/pydantic_settings/"
    },
    {
      "standard": "uv",
      "url": "https://docs.astral.sh/uv/"
    },
    {
      "standard": "Groq API",
      "url": "https://console.groq.com/docs/api-reference"
    },
    {
      "standard": "OpenAI Moderation API",
      "url": "https://platform.openai.com/docs/guides/moderation"
    }
  ]
}
---

# Phase 1 of 8: Integration Thread: Baseline Gates and Required Credential Contract

Confirm the existing BWS4 codebase builds, tests and runs as-is, then make GROQ_API_KEY and OPENAI_API_KEY genuinely required in every environment. CLAUDE.md, config.py and .env.example are aligned to one contract with no placeholders and no opt-out.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Codebase_Quality_And_Config_Cleanup — product feature — introduced in this phase

*Scope for this phase: Baseline verification and the required-credential contract land here; lint/type gates, Render sweep, edit review and acceptance land in Phases 4-8.*

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

### Shared_Framework_Services — product feature — extended in this phase

*Scope for this phase: Only the startup credential enforcement is changed in this phase; Router warm-up resilience lands in Phase 2.*

Provides the common capabilities every example app relies on: text generation through free hosted models, a small local embedding model with a 2D projection, web search, relational and vector data access, moderation, and shared usage caps. Gives all apps one consistent, always-warm foundation.

**Invocation**

- Trigger: The service starts up, and afterwards any example app requests generation, embedding, search, retrieval, moderation or usage accounting.

**Inputs**

- `Generation credential` (secret text, required) — Required in every environment (production, local development, tests). There is no placeholder value and no opt-out.
- `Moderation credential` (secret text, required) — Required in every environment for the moderation service, with the same strictness.
- `Service requests` (structured request, required) — Prompts, texts to embed, search queries and retrieval queries from the example apps.
- `Route descriptions source` (list of items, optional) — Data used at startup to prepare the Router's route descriptions.

**Outputs**

- Primary: Generated text, embedding vectors and 2D coordinates, search results, retrieved passages, moderation verdicts and remaining-usage information.
- Format: Structured responses consumed by the example apps
- Schema notes: The embedding model and 2D projection are prepared once at startup and stay ready for the life of the process. Route-description preparation is best-effort. Hourly and daily usage caps are shared across all apps.

**Success criteria**

- The service refuses to start if either required credential is missing, with a clear message.
- With both credentials present, the service starts and embedding and projection are ready before the first visitor request.
- A failure while preparing route descriptions is logged and the service still starts.
- Shared usage caps are enforced consistently across all apps.

**Failure modes**

- A required credential is missing or invalid in some environment (likelihood: medium) — mitigation: Fail at startup with a message naming the missing credential; never substitute a placeholder.
- The hosted free models are rate-limited or unavailable (likelihood: high) — mitigation: Return a clear, distinguishable 'service busy' outcome and keep prior results visible in the apps.
- Route-description preparation fails at startup (likelihood: medium) — mitigation: Log the failure, start anyway, and let the Router report itself temporarily unavailable until preparation succeeds.
- The data store is unreachable (likelihood: low) — mitigation: Report a clear failure to the affected app and leave unaffected apps working.

- entities: Model Request, Embedding, Usage Cap, Search Result, Document

## Tech Stack

**Dependencies:**

- pydantic-settings
- pytest
- structlog
- uv

**Configurations:** Required in every environment: DATABASE_URL, CORS_ORIGIN, OPENROUTER_API_KEY, EXA_API_KEY, GROQ_API_KEY, OPENAI_API_KEY. Optional: SENTRY_DSN, SENTRY_ENVIRONMENT, MODERATION_HASH_SALT, PORT, EMBEDDING_MODEL_NAME and the existing limit variables. Frontend build-time only: VITE_API_BASE_URL, VITE_SENTRY_DSN. Real GROQ_API_KEY and OPENAI_API_KEY values must be present in the shell or repo-root .env for every pytest run.

**Approved stack for this phase's declared work** (deterministic, from the stack spec):

- OpenAI Moderation API (omni-moderation-latest) (integrations): pre-dispatch safety screening of free-form visitor input only (orchestrated subagents, ReAct loop, Router free text), free of charge so it does not consume model quota; runs before any allowance hold and fails closed; preset input skips it and the collaboration app never calls it — serves `shared_framework_services`
- generation_results (persistence) — serves `shared_framework_services`
- text_representations (persistence) — serves `shared_framework_services`
- stored_records (persistence): the shared storage abstraction's generic key-addressed retention records for apps that keep small pieces of information through the shared retention capability — serves `shared_framework_services`
- usage_limits (persistence): the showcase-wide model/search allowance gate enforced server-side before every provider call by every example app, windowed per UTC hour and per UTC day — serves `shared_framework_services`
- allowance_holds (persistence): reserve/redeem/refund records against the shared usage gate so a run's full call budget is held before its first model call and a run that cannot finish is never started; the Router holds 2 units after moderation and before the router call and releases the second once the evaluator accepts; a comparison re-run holds only the expected route's dispatch cost; a Router run refused because route descriptions are unavailable takes no hold — serves `shared_framework_services`
- service_log_entries (persistence): the shared services' per-call log: which capability was invoked, by which example app, outcome and usage accounting, for every generation, embedding, search and moderation call — serves `shared_framework_services`
- embedding_pipeline (infrastructure): fills the embedding_pipeline substrate for RAG, the embeddings example and the ReAct near-duplicate guard: one shared model, never a second; stays resident for the process's lifetime so no visitor pays the load cost; the package is listed under libraries — serves `shared_framework_services`
- process_supervision (infrastructure): keeps the always-on instance running across crashes and reboots so the boot-time model load and PCA fit stay warm; holds the environment contract (DATABASE_URL, OPENROUTER_API_KEY, GROQ_API_KEY, EXA_API_KEY, OPENAI_API_KEY, CORS_ORIGIN, optional SENTRY_DSN) outside the repository, with GROQ_API_KEY and OPENAI_API_KEY enforced as required at startup; a single worker is mandatory because the loaded model, fitted projection, message bus and duplicate-guard cache are per-process state; the lifespan keeps embedding and Router route-description warm-ups best-effort so one failed optional step never blocks boot — serves `shared_framework_services`
- httpx (libraries): async HTTP client for the shared Exa wrapper (tool use, planning, ReAct, Router search route) and the OpenAI Moderation call — serves `shared_framework_services`
- LiteLLM (libraries): unified interface to Groq and OpenRouter free models with retry and ordered fallback via model_registry.py; used by RAG, the single-call app and the Router's single_call and search_generation routes through the existing generation service — serves `shared_framework_services`
- sentence-transformers (libraries): in-process embedding model (all-MiniLM-L6-v2) shared by RAG (including the Router's retrieval route), the embeddings example and the ReAct duplicate guard; no second embedding model is introduced — serves `shared_framework_services`
- torch (libraries): inference backend beneath sentence-transformers, loaded at boot in the lifespan and kept resident — serves `shared_framework_services`

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

1. Record a baseline before changing anything: run `uv run pytest`, `uv run ruff check .`, `uv run mypy` and, in frontend/, `npm run build` and the Vitest suite. Save the pass/fail counts in a new file docs/v10-cleanup-review-note.md under a 'Baseline' heading. This file is extended in later phases.
2. Confirm the app still boots: `uv run uvicorn backend.app.main:app` (single worker) and GET /api/health returns success. This verifies the Neon DATABASE_URL connection.
3. In backend/app/core/config.py, change GROQ_API_KEY and OPENAI_API_KEY from optional to required (non-optional) pydantic-settings fields. Preserve the get_settings contract: cached Settings instance, env file resolved from REPO_ROOT, and RuntimeError with an operator-facing message when required config is missing.
4. Make the startup error name the specific missing credential(s). Do not add a placeholder default or an opt-out flag (such as ALLOW_MISSING_KEYS), and do not skip the check under tests.
5. Search backend/ for code or test fixtures that set placeholder values for either key, or that rely on them being optional (for example monkeypatching to empty or None, or a conftest default). Remove the placeholders. Where a unit test depended on the key being absent, assert the new fail-fast behaviour instead. If a test cannot be adapted without changing what it asserts, list it in the review note as flagged and do not change it quietly.
6. Add a new test, backend/tests/core/test_required_credentials.py, with a Spec4 header comment. It constructs Settings with each key removed in turn (via monkeypatch.delenv with the .env file disabled) and asserts startup configuration fails with a message naming that key. It also covers both keys missing.
7. Update CLAUDE.md, .env.example and the config.py field descriptions to state the same contract: both keys are required in every environment (production, local development and tests), with no placeholders and no opt-out. State that every pytest run needs real credentials and that `-m live` smoke tests remain opt-in and deselected by default.
8. Confirm the pytest marker configuration still deselects `-m live` by default. Do not change it.
9. Leave the single uvicorn worker requirement and the rule that streaming endpoints open their own DB session inside the generator untouched.

## Risk Assessment

**Potential bottlenecks:**

Making the keys required breaks every test run or local run that lacked real credentials. Existing tests may silently depend on empty or absent keys.

**Mitigation strategy:**

Run the full suite with real keys before and after, and list any test that needed a change in the review note rather than editing it silently. Document the real-credentials requirement in CLAUDE.md. Keep the check inside Settings validation so it fails at startup with a clear message.

## Verification

With both keys set: `uv run pytest` passes with the same counts as the baseline and the new test passes. With GROQ_API_KEY unset, `uv run uvicorn backend.app.main:app` exits immediately with an error naming GROQ_API_KEY; repeat with OPENAI_API_KEY unset. `grep -n "GROQ_API_KEY\|OPENAI_API_KEY" CLAUDE.md .env.example backend/app/core/config.py` shows the same 'required' wording in all three. Cites nfr_the_service_refuses_to_start_when_a_required_credential_is_missing.

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_the_first_visit_loads_without_a_cold_start_delay_because_the_embedding_capability_is_ready_at_startup`: The first visit loads without a cold-start delay because the embedding capability is ready at startup — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_the_service_refuses_to_start_when_a_required_credential_is_missing`: The service refuses to start when a required credential is missing — delivered by process_supervision, pydantic-settings
- `nfr_every_example_app_stays_within_the_shared_hourly_and_daily_usage_limits_so_total_spend_is_bounded`: Every example app stays within the shared hourly and daily usage limits so total spend is bounded — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_run_model_call_counts_are_fixed_and_clearly_stated_in_each_app`: Per-run model-call counts are fixed and clearly stated in each app — delivered by allowance_holds
- `nfr_visitors_are_told_clearly_which_limit__per_app_visit_limit_or_shared_cap__stopped_them`: Visitors are told clearly which limit (per-app visit limit or shared cap) stopped them — delivered by browser_local_storage, usage_limits
- `nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps`: A failure in one example app or optional startup step does not affect the other apps — delivered by process_supervision, router_route_descriptions


## References

- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [uv](https://docs.astral.sh/uv/)
- [Groq API](https://console.groq.com/docs/api-reference)
- [OpenAI Moderation API](https://platform.openai.com/docs/guides/moderation)
