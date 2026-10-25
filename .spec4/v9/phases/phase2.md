---
{
  "phase_number": 2,
  "total_phases": 10,
  "phase_title": "Deterministic Evaluator and Unit Table",
  "phase_summary": "Build the no-model route: a single-source unit table and a closed-grammar tokenizer feeding a hand-written recursive-descent evaluator for arithmetic, percentages and length, speed and temperature conversions. Model-produced text is never executed, so this must be correct and rigorously tested before anything depends on it.",
  "features": [
    {
      "id": "router_example_app",
      "role": "extended",
      "scope_note": "Only the deterministic evaluator and unit table; no wiring to the run endpoint yet."
    }
  ],
  "capabilities": [],
  "tech_stack_spec": {
    "dependencies": [
      "pydantic",
      "pytest",
      "mypy",
      "ruff"
    ],
    "configurations": "No new environment variables. Named constants for input length cap and nesting-depth cap live in backend/app/router/constants.py."
  },
  "instructions": [
    "Create backend/app/router/unit_table.py as the single source of truth for the evaluator's accepted language: operators (+, -, x or the multiplication sign, / or the division sign, parentheses, percent), unit families length, speed and temperature with unit names, aliases and conversion factors or functions, plus the input length cap and nesting-depth cap. Typed literals, mypy-strict clean.",
    "Create backend/app/router/evaluator.py with a tokenizer that accepts ONLY numbers, the allow-listed operators, parentheses, the percent sign and unit names from the unit table. Anything else is rejected before parsing. Enforce the length and nesting caps.",
    "Implement a recursive-descent parser/evaluator by hand. Do not use eval, exec, ast.literal_eval, ast.parse or any dynamic-evaluation library. Support precedence, unary minus, percentages and a 'quantity unit to unit' conversion form within one family. Temperature conversion must be affine (not a pure factor); reject cross-family conversions and unknown units.",
    "Expose a pure function evaluate(expression: str) returning a typed result (accepted with value and normalised unit, or rejected with a machine-readable reason). Never raise on bad input; division by zero is a rejection.",
    "Expose a validate-only entry point used later to decide whether the second reserved unit can be released, sharing the same tokenizer and table so the two cannot drift.",
    "Expose a function in unit_table.py that renders the deterministic route's supported-operations line from the table, for use by Phase 3. Do not hand-write that line anywhere.",
    "Write backend/tests/router/test_evaluator.py covering: each operator and precedence; percentages; each unit family including temperature offsets; 72 km/h to m/s equals 20; rejection of identifiers, function calls, attribute access, dunder strings, semicolons, quotes, import text and unicode lookalikes; length and nesting caps; division by zero; cross-family conversions; and a test asserting the source file contains no 'eval(' or 'ast' import.",
    "Write a test proving every unit and operator in the table is accepted by the validator and that the generated supported-operations line mentions exactly the table's families (single-source check)."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Hand-written parsers have subtle precedence, unary and percent-semantics bugs; the AI coder may reach for eval or ast as a shortcut; temperature conversion is easily implemented as a pure ratio.",
    "mitigation_strategy": "Tokenizer allow-list runs before any parsing; a source-scanning test forbids eval and ast; table-driven tests include fixed numeric expectations for each family, including temperature offsets and percent cases; define percent semantics in a docstring before coding."
  },
  "verification": "Run `uv run pytest backend/tests/router/test_evaluator.py`, `uv run ruff check .` and `uv run mypy`; all pass. In a Python shell, evaluate('72 km/h to m/s') accepts with value 20, and evaluate('__import__(\"os\")') and evaluate('1/0') are rejected without raising. Confirm the evaluator test that scans for eval/ast passes.",
  "references": [
    {
      "standard": "Spec4 pattern library - structured_outputs mechanism",
      "url": "https://github.com/robertcrowe/Spec4/blob/dev/src/spec4/agentifier/patterns/mechanisms/structured_outputs.md"
    }
  ]
}
---

