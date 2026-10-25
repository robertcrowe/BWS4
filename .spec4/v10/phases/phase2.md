---
{
  "phase_number": 2,
  "total_phases": 8,
  "phase_title": "Best-Effort Router Warm-Up and Backend Unavailable State",
  "phase_summary": "Make warm_route_descriptions() best-effort in the FastAPI lifespan, so a failure is logged and the API still starts. Add a ready/unavailable state in the Router module, an availability flag on GET presets, and a retry endpoint. While unavailable, runs are refused with no hold and no usage spent.",
  "features": [
    {
      "id": "shared_framework_services",
      "role": "extended",
      "scope_note": "Best-effort startup handling of Router route-description preparation; credential enforcement was done in Phase 1."
    },
    {
      "id": "router_example_app",
      "role": "introduced",
      "scope_note": "Backend unavailable state, availability flag and retry only; the frontend unavailable page lands in Phase 3."
    },
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "extended",
      "scope_note": "Startup resilience item (7) backend half."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "FastAPI",
      "structlog",
      "pytest",
      "sse-starlette"
    ],
    "configurations": "No new environment variables. Uvicorn stays at --workers 1 because route-description state is per-process."
  },
  "instructions": [
    "Read backend/app/main.py lifespan and backend/app/router/ (the module holding route descriptions and warm_route_descriptions()). Document in code comments that the lifespan currently awaits warm_route_descriptions() outside the try/except that protects the embeddings warm-up.",
    "Wrap warm_route_descriptions() in the same best-effort handling as the embeddings warm-up. On any exception, log a structlog event naming the failure (for example router_warmup_failed) with the exception info, and continue booting. Required-credential failures from Phase 1 must stay fatal and must not be caught here.",
    "In the Router module, give the route-description holder an explicit ready/unavailable state: unavailable at import, ready only after a successful warm-up. A failed warm-up leaves it unavailable and never leaves partial descriptions. Expose a small function to read the state.",
    "Make warm_route_descriptions() safely re-callable. A successful call fills the state, and a failing call leaves state unchanged and raises or returns a failure result that the retry handler can report. Do not add a background retry timer.",
    "Extend GET /api/router/presets in backend/app/api/router.py with an availability boolean, false while descriptions are not ready. Keep the existing response fields and shapes (route descriptions, margin, cost order, presets) unchanged for the ready case. Return an empty or null route-description field in the unavailable case, and update the typed response model accordingly.",
    "Add POST /api/router/retry. It re-attempts the warm-up and returns the availability result, 200 on success. On failure it returns an ordinary error or an availability=false payload, so the page keeps showing the same message. It must not reserve usage or touch the allowance tables.",
    "In POST /api/router/run and POST /api/router/rerun, check availability first, before moderation and before any allowance hold. When unavailable, return an ordinary error response (not an SSE stream) with a clear 'temporarily unavailable' detail. Take no hold, spend no units and write no history row. Keep the documented run order for the ready case: availability check, moderation (free text only), 2-unit hold, SSE.",
    "Do not touch the 'streaming endpoints open their own DB session inside the generator' rule. The availability check must not use a DB session.",
    "Add tests under backend/tests/router/: (a) the API boots when warm_route_descriptions is patched to raise; (b) GET presets reports availability false in that case and true after a successful retry with no restart; (c) POST run while unavailable returns an error response and creates no allowance hold row; (d) a failed retry keeps availability false; (e) an embeddings or other app endpoint still works while the Router is unavailable. Use dependency overrides or monkeypatching, never placeholder credentials.",
    "Each new file opens with the header comment 'Built with Spec4 AI - https://spec4.ai'. New public functions get Google-style docstrings."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Catching too broadly could swallow the fatal credential error, or leave Router state half-populated. The refusal ordering (availability before moderation and hold) is easy to get wrong.",
    "mitigation_strategy": "Catch only around the warm-up call, never around Settings loading. Assign descriptions to module state atomically only after generation fully succeeds. Test that no allowance_holds row exists after a refused run."
  },
  "verification": "`uv run pytest backend/tests/router -q` passes including the new warm-up tests. With warm_route_descriptions forced to fail, `uv run uvicorn backend.app.main:app` starts; GET /api/embeddings/presets returns 200; GET /api/router/presets shows availability false; POST /api/router/run returns an ordinary error and no hold is recorded. After the fault is removed, POST /api/router/retry makes presets report availability true with no restart. Cites nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps.",
  "references": [
    {
      "standard": "FastAPI lifespan events",
      "url": "https://fastapi.tiangolo.com/advanced/events/"
    },
    {
      "standard": "structlog",
      "url": "https://www.structlog.org/"
    }
  ]
}
---

