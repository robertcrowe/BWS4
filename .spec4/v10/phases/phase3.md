---
{
  "phase_number": 3,
  "total_phases": 8,
  "phase_title": "Router Unavailable Page State and Retry Button",
  "phase_summary": "Show a clear 'temporarily unavailable' message with a Retry button on the Router page instead of the input when the presets endpoint reports route descriptions unavailable. A successful retry restores the normal page without reloading, and a failed retry keeps the message.",
  "features": [
    {
      "id": "router_example_app",
      "role": "extended",
      "scope_note": "Frontend unavailable state and Retry action only; backend support landed in Phase 2."
    },
    {
      "id": "codebase_quality_and_config_cleanup",
      "role": "extended",
      "scope_note": "Startup resilience item (7) frontend half."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "React",
      "TanStack Query",
      "Tailwind CSS",
      "Vitest",
      "React Testing Library",
      "@testing-library/user-event",
      "oxlint",
      "typescript"
    ],
    "configurations": "No new variables. The client calls same-origin /api/router/*."
  },
  "instructions": [
    "In frontend/src/api/router.ts, extend the RouterPresetsResponse type with the availability field added in Phase 2. Add a retry function and a useRouterRetry mutation hook for POST /api/router/retry. On success it invalidates the presets query. Keep retries disabled on quota-sensitive calls, as with the existing hooks. Do not change the RouteId spellings.",
    "In frontend/src/apps/router/, when the presets response reports availability false, render instead of the input and run controls a 'temporarily unavailable' message and a Retry button. Keep the overview and layout shell visible. Use the existing example-app layout and Tailwind conventions. No design mock exists, so follow the look of existing error notices in the other apps.",
    "Clicking Retry calls the retry mutation and disables the button while pending. On success the page re-renders the normal input and knowledge panel without a browser reload. On failure the same message stays up, with no additional error banner that would change the message.",
    "While unavailable, do not start any run, do not decrement the runs-remaining counter and do not touch the localStorage allowance entry. Prior results retained in localStorage stay visible if present.",
    "Handle the run endpoint's ordinary error response (unavailable) defensively. The run is not spent, because a run is spent only on the run_end event.",
    "Add Vitest tests in frontend/tests/ (a router-unavailable test file) covering: unavailable presets show the message and Retry and no input; a successful retry (mocked) restores the input; a failed retry keeps the message; the runs-remaining counter is unchanged throughout. Mock the API per the existing router test conventions.",
    "Run the oxlint command and `npx tsc --noEmit` in frontend/, and fix findings in the touched files. Source files keep the header comment 'Built with Spec4 AI - https://spec4.ai' and JSDoc on exported functions."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Cached TanStack Query state could keep showing the unavailable page after a successful retry, or a retry could trigger query retries that spam the endpoint.",
    "mitigation_strategy": "Invalidate the presets query on retry success and keep retries disabled. Test the transition from unavailable to ready explicitly."
  },
  "verification": "In frontend/: the Vitest suite passes (`npx vitest run`), including the new tests, `npx tsc --noEmit` is clean, oxlint is clean and `npm run build` succeeds. Manual check: start the backend with the warm-up forced to fail, open the Router route to see the message and Retry, then remove the fault and click Retry to see the page restore with no reload. The other nine apps load normally. Cites nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps and nfr_consistent_layout_and_navigation_across_all_example_apps.",
  "references": [
    {
      "standard": "TanStack Query",
      "url": "https://tanstack.com/query/latest"
    },
    {
      "standard": "React Testing Library",
      "url": "https://testing-library.com/docs/react-testing-library/intro/"
    },
    {
      "standard": "Vitest",
      "url": "https://vitest.dev/"
    }
  ]
}
---

# Phase 3 of 8: Router Unavailable Page State and Retry Button

Show a clear 'temporarily unavailable' message with a Retry button on the Router page instead of the input when the presets endpoint reports route descriptions unavailable. A successful retry restores the normal page without reloading, and a failed retry keeps the message.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Router_Example_App — product feature — extended in this phase

*Scope for this phase: Frontend unavailable state and Retry action only; backend support landed in Phase 2.*

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

*Scope for this phase: Startup resilience item (7) frontend half.*

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

- React
- TanStack Query
- Tailwind CSS
- Vitest
- React Testing Library
- @testing-library/user-event
- oxlint
- typescript