# Phase 2 of 10: Deterministic Evaluator and Unit Table

Build the no-model route: a single-source unit table and a closed-grammar tokenizer feeding a hand-written recursive-descent evaluator for arithmetic, percentages and length, speed and temperature conversions. Model-produced text is never executed, so this must be correct and rigorously tested before anything depends on it.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Router_Example_App — product feature — extended in this phase

*Scope for this phase: Only the deterministic evaluator and unit table; no wiring to the run endpoint yet.*

Teaches routing: one cheap classification call chooses among four existing paths and then deterministic code dispatches to the chosen path, with the model that decided taking no further part. It shows decisions, honest agreement history and real cost savings.

**Invocation**

- Trigger: The visitor chooses one of six preset requests or types their own and starts the run; or chooses to re-run a misrouted preset through its expected route.

**Inputs**

- `Request` (text, required) — One of six curated presets (request only, each with an expected route and one-line reason) or free text.
- `Route descriptions` (list of four one-line descriptions, required) — Told to the router and displayed exactly as given. The deterministic line lists supported operations and unit families from the same table the evaluator validates against. The RAG line lists subjects derived at startup from the indexed document titles.
- `Decision margin and cost order` (fixed settings, required) — Margin for low-confidence decisions and cost order (deterministic, single call, RAG, search plus generation), shown on the page.
- `Re-run choice` (choice, optional) — Offered once per eligible preset run to re-run through the expected route.

**Outputs**

- Primary: A decision card (chosen route, one-line rationale, all four scores, agreement statement for presets: agreed, 'misrouted' or 'declined'), the answer from the dispatched path labelled with its path, a cost strip, an agreement history, and for eligible runs a side-by-side re-run.
- Format: Decision card, answer in the corresponding example app's layout, comparison strip, per-preset and overall history
- Schema notes: Routes: no-model evaluator over allowed arithmetic and length, speed, temperature conversions; single call; RAG retrieval; web search plus one generation. Model-produced text is never executed. If the top two scores are within the margin, the run is low-confidence: it dispatches to the cheaper of the two with the caveat shown. If a deterministic choice cannot be computed, dispatch goes to single call and the card says so; for a low-confidence tie the other torn route is used. Cost strip compares the route taken with a 'no router' baseline (search plus generation) by model calls, searches, retrievals and time, with router overhead shown separately. Baseline time is labelled 'typical' and is the median of real search-route runs, shown only after at least five observations, with sample size, otherwise counts only. Per-preset agreed, disagreed and declined counts and rates (agreed divided by all three) show counts only until five observations. Free-text runs, re-runs and lucky tie-breaks earn no history credit. Re-run costs one run, shows router overhead as zero, and never feeds histories. Overview states the scores are uncalibrated self-report and the agreement rate is the one calibrated number.

**Success criteria**

- Route descriptions on the page match byte for byte what the router received, with the margin beside them.
- Every run ends in exactly one of a routed answer or a low-confidence card; a refused-before-start run is not an ending.
- All four scores appear on every decision card.
- A deterministic result is only released after the evaluator accepts the expression, and model text is never executed.
- No run exceeds 2 model-call units, plus one search on the search route; units are reserved before the router runs and the second is released once the evaluator accepts.
- The cost strip never presents the baseline's time as this run's time and never shows a hard-coded figure.
- Histories survive interruptions of the service and respect the five-observation rule.
- A re-run is offered once, only when a preset's dispatched route differs from expected, and never for free text.
- 5 runs per visit with a visible counter; at zero the input and run controls are disabled with a message that tells the 5-run limit from the shared cap, and earlier results remain.

**Failure modes**