# Phase 2 of 8: Best-Effort Router Warm-Up and Backend Unavailable State

Make warm_route_descriptions() best-effort in the FastAPI lifespan, so a failure is logged and the API still starts. Add a ready/unavailable state in the Router module, an availability flag on GET presets, and a retry endpoint. While unavailable, runs are refused with no hold and no usage spent.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Shared_Framework_Services — product feature — extended in this phase

*Scope for this phase: Best-effort startup handling of Router route-description preparation; credential enforcement was done in Phase 1.*

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

### Router_Example_App — product feature — introduced in this phase

*Scope for this phase: Backend unavailable state, availability flag and retry only; the frontend unavailable page lands in Phase 3.*

Illustrates routing: one cheap classification call chooses among four existing paths (deterministic evaluator, single call, RAG retrieval, search plus generation), after which code dispatches and the router steps aside. The app shows the decision, the answer, the cost against a no-router baseline, and measured agreement history.

**Invocation**

- Trigger: The visitor picks one of six curated requests or types their own and runs it; after a mismatched preset run, the visitor may request one comparison re-run through the expected route.

**Inputs**

- `Request` (text, required) — A preset (each with an expected route and one-line reason, no stored answer) or free text.
- `Route descriptions` (list of items, required) — One line per route, shown exactly as the router received them. The deterministic line is generated from the same table the evaluator checks; the RAG line carries the subject list derived at startup from the indexed documents.
- `Outcome and latency history` (list of items, optional) — Recorded per-preset agreed, disagreed and declined counts and search-route timings from all visitors, which persist across service interruptions.

**Outputs**

- Primary: A decision card (chosen route, one-line rationale, all four scores, and agreement status for presets), the dispatched path's answer labelled with its path, a cost strip against the no-router baseline, and per-preset agreement history.
- Format: Decision card, answer panel in the matching app's layout, cost comparison, history table
- Schema notes: Router returns four scores plus a structured expression if the deterministic route scores highest. Scores are the model's uncalibrated self-report, and the measured agreement rate is the one calibrated number. A fixed margin in code triggers a low-confidence path that dispatches to the cheaper of the top two routes in the fixed cost order (deterministic, single call, RAG, search plus generation). Preset runs state 'agreed', 'misrouted' or 'declined'. The cost strip separates router overhead and always labels baseline time 'typical', showing counts only until at least five observations exist.

**Success criteria**

- Every run ends as either a routed answer with its decision card and cost strip, or a low-confidence card naming the two routes it was torn between.
- Deterministic calculations never run model-produced text; an expression the evaluator cannot compute is dispatched to single call and the card says so plainly as the router's own misroute.
- If a low-confidence tie lands on deterministic and the evaluator rejects it, the other candidate route is used and the card says the evaluator could not compute it.
- Each run costs at most 2 model-call units (1 on the deterministic route); 2 are reserved before the router runs and the second is released once the evaluator accepts.
- A comparison re-run is offered only when the dispatched route differs from the expected route for a preset, does not run the router again, shows router overhead as zero, counts as one of the 5 visit runs, and feeds no history.
- Free-text runs and re-runs feed no agreement cell, and a tie-break landing on the expected route earns no credit.
- History cells show counts only until they have at least five observations.
- A runs-remaining indicator is shown, and when exhausted the input and run controls are disabled with a message distinguishing the 5-run limit from the shared cap.
- If route descriptions are not ready, the page shows 'temporarily unavailable' with a retry action, no run starts and no usage is reserved; a successful retry restores normal operation without restarting the service, while a failed retry keeps the message. Other apps are unaffected.

**Failure modes**

- Router picks the wrong route (likelihood: medium) — mitigation: Show it candidly as 'misrouted', record it in the agreement history, and offer the comparison re-run for presets.
- Router returns an unusable or missing decision (likelihood: medium) — mitigation: Treat it as 'declined' for presets and apply the low-confidence path.
- Expression is rejected by the evaluator (likelihood: medium) — mitigation: Dispatch to the fallback route with the held units and state the correction on the card.
- Too little latency history for the baseline (likelihood: high) — mitigation: Show counts only with a note until enough search-route runs exist, never a made-up figure.
- Shared cap too close to complete a run (likelihood: medium) — mitigation: Refuse before starting so no run begins and nothing is spent.