**Configurations:** No new variables. The client calls same-origin /api/router/*.

**Approved stack for this phase's declared work** (deterministic, from the stack spec):

- Groq (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`
- OpenRouter free models (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`
- Exa Search API (integrations): ranked real web search results (title, snippet, source) through the single shared wrapper services/web_search.py, called directly in-process (no MCP) by the tool-use integration, the planning agent's research steps, the ReAct loop's act step, and the Router's search_generation route — serves `router_example_app`
- OpenAI Moderation API (omni-moderation-latest) (integrations): pre-dispatch safety screening of free-form visitor input only (orchestrated subagents, ReAct loop, Router free text), free of charge so it does not consume model quota; runs before any allowance hold and fails closed; preset input skips it and the collaboration app never calls it — serves `router_example_app`
- dataset_embeddings (persistence) — serves `router_example_app`
- search_queries (persistence) — serves `router_example_app`
- usage_limits (persistence): the showcase-wide model/search allowance gate enforced server-side before every provider call by every example app, windowed per UTC hour and per UTC day — serves `router_example_app`
- allowance_holds (persistence): reserve/redeem/refund records against the shared usage gate so a run's full call budget is held before its first model call and a run that cannot finish is never started; the Router holds 2 units after moderation and before the router call and releases the second once the evaluator accepts; a comparison re-run holds only the expected route's dispatch cost; a Router run refused because route descriptions are unavailable takes no hold — serves `router_example_app`
- moderation_log (persistence): safety-gate telemetry for free-form input: a salted hash of the question (never raw text), category, confidence, latency and whether the call failed closed — serves `router_example_app`
- router_agreement_records (persistence): Append-only, shared-across-visitors record of one row per qualifying preset run, from which per-preset agreed/disagreed/declined counts, rates and the overall rate are computed in SQL; free-text runs, comparison re-runs and malformed-decision fallbacks write no row; a low-confidence tie-break landing on the expected route is recorded 'declined' and earns no credit; cells show counts only until 5 observations — serves `router_example_app`
- router_latency_observations (persistence): Append-only, shared-across-visitors record of one row per real search_generation-route run (comparison re-runs excluded), from which the rolling median behind the cost strip's 'typical' baseline is computed in SQL over the most recent N rows; sample size is the row count; below 5 observations the baseline is shown as counts only — serves `router_example_app`
- service_log_entries (persistence): the shared services' per-call log: which capability was invoked, by which example app, outcome and usage accounting, for every generation, embedding, search and moderation call — serves `router_example_app`
- router_preset_catalog (persistence): The six curated Router requests, each with an expected route and a one-line reason, including the two control/near-miss pairs; stores requests only, never answers; expected_route uses exactly the route ids deterministic_evaluator, single_call, retrieval and search_generation; typed Python literals — serves `router_example_app`
- router_unit_table (persistence): The single source of truth for the deterministic evaluator's accepted language (operators, unit names and factors in length, speed and temperature, input length and nesting caps), read by the validator, the evaluator and the generated route description so they cannot drift — serves `router_example_app`
- router_route_descriptions (persistence): The four one-line route descriptions generated at startup (never hand-written) from the unit table, the retriever's indexed document titles, the search tool's declared schema and the single-call capability's description, each with its cost_rank; shown byte for byte as the router received them; held in Router-module in-process state that is either ready or unavailable: a failed best-effort warm-up leaves it unavailable (the API still boots, the Router page shows 'temporarily unavailable' with Retry) and a successful Retry fills it without a restart — serves `router_example_app`
- router_prompt_templates (persistence): The static, versioned route-classification prompt (request delimited as untrusted data) with its typed decision schema — serves `router_example_app`
- educational_overviews (persistence): per-app short educational overview content, quota rationale and cross-references (Planning Agent and ReAct Loop; Router's contrast with Tool Use, Planning Agent and ReAct Loop and its uncalibrated-scores statement) — serves `router_example_app`
- router_run_allowance (persistence): The Router's advisory five-run counter plus the visitor's retained decision cards, routed answers and cost strips, stamped with the UTC hour; a comparison re-run costs one run and a refused run (including one refused because route descriptions are unavailable) costs none; the client decrements from the end-of-run event — serves `router_example_app`
- retriever (infrastructure): finds the top-N passages for a question's embedding; the Router's retrieval route calls this existing retriever through its existing entry point, unmodified — serves `router_example_app`
- pipeline_runner (infrastructure): fills the pipeline_runner substrate for the chained-calls writer-to-critic sequence (first response passed directly as the second call's input) and for the Router's classify, code-dispatch, optional-generation flow (one typed classification call with output retries zero, then code-owned dispatch); the usage gate checks every call exactly as on the LiteLLM path; no new dependency — serves `router_example_app`
- tool_execution_harness (infrastructure): fills the tool_execution_harness substrate; the run-allowance check is a direct service-layer call, never a model-exposed tool, so the model cannot decide whether quota is spent; the Router reuses the shared wrapper rather than adding a harness — serves `router_example_app`
- httpx (libraries): async HTTP client for the shared Exa wrapper (tool use, planning, ReAct, Router search route) and the OpenAI Moderation call — serves `router_example_app`
- LiteLLM (libraries): unified interface to Groq and OpenRouter free models with retry and ordered fallback via model_registry.py; used by RAG, the single-call app and the Router's single_call and search_generation routes through the existing generation service — serves `router_example_app`
- PydanticAI (libraries): agent framework (second model lane) returning validated Pydantic models via FallbackModel over the shared chain: chained calls, planning agent, orchestrated subagents, collaboration agents, ReAct per-cycle calls and annotation, and the Router's single typed classification call (output retries zero) — serves `router_example_app`
- sse-starlette (libraries): server-sent events responses with keep-alive and client-disconnect detection so an abandoned run stops spending quota; streams the planning, orchestrated, collaboration, ReAct and Router runs — serves `router_example_app`
- sentence-transformers (libraries): in-process embedding model (all-MiniLM-L6-v2) shared by RAG (including the Router's retrieval route), the embeddings example and the ReAct duplicate guard; no second embedding model is introduced — serves `router_example_app`
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

1. In frontend/src/api/router.ts, extend the RouterPresetsResponse type with the availability field added in Phase 2. Add a retry function and a useRouterRetry mutation hook for POST /api/router/retry. On success it invalidates the presets query. Keep retries disabled on quota-sensitive calls, as with the existing hooks. Do not change the RouteId spellings.
2. In frontend/src/apps/router/, when the presets response reports availability false, render instead of the input and run controls a 'temporarily unavailable' message and a Retry button. Keep the overview and layout shell visible. Use the existing example-app layout and Tailwind conventions. No design mock exists, so follow the look of existing error notices in the other apps.
3. Clicking Retry calls the retry mutation and disables the button while pending. On success the page re-renders the normal input and knowledge panel without a browser reload. On failure the same message stays up, with no additional error banner that would change the message.
4. While unavailable, do not start any run, do not decrement the runs-remaining counter and do not touch the localStorage allowance entry. Prior results retained in localStorage stay visible if present.
5. Handle the run endpoint's ordinary error response (unavailable) defensively. The run is not spent, because a run is spent only on the run_end event.
6. Add Vitest tests in frontend/tests/ (a router-unavailable test file) covering: unavailable presets show the message and Retry and no input; a successful retry (mocked) restores the input; a failed retry keeps the message; the runs-remaining counter is unchanged throughout. Mock the API per the existing router test conventions.
7. Run the oxlint command and `npx tsc --noEmit` in frontend/, and fix findings in the touched files. Source files keep the header comment 'Built with Spec4 AI - https://spec4.ai' and JSDoc on exported functions.

## Risk Assessment

**Potential bottlenecks:**

Cached TanStack Query state could keep showing the unavailable page after a successful retry, or a retry could trigger query retries that spam the endpoint.

**Mitigation strategy:**

Invalidate the presets query on retry success and keep retries disabled. Test the transition from unavailable to ready explicitly.

## Verification

In frontend/: the Vitest suite passes (`npx vitest run`), including the new tests, `npx tsc --noEmit` is clean, oxlint is clean and `npm run build` succeeds. Manual check: start the backend with the warm-up forced to fail, open the Router route to see the message and Retry, then remove the fault and click Retry to see the page restore with no reload. The other nine apps load normally. Cites nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps and nfr_consistent_layout_and_navigation_across_all_example_apps.

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_the_first_visit_loads_without_a_cold_start_delay_because_the_embedding_capability_is_ready_at_startup`: The first visit loads without a cold-start delay because the embedding capability is ready at startup — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_every_example_app_stays_within_the_shared_hourly_and_daily_usage_limits_so_total_spend_is_bounded`: Every example app stays within the shared hourly and daily usage limits so total spend is bounded — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_run_model_call_counts_are_fixed_and_clearly_stated_in_each_app`: Per-run model-call counts are fixed and clearly stated in each app — delivered by allowance_holds
- `nfr_visitors_are_told_clearly_which_limit__per_app_visit_limit_or_shared_cap__stopped_them`: Visitors are told clearly which limit (per-app visit limit or shared cap) stopped them — delivered by browser_local_storage, usage_limits
- `nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps`: A failure in one example app or optional startup step does not affect the other apps — delivered by process_supervision, router_route_descriptions
- `nfr_routing_and_agreement_history_persists_across_service_interruptions`: Routing and agreement history persists across service interruptions — delivered by SQLAlchemy, primary_store, router_agreement_records, router_latency_observations


## References

- [TanStack Query](https://tanstack.com/query/latest)
- [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/)
- [Vitest](https://vitest.dev/)