- The router returns a malformed or incomplete decision (likelihood: medium) — mitigation: Treat it as declined for presets, show it candidly and dispatch via the low-confidence path or a clear failure.
- The evaluator cannot compute the router's expression (likelihood: medium) — mitigation: Fall back as specified and state the misroute plainly on the card.
- Visitors read the scores as calibrated probabilities (likelihood: medium) — mitigation: State that they are uncalibrated self-report and highlight the measured agreement rate.
- Too little history for a meaningful rate or typical time (likelihood: high) — mitigation: Show counts only and an explanatory note until five observations exist.
- Shared cap is too close for a complete run (likelihood: medium) — mitigation: Refuse before anything runs, with a message naming the shared cap.
- Route description list goes out of date with the dataset or evaluator (likelihood: low) — mitigation: Generate the lines from the retriever's indexed titles and the evaluator's own table.

- depends on: shared_framework_services, tool_use_integration, rag_example_app, single_call_example_app (build these no later than `router_example_app`)
- entities: Request, Route, Routing Decision, Score, Expression, Expected Route, Cost Strip, Agreement History, Latency History, Run Allowance

### UI surfaces for this phase (from the design)

- **`Router Knowledge Panel`** [non_ai]
  - screens: visitor
  - output: Four route descriptions verbatim plus margin and cost order
  - states: default
  - reads: Route
- **`Router Cost Strip`** [non_ai]
  - screens: visitor
  - output: Run cost vs no-router baseline, overhead separate, typical time only at n>=5
  - states: counts only, with typical time
  - reads: CostStrip, LatencyHistory
  - after (advisory UI ordering): Router Example App
- **`Router Comparison Re-run`** [non_ai]
  - screens: visitor
  - inputs: Run it the expected way button
  - output: Side-by-side original and expected-route result, overhead 0, not feeding history
  - states: offered, used
  - reads: RoutingDecision
  - after (advisory UI ordering): Router Decision and Answer Card
- **`Router Agreement Panel`** [non_ai]
  - screens: visitor
  - output: Per-preset agreed/disagreed/declined counts, rate only at 5+ observations, tie-break footnote
  - states: counts only, rate shown
  - reads: AgreementHistory
  - after (advisory UI ordering): Router Example App
The following surface(s) realize the AI capability `router_example_app` — one unit of work; the surfaces are views onto it:
- **`Router Example App`** [ai]
  - screens: visitor
  - inputs: six preset buttons, free-text field, run button
  - output: Run flow with reserved units, routed answer card or low-confidence card, with fallback variants
  - states: idle, multi-step loading, routed answer, low-confidence, fallback note, runs exhausted, refused by shared cap
  - reads: PresetRequest, RoutingDecision, RunAllowance
  - writes: RoutingDecision
  - after (advisory UI ordering): Example App Navigation, Router Knowledge Panel
The following surface(s) realize the AI capability `request_route_classification` — one unit of work; the surfaces are views onto it:
- **`Router Decision and Answer Card`** [ai]
  - screens: visitor
  - output: Four score bars, chosen route highlighted, rationale, answer labelled with path
  - states: routed, low-confidence, fallback
  - reads: RoutingDecision, Expression, Passage
  - after (advisory UI ordering): Router Example App
The following surface(s) realize the AI capability `search_route_answer_generation` — one unit of work; the surfaces are views onto it:
- **`Router Search Answer`** [ai]
  - screens: visitor
  - output: 2-5 sentence snippet-only answer with bracketed indices
  - states: shown
  - after (advisory UI ordering): Router Decision and Answer Card
The following surface(s) realize the AI capability `router_free_text_request_answering` — one unit of work; the surfaces are views onto it:
- **`Router Free Text Answer`** [ai]
  - screens: visitor
  - output: Concise direct answer from the request only
  - states: shown
  - after (advisory UI ordering): Router Decision and Answer Card

## Tech Stack

**Dependencies:**

- pydantic
- pytest
- mypy
- ruff

**Configurations:** No new environment variables. Named constants for input length cap and nesting-depth cap live in backend/app/router/constants.py.

**Approved stack for this phase's declared work** (deterministic, from the stack spec):