- depends on: shared_framework_services, tool_use_integration, rag_example_app, single_call_example_app (build these no later than `router_example_app`)
- entities: Request, Route, Routing Decision, Preset, Agreement Record, Latency Observation, Cost Strip, Run Allowance

### Codebase_Quality_And_Config_Cleanup — product feature — extended in this phase

*Scope for this phase: Startup resilience item (7) backend half.*

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

- FastAPI
- structlog
- pytest
- sse-starlette

**Configurations:** No new environment variables. Uvicorn stays at --workers 1 because route-description state is per-process.

**Approved stack for this phase's declared work** (deterministic, from the stack spec):

- Groq (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`
- OpenRouter free models (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`
- Exa Search API (integrations): ranked real web search results (title, snippet, source) through the single shared wrapper services/web_search.py, called directly in-process (no MCP) by the tool-use integration, the planning agent's research steps, the ReAct loop's act step, and the Router's search_generation route — serves `router_example_app`
- OpenAI Moderation API (omni-moderation-latest) (integrations): pre-dispatch safety screening of free-form visitor input only (orchestrated subagents, ReAct loop, Router free text), free of charge so it does not consume model quota; runs before any allowance hold and fails closed; preset input skips it and the collaboration app never calls it — serves `router_example_app`, `shared_framework_services`
- dataset_embeddings (persistence) — serves `router_example_app`
- generation_results (persistence) — serves `shared_framework_services`
- text_representations (persistence) — serves `shared_framework_services`
- search_queries (persistence) — serves `router_example_app`
- stored_records (persistence): the shared storage abstraction's generic key-addressed retention records for apps that keep small pieces of information through the shared retention capability — serves `shared_framework_services`
- usage_limits (persistence): the showcase-wide model/search allowance gate enforced server-side before every provider call by every example app, windowed per UTC hour and per UTC day — serves `router_example_app`, `shared_framework_services`
- allowance_holds (persistence): reserve/redeem/refund records against the shared usage gate so a run's full call budget is held before its first model call and a run that cannot finish is never started; the Router holds 2 units after moderation and before the router call and releases the second once the evaluator accepts; a comparison re-run holds only the expected route's dispatch cost; a Router run refused because route descriptions are unavailable takes no hold — serves `router_example_app`, `shared_framework_services`
- moderation_log (persistence): safety-gate telemetry for free-form input: a salted hash of the question (never raw text), category, confidence, latency and whether the call failed closed — serves `router_example_app`
- router_agreement_records (persistence): Append-only, shared-across-visitors record of one row per qualifying preset run, from which per-preset agreed/disagreed/declined counts, rates and the overall rate are computed in SQL; free-text runs, comparison re-runs and malformed-decision fallbacks write no row; a low-confidence tie-break landing on the expected route is recorded 'declined' and earns no credit; cells show counts only until 5 observations — serves `router_example_app`
- router_latency_observations (persistence): Append-only, shared-across-visitors record of one row per real search_generation-route run (comparison re-runs excluded), from which the rolling median behind the cost strip's 'typical' baseline is computed in SQL over the most recent N rows; sample size is the row count; below 5 observations the baseline is shown as counts only — serves `router_example_app`
- service_log_entries (persistence): the shared services' per-call log: which capability was invoked, by which example app, outcome and usage accounting, for every generation, embedding, search and moderation call — serves `router_example_app`, `shared_framework_services`
- router_preset_catalog (persistence): The six curated Router requests, each with an expected route and a one-line reason, including the two control/near-miss pairs; stores requests only, never answers; expected_route uses exactly the route ids deterministic_evaluator, single_call, retrieval and search_generation; typed Python literals — serves `router_example_app`
- router_unit_table (persistence): The single source of truth for the deterministic evaluator's accepted language (operators, unit names and factors in length, speed and temperature, input length and nesting caps), read by the validator, the evaluator and the generated route description so they cannot drift — serves `router_example_app`
- router_route_descriptions (persistence): The four one-line route descriptions generated at startup (never hand-written) from the unit table, the retriever's indexed document titles, the search tool's declared schema and the single-call capability's description, each with its cost_rank; shown byte for byte as the router received them; held in Router-module in-process state that is either ready or unavailable: a failed best-effort warm-up leaves it unavailable (the API still boots, the Router page shows 'temporarily unavailable' with Retry) and a successful Retry fills it without a restart — serves `router_example_app`
- router_prompt_templates (persistence): The static, versioned route-classification prompt (request delimited as untrusted data) with its typed decision schema — serves `router_example_app`
- educational_overviews (persistence): per-app short educational overview content, quota rationale and cross-references (Planning Agent and ReAct Loop; Router's contrast with Tool Use, Planning Agent and ReAct Loop and its uncalibrated-scores statement) — serves `router_example_app`
- router_run_allowance (persistence): The Router's advisory five-run counter plus the visitor's retained decision cards, routed answers and cost strips, stamped with the UTC hour; a comparison re-run costs one run and a refused run (including one refused because route descriptions are unavailable) costs none; the client decrements from the end-of-run event — serves `router_example_app`
- embedding_pipeline (infrastructure): fills the embedding_pipeline substrate for RAG, the embeddings example and the ReAct near-duplicate guard: one shared model, never a second; stays resident for the process's lifetime so no visitor pays the load cost; the package is listed under libraries — serves `shared_framework_services`
- retriever (infrastructure): finds the top-N passages for a question's embedding; the Router's retrieval route calls this existing retriever through its existing entry point, unmodified — serves `router_example_app`
- pipeline_runner (infrastructure): fills the pipeline_runner substrate for the chained-calls writer-to-critic sequence (first response passed directly as the second call's input) and for the Router's classify, code-dispatch, optional-generation flow (one typed classification call with output retries zero, then code-owned dispatch); the usage gate checks every call exactly as on the LiteLLM path; no new dependency — serves `router_example_app`
- tool_execution_harness (infrastructure): fills the tool_execution_harness substrate; the run-allowance check is a direct service-layer call, never a model-exposed tool, so the model cannot decide whether quota is spent; the Router reuses the shared wrapper rather than adding a harness — serves `router_example_app`
- process_supervision (infrastructure): keeps the always-on instance running across crashes and reboots so the boot-time model load and PCA fit stay warm; holds the environment contract (DATABASE_URL, OPENROUTER_API_KEY, GROQ_API_KEY, EXA_API_KEY, OPENAI_API_KEY, CORS_ORIGIN, optional SENTRY_DSN) outside the repository, with GROQ_API_KEY and OPENAI_API_KEY enforced as required at startup; a single worker is mandatory because the loaded model, fitted projection, message bus and duplicate-guard cache are per-process state; the lifespan keeps embedding and Router route-description warm-ups best-effort so one failed optional step never blocks boot — serves `shared_framework_services`
- httpx (libraries): async HTTP client for the shared Exa wrapper (tool use, planning, ReAct, Router search route) and the OpenAI Moderation call — serves `router_example_app`, `shared_framework_services`
- LiteLLM (libraries): unified interface to Groq and OpenRouter free models with retry and ordered fallback via model_registry.py; used by RAG, the single-call app and the Router's single_call and search_generation routes through the existing generation service — serves `router_example_app`, `shared_framework_services`
- PydanticAI (libraries): agent framework (second model lane) returning validated Pydantic models via FallbackModel over the shared chain: chained calls, planning agent, orchestrated subagents, collaboration agents, ReAct per-cycle calls and annotation, and the Router's single typed classification call (output retries zero) — serves `router_example_app`
- sse-starlette (libraries): server-sent events responses with keep-alive and client-disconnect detection so an abandoned run stops spending quota; streams the planning, orchestrated, collaboration, ReAct and Router runs — serves `router_example_app`
- sentence-transformers (libraries): in-process embedding model (all-MiniLM-L6-v2) shared by RAG (including the Router's retrieval route), the embeddings example and the ReAct duplicate guard; no second embedding model is introduced — serves `router_example_app`, `shared_framework_services`
- torch (libraries): inference backend beneath sentence-transformers, loaded at boot in the lifespan and kept resident — serves `shared_framework_services`
- pgvector (libraries): Python/SQLAlchemy client for the pgvector extension: vector columns and similarity queries, including the RAG retriever the Router reuses — serves `router_example_app`
- @microsoft/fetch-event-source (libraries): fetch-based SSE client supporting POST bodies and abort (native EventSource is GET-only); abort stops an abandoned run from spending quota — serves `router_example_app`
- react-markdown (libraries): renders model-produced markdown as React elements (no dangerouslySetInnerHTML) on this unauthenticated public surface: specialist and merged answers, award rationales, ReAct thoughts and observations, Router rationale and routed answers — serves `router_example_app`

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

1. Read backend/app/main.py lifespan and backend/app/router/ (the module holding route descriptions and warm_route_descriptions()). Document in code comments that the lifespan currently awaits warm_route_descriptions() outside the try/except that protects the embeddings warm-up.
2. Wrap warm_route_descriptions() in the same best-effort handling as the embeddings warm-up. On any exception, log a structlog event naming the failure (for example router_warmup_failed) with the exception info, and continue booting. Required-credential failures from Phase 1 must stay fatal and must not be caught here.
3. In the Router module, give the route-description holder an explicit ready/unavailable state: unavailable at import, ready only after a successful warm-up. A failed warm-up leaves it unavailable and never leaves partial descriptions. Expose a small function to read the state.
4. Make warm_route_descriptions() safely re-callable. A successful call fills the state, and a failing call leaves state unchanged and raises or returns a failure result that the retry handler can report. Do not add a background retry timer.
5. Extend GET /api/router/presets in backend/app/api/router.py with an availability boolean, false while descriptions are not ready. Keep the existing response fields and shapes (route descriptions, margin, cost order, presets) unchanged for the ready case. Return an empty or null route-description field in the unavailable case, and update the typed response model accordingly.
6. Add POST /api/router/retry. It re-attempts the warm-up and returns the availability result, 200 on success. On failure it returns an ordinary error or an availability=false payload, so the page keeps showing the same message. It must not reserve usage or touch the allowance tables.
7. In POST /api/router/run and POST /api/router/rerun, check availability first, before moderation and before any allowance hold. When unavailable, return an ordinary error response (not an SSE stream) with a clear 'temporarily unavailable' detail. Take no hold, spend no units and write no history row. Keep the documented run order for the ready case: availability check, moderation (free text only), 2-unit hold, SSE.
8. Do not touch the 'streaming endpoints open their own DB session inside the generator' rule. The availability check must not use a DB session.
9. Add tests under backend/tests/router/: (a) the API boots when warm_route_descriptions is patched to raise; (b) GET presets reports availability false in that case and true after a successful retry with no restart; (c) POST run while unavailable returns an error response and creates no allowance hold row; (d) a failed retry keeps availability false; (e) an embeddings or other app endpoint still works while the Router is unavailable. Use dependency overrides or monkeypatching, never placeholder credentials.
10. Each new file opens with the header comment 'Built with Spec4 AI - https://spec4.ai'. New public functions get Google-style docstrings.

## Risk Assessment

**Potential bottlenecks:**

Catching too broadly could swallow the fatal credential error, or leave Router state half-populated. The refusal ordering (availability before moderation and hold) is easy to get wrong.

**Mitigation strategy:**

Catch only around the warm-up call, never around Settings loading. Assign descriptions to module state atomically only after generation fully succeeds. Test that no allowance_holds row exists after a refused run.

## Verification

`uv run pytest backend/tests/router -q` passes including the new warm-up tests. With warm_route_descriptions forced to fail, `uv run uvicorn backend.app.main:app` starts; GET /api/embeddings/presets returns 200; GET /api/router/presets shows availability false; POST /api/router/run returns an ordinary error and no hold is recorded. After the fault is removed, POST /api/router/retry makes presets report availability true with no restart. Cites nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps.

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_the_first_visit_loads_without_a_cold_start_delay_because_the_embedding_capability_is_ready_at_startup`: The first visit loads without a cold-start delay because the embedding capability is ready at startup — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_the_service_refuses_to_start_when_a_required_credential_is_missing`: The service refuses to start when a required credential is missing — delivered by process_supervision, pydantic-settings
- `nfr_every_example_app_stays_within_the_shared_hourly_and_daily_usage_limits_so_total_spend_is_bounded`: Every example app stays within the shared hourly and daily usage limits so total spend is bounded — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_run_model_call_counts_are_fixed_and_clearly_stated_in_each_app`: Per-run model-call counts are fixed and clearly stated in each app — delivered by allowance_holds
- `nfr_visitors_are_told_clearly_which_limit__per_app_visit_limit_or_shared_cap__stopped_them`: Visitors are told clearly which limit (per-app visit limit or shared cap) stopped them — delivered by browser_local_storage, usage_limits
- `nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps`: A failure in one example app or optional startup step does not affect the other apps — delivered by process_supervision, router_route_descriptions
- `nfr_routing_and_agreement_history_persists_across_service_interruptions`: Routing and agreement history persists across service interruptions — delivered by SQLAlchemy, primary_store, router_agreement_records, router_latency_observations


## References

- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/)
- [structlog](https://www.structlog.org/)