- Groq (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`
- OpenRouter free models (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`
- Exa Search API (integrations): ranked real web search results (title, snippet, source) through the single shared wrapper services/web_search.py, called directly in-process (no MCP) by the tool-use integration, the planning agent's research steps, the ReAct loop's act step, and the Router's search_generation route — serves `router_example_app`
- OpenAI Moderation API (omni-moderation-latest) (integrations): pre-dispatch safety screening of free-form visitor input only (orchestrated subagents, ReAct loop, Router free text), free of charge so it does not consume model quota; runs before any allowance hold and fails closed; preset input skips it and the collaboration app never calls it — serves `router_example_app`
- dataset_embeddings (persistence) — serves `router_example_app`
- search_queries (persistence) — serves `router_example_app`
- usage_limits (persistence): the showcase-wide model/search allowance gate enforced server-side before every provider call by every example app, windowed per UTC hour and per UTC day — serves `router_example_app`
- allowance_holds (persistence): reserve/redeem/refund records against the shared usage gate so a run's full call budget is held before its first model call and a run that cannot finish is never started; the Router holds 2 units after moderation and before the router call and releases the second once the evaluator accepts; a comparison re-run holds only the expected route's dispatch cost — serves `router_example_app`
- moderation_log (persistence): safety-gate telemetry for free-form input: a salted hash of the question (never raw text), category, confidence, latency and whether the call failed closed — serves `router_example_app`
- router_agreement_records (persistence): NEW WORK. Append-only, shared-across-visitors record of one row per qualifying preset run, from which per-preset agreed/disagreed/declined counts, rates and the overall rate are computed in SQL; free-text runs, comparison re-runs and malformed-decision fallbacks write no row; a low-confidence tie-break landing on the expected route is recorded 'declined' and earns no credit; cells show counts only until 5 observations — serves `router_example_app`
- router_latency_observations (persistence): NEW WORK. Append-only, shared-across-visitors record of one row per real search_generation-route run (comparison re-runs excluded), from which the rolling median behind the cost strip's 'typical' baseline is computed in SQL over the most recent N rows; sample size is the row count; below 5 observations the baseline is shown as counts only — serves `router_example_app`
- service_log_entries (persistence): the shared services' per-call log: which capability was invoked, by which example app, outcome and usage accounting, for every generation, embedding, search and moderation call — serves `router_example_app`
- router_preset_catalog (persistence): NEW WORK. The six curated Router requests, each with an expected route and a one-line reason, including the two control/near-miss pairs; stores requests only, never answers; expected_route uses exactly the route ids deterministic_evaluator, single_call, retrieval and search_generation; typed Python literals — serves `router_example_app`
- router_unit_table (persistence): NEW WORK. The single source of truth for the deterministic evaluator's accepted language (operators, unit names and factors in length, speed and temperature, input length and nesting caps), read by the validator, the evaluator and the generated route description so they cannot drift — serves `router_example_app`
- router_route_descriptions (persistence): NEW WORK. The four one-line route descriptions generated at startup (never hand-written) from the unit table, the retriever's indexed document titles, the search tool's declared schema and the single-call capability's description, each with its cost_rank; shown byte for byte as the router received them — serves `router_example_app`
- router_prompt_templates (persistence): NEW WORK. The static, versioned route-classification prompt (request delimited as untrusted data) with its typed decision schema — serves `router_example_app`
- educational_overviews (persistence): per-app short educational overview content, quota rationale and cross-references (Planning Agent and ReAct Loop; Router's contrast with Tool Use, Planning Agent and ReAct Loop and its uncalibrated-scores statement) — serves `router_example_app`
- router_run_allowance (persistence): NEW WORK. The Router's advisory five-run counter plus the visitor's retained decision cards, routed answers and cost strips, stamped with the UTC hour; a comparison re-run costs one run and a refused run costs none; the client decrements from the end-of-run event — serves `router_example_app`
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

1. Create backend/app/router/unit_table.py as the single source of truth for the evaluator's accepted language: operators (+, -, x or the multiplication sign, / or the division sign, parentheses, percent), unit families length, speed and temperature with unit names, aliases and conversion factors or functions, plus the input length cap and nesting-depth cap. Typed literals, mypy-strict clean.
2. Create backend/app/router/evaluator.py with a tokenizer that accepts ONLY numbers, the allow-listed operators, parentheses, the percent sign and unit names from the unit table. Anything else is rejected before parsing. Enforce the length and nesting caps.
3. Implement a recursive-descent parser/evaluator by hand. Do not use eval, exec, ast.literal_eval, ast.parse or any dynamic-evaluation library. Support precedence, unary minus, percentages and a 'quantity unit to unit' conversion form within one family. Temperature conversion must be affine (not a pure factor); reject cross-family conversions and unknown units.
4. Expose a pure function evaluate(expression: str) returning a typed result (accepted with value and normalised unit, or rejected with a machine-readable reason). Never raise on bad input; division by zero is a rejection.
5. Expose a validate-only entry point used later to decide whether the second reserved unit can be released, sharing the same tokenizer and table so the two cannot drift.
6. Expose a function in unit_table.py that renders the deterministic route's supported-operations line from the table, for use by Phase 3. Do not hand-write that line anywhere.
7. Write backend/tests/router/test_evaluator.py covering: each operator and precedence; percentages; each unit family including temperature offsets; 72 km/h to m/s equals 20; rejection of identifiers, function calls, attribute access, dunder strings, semicolons, quotes, import text and unicode lookalikes; length and nesting caps; division by zero; cross-family conversions; and a test asserting the source file contains no 'eval(' or 'ast' import.
8. Write a test proving every unit and operator in the table is accepted by the validator and that the generated supported-operations line mentions exactly the table's families (single-source check).

## Risk Assessment

**Potential bottlenecks:**

Hand-written parsers have subtle precedence, unary and percent-semantics bugs; the AI coder may reach for eval or ast as a shortcut; temperature conversion is easily implemented as a pure ratio.

**Mitigation strategy:**

Tokenizer allow-list runs before any parsing; a source-scanning test forbids eval and ast; table-driven tests include fixed numeric expectations for each family, including temperature offsets and percent cases; define percent semantics in a docstring before coding.

## Verification

Run `uv run pytest backend/tests/router/test_evaluator.py`, `uv run ruff check .` and `uv run mypy`; all pass. In a Python shell, evaluate('72 km/h to m/s') accepts with value 20, and evaluate('__import__("os")') and evaluate('1/0') are rejected without raising. Confirm the evaluator test that scans for eval/ast passes.

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_first_visit_is_fast_with_no_cold_start_delay__including_the_embedding_explorer_`: First visit is fast with no cold-start delay, including the embedding explorer. — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_`: Total model, search and embedding spend stays within shared hourly and daily caps. — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_app_run_limits_are_visible_and_enforced__and_messages_always_tell_app_level_limits_from_shared_caps_`: Per-app run limits are visible and enforced, and messages always tell app-level limits from shared caps. — delivered by allowance_holds, browser_local_storage, usage_limits
- `nfr_streaming_progress_such_as_live_status_and_trace_entries_appears_as_steps_complete_`: Streaming progress such as live status and trace entries appears as steps complete. — delivered by @microsoft/fetch-event-source, agent_loop_runtime, sse-starlette, tls_termination_and_static_serving
- `nfr_visitor_facing_history_and_statistics_remain_available_over_time_`: Visitor-facing history and statistics remain available over time. — delivered by primary_store, router_agreement_records, router_latency_observations
- `nfr_failures_are_always_shown_candidly_and_never_replaced_with_invented_results_`: Failures are always shown candidly and never replaced with invented results. — delivered by OpenRouter free models (via LiteLLM and PydanticAI) [single_call], react_runs


## References

- [Spec4 pattern library - structured_outputs mechanism](https://github.com/robertcrowe/Spec4/blob/dev/src/spec4/agentifier/patterns/mechanisms/structured_outputs.md)
