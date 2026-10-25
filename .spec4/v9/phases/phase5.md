---
{
  "phase_number": 5,
  "total_phases": 10,
  "phase_title": "Run Endpoint, Reservation and Decision Card",
  "phase_summary": "Add POST /api/router/run with the fixed run order (moderation for free text, 2-unit hold, router call, staged SSE) and the frontend run experience: presets plus free text, runs-remaining counter, exhausted and shared-cap states, and the decision card with all four scores and the agreement statement. The low-confidence card ending is built here; answers from routes follow in later phases.",
  "features": [
    {
      "id": "router_example_app",
      "role": "extended",
      "scope_note": "Run endpoint, allowance and hold, SSE staging, decision card, low-confidence card and run-limit UI; route dispatch, histories and re-run come later."
    }
  ],
  "capabilities": [
    {
      "id": "router_example_app",
      "role": "introduced",
      "scope_note": "Coordinator assembled: moderation, hold, classification, decision rules and staged events; dispatch targets are attached in Phases 6 and 7."
    },
    {
      "id": "request_route_classification",
      "role": "extended",
      "scope_note": "Wired into the run flow with hold and the decision card; dispatch comes later."
    }
  ],
  "tech_stack_spec": {
    "dependencies": [
      "fastapi",
      "sse-starlette",
      "sqlalchemy",
      "asyncpg",
      "httpx",
      "@microsoft/fetch-event-source",
      "react-markdown",
      "@tanstack/react-query",
      "vitest"
    ],
    "configurations": "No new environment variables. Uses OPENAI_API_KEY (moderation, fails closed), DATABASE_URL, and existing GENERATION_HOURLY_LIMIT and SEARCH_HOURLY_LIMIT gates."
  },
  "instructions": [
    "Study backend/app/react/ and backend/app/orchestrated/ for how they call services/moderation.moderate, reserve and refund allowance holds, and stream SSE. Reuse those service entry points unchanged.",
    "Implement POST /api/router/run in backend/app/api/router.py as a thin handler delegating to backend/app/router/service.py. Request: the request text, optional preset_id, visit id. Validate length and trim.",
    "Fixed run order: (1) moderation for free text ONLY (presets skip it), fail closed; (2) hold 2 units against the shared generation cap via the existing allowance_holds mechanism before the first SSE event; (3) router classification; (4) staged events. If moderation flags, or fails closed, or the hold cannot be made because the shared cap is too close, return an ordinary HTTP error response (no stream), consume no run, take no hold and write nothing.",
    "Distinguish error bodies so the UI can tell the causes apart: moderation flagged, moderation unavailable, shared cap too close (naming the shared cap). Do not mix these with the app's 5-run limit, which is advisory and client-side.",
    "Stream with sse-starlette and open the DB session inside the async generator via async_session_factory; never use Depends(get_db_session) in the generator. Stop spending if the client disconnects.",
    "Emit staged events: a decision event (chosen route, rationale, all four scores, expression if any, agreement statement for presets, low_confidence flag with the torn pair and the caveat, malformed-decision note) and an end-of-run event carrying the outcome. For this phase, after a decision, route dispatch is a stub that ends the run with a clear 'dispatch not available yet' note; the stub must still release or redeem holds correctly (refund the unspent hold) and must not be reachable in production configuration once Phase 6 lands.",
    "Low-confidence runs: the card names the two routes torn between, states the cheaper-of-the-two cost order caveat, and uses the Phase 4 rules. Every started run ends in exactly one of a routed answer or low-confidence card.",
    "Frontend: build the run view in frontend/src/apps/router/ with preset selection, free-text input, a run button, the runs-remaining counter (advisory localStorage allowance, 5 runs, stamped with the UTC hour, through the existing useRunAllowance pattern), disabled input and a clear message when exhausted that names the 5-run session limit versus the shared framework cap, while previous results stay on screen. A refused run costs no run; the client decrements only from the end-of-run event.",
    "Build the decision card: chosen route, one-line rationale rendered as escaped plain text, all four scores on every run labelled as uncalibrated router self-report (never percentages), agreement statement for presets ('agreed', 'misrouted', 'declined'), low-confidence caveat. Consume the SSE stream with @microsoft/fetch-event-source and abort on unmount. Retries must be disabled on this quota-spending call. Reference .spec4/v9/design/mock.html.",
    "Tests: moderation-before-hold ordering and presets skipping moderation; refusal returns HTTP error with no hold, no run and no history; hold of 2 units taken before the router call; SSE event order; low-confidence card content; malformed decision note; exhausted-state and shared-cap messaging in Vitest; no stream generator uses Depends for the session."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Ordering mistakes (hold before moderation, or a hold taken for a refused run) would leak quota; a request-scoped DB session inside the SSE generator breaks; the run counter could be decremented for refused runs; Caddy/SSE buffering hides progressive events.",
    "mitigation_strategy": "Centralise the order in service.py with tests asserting call order; open the session inside the generator; decrement only on the end-of-run event; verify progressive SSE delivery manually through the local server."
  },
  "verification": "Run `uv run pytest backend/tests/router`, `uv run ruff check .`, `uv run mypy`, `cd frontend && npx vitest run`, `cd frontend && npm run build`. With the stack running, run preset 5 and observe a decision card with four scores, the agreement statement and the runs-remaining counter dropping from 5 to 4; flagged free text returns an error with the counter unchanged. Exhaust five runs and confirm the disabled state names the 5-run limit and earlier cards remain. Cite nfr_per_app_run_limits_are_visible_and_enforced__and_messages_always_tell_app_level_limits_from_shared_caps_, nfr_streaming_progress_such_as_live_status_and_trace_entries_appears_as_steps_complete_ and nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_.",
  "references": [
    {
      "standard": "sse-starlette",
      "url": "https://github.com/sysid/sse-starlette"
    },
    {
      "standard": "Server-Sent Events (WHATWG HTML Living Standard, section 9.2)",
      "url": "https://html.spec.whatwg.org/multipage/server-sent-events.html"
    },
    {
      "standard": "@microsoft/fetch-event-source",
      "url": "https://github.com/Azure/fetch-event-source"
    },
    {
      "standard": "OpenAI Moderation API guide",
      "url": "https://platform.openai.com/docs/guides/moderation"
    }
  ]
}
---

# Phase 5 of 10: Run Endpoint, Reservation and Decision Card

Add POST /api/router/run with the fixed run order (moderation for free text, 2-unit hold, router call, staged SSE) and the frontend run experience: presets plus free text, runs-remaining counter, exhausted and shared-cap states, and the decision card with all four scores and the agreement statement. The low-confidence card ending is built here; answers from routes follow in later phases.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Router_Example_App — product feature — extended in this phase

*Scope for this phase: Run endpoint, allowance and hold, SSE staging, decision card, low-confidence card and run-limit UI; route dispatch, histories and re-run come later.*

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

### router_example_app — AI capability — introduced in this phase

*Scope for this phase: Coordinator assembled: moderation, hold, classification, decision rules and staged events; dispatch targets are attached in Phases 6 and 7.*

Serves product feature(s): `router_example_app` (specified above).

- Tier: `chained_calls`
- Scope: `feature`
- Phase priority: `steel_thread`
- Requires: `pipeline_runner`
- Tier rationale: Stripped of the 'router' framing, the feature takes free-text input and must decide, by meaning, whether the request needs outside facts. Deterministic rules would get this wrong: 'Who won the match last night?' and 'Explain what a match statement is' share surface forms but need different routes, so classification is semantic and a keyword or regex rule fails on the long-tail of natural-language phrasing. A static route is not possible because the path depends on the classification output. The classifier needs no retrieved facts, so embeddings are not required, and a centroid router would not generate an answer anyway. A single_call does not suffice for the search path: the Exa search must run on the visitor's request after the classifier has chosen the route, and its snippets must then be fed into a second LLM call that composes the answer. That is a true sequential dependency (LLM classify -> code search call -> LLM answer from snippets), not just formatting. Route selection is a fixed two-way branch with a known structure, so this is a simple chain with a conditional branch, not an adaptive planning agent. The plain-answer route is only classify -> generate. Both routes reuse the existing litellm/pydantic-ai lanes and the Exa web_search service.
- Next-cheaper tier would lose: single_call would lose the ability to run a web search conditioned on the classification result and feed the snippets into the answer, so time-variable factual requests would be answered from model memory instead of grounded, current sources.
- Borderline — seams to watch: If the classifier output is just a one-token route label and the search step is plain code, this could be seen as single_call plus deterministic dispatch, with the second LLM call being the only real generation; If the route set grows or the model begins choosing among many tools dynamically, it drifts toward tool_agent; If a stated search-needed boolean were inferred by the same call that answers, a single structured-output call with tool access might suffice

Teach routing by classifying a visitor's request once with a cheap model call, then dispatching deterministically to one of four existing paths (including a plain generated answer or a web-search-snippet answer) or declining with a low-confidence card, while showing honest decisions, agreement history and real cost savings.

**Invocation**

- Trigger: Visitor selects one of six preset requests or types their own and starts a run; or opts to re-run a misrouted preset through its expected route (offered once, presets only).
- Mode: synchronous

**Inputs**

- `request` (string, required) — Preset request text or visitor free text. Screened by moderation before any model-call unit is spent.
- `preset_id` (string | null, optional) — Identifier of the preset when chosen from the six presets; carries the expected route. Null for free text.
- `route_descriptions` (list[string] (4), required) — Four one-line route descriptions, a single source of truth sent verbatim to the router and rendered byte for byte on the page beside the margin.
- `decision_settings` (object {margin: float, cost_order: list[route_id]}, required) — Fixed settings: decision margin (minimum gap between top score and runner-up) and cost ordering used for tie handling and cost strip.
- `rerun_choice` (enum {none, rerun_expected}, optional) — Visitor's choice to re-run a misrouted preset through its expected route.
- `visit_id` (string, required) — Session identifier used for the 5-run allowance counter.

**Outputs**

- Primary: Either a routed answer (labelled with its path) or a low-confidence card, always accompanied by a decision card (chosen route, one-line rationale, all four scores, agreement statement for presets), a cost strip, agreement history, latency history, and the run allowance counter; for eligible misrouted presets, a side-by-side re-run.
- Format: JSON object rendered by the UI
- Schema notes: decision: {route, rationale, scores: {route_id: float x4}, expression: string|null, agreement: 'agreed'|'misrouted'|'declined'|null}; outcome: 'routed'|'low_confidence' (exactly one); answer: {path, text, sources?}; cost_strip: {router_units, path_units, search_calls, measured_run_ms, baseline_ms: {value, label: 'baseline, not this run'}|null}; history: {agreement_rate|null, typical_time|null, n}; allowance: {remaining, limit: 5, blocked_reason: null|'visit_limit'|'shared_cap'}. Scores are uncalibrated and labelled as such.

**Decision authority:** autonomous

**Knowledge sources**

- `Route descriptions and preset catalogue` (other) — Four one-line route descriptions, six preset requests with expected routes, margin and cost-order settings. [updates: static (changes only with code deploys)]
- `Run history store` (relational_db) — Persisted agreement outcomes and measured latencies per route, used for agreement and typical-time displays. [updates: real-time]
- `Exa web search` (api) — Live web snippets used by the search route. [updates: real-time]

**Tool access**

- Fetch web search snippets for the search-composed answer route (max one search per run). (existing_third_party_mcp, mcp)
  - MCP server: Exa MCP server (https://github.com/exa-labs/exa-mcp-server)
  - Rationale: Maintained MCP server exists for Exa; reuse rather than rebuild. The existing web_search.py service remains the app-facing wrapper for budgeting and snippet trimming.
- Evaluate the router's arithmetic expression deterministically before releasing a computed result. (to_build_internal, direct)
  - Rationale: Pure in-process function with a single consumer and no external resource; an existing evaluator from the tool-use app is reused if present. No MCP server was considered because wrapping an in-process function adds overhead for nothing.

**Mechanisms**

- `structured_outputs` — Matches 'downstream code consumes the output programmatically': deterministic dispatch code reads the chosen route, four scores, and the expression, and the evaluator parses the expression. Bounded route enum prevents invented routes. Implemented through the existing pydantic-ai typed-output lane.
  - definition: Typed or schema-constrained generation: the model's output is forced to conform to a defined structure — a JSON Schema, a Pydantic model, an enum, a function signature. Instead of free text the consum…
  - schema: RoutingDecision {route: enum(4), rationale: str, scores: dict[route -> float] (all 4 required), expression: str | null}
  - lane: pydantic-ai over FallbackModel
  - retries: 1
- `mcp` — The search route consumes web search, which has maintained MCP servers; reuse over rebuild. Exa publishes an MCP server that can serve the one-search-per-run need, while the existing web_search.py service remains the wrapper for budget and snippet handling.
  - definition: Whether to use the Model Context Protocol (MCP) for tool and data access. MCP bundles two genuinely distinct decisions that must be reasoned about separately: **consumption** — for a capability you *n…
  - server: Exa MCP server
  - max_searches_per_run: 1

**Success criteria**

- Route descriptions displayed match byte for byte what the router received, with the margin beside them (verified by hash comparison).
- Every run that starts ends in exactly one of a routed answer or a low-confidence card; refusal before start is not counted as an ending.
- All four scores appear on every decision card.
- A deterministic result is released only after the evaluator accepts the expression; model text is never executed.
- No run exceeds 2 model-call units plus one search on the search route; units are reserved before the router runs and the second is released once the evaluator accepts.
- Cost strip never presents the baseline's time as this run's time and never shows a hard-coded figure; all values derive from measured or registry data.
- Agreement and latency histories persist across service interruptions and show no rate or typical time below five observations.
- Re-run offered at most once, only when a preset's dispatched route differs from expected, never for free text.
- 5 runs per visit with a visible counter; at zero, input and run controls are disabled with a message distinguishing the 5-run limit from the shared cap, and earlier results remain visible.
- Router decision schema validation success rate >= 98% after one retry on the eval set.

**Failure modes**

- Router returns a malformed or incomplete decision (missing scores, unknown route) (likelihood: medium) — mitigation: Typed output validated by pydantic-ai; one retry on the FallbackModel; if still invalid, end in a low-confidence card, not a guessed route.
- Evaluator cannot compute the router's expression (likelihood: medium) — mitigation: Evaluator uses a restricted arithmetic grammar and never executes model text; on rejection, end in a low-confidence card (or fall back per spec to the generated-answer path only if the second unit was not released); release the reserved second unit.
- Visitors read scores as calibrated probabilities (likelihood: high) — mitigation: Label scores as uncalibrated router scores next to the card; never format as percentages.
- Too little history for a meaningful rate or typical time (likelihood: high) — mitigation: Show 'not enough runs yet' with the count until five observations exist.
- Shared cap too close for a complete run (likelihood: medium) — mitigation: Reserve units before the router runs; if the reservation fails, refuse before start with a shared-cap message that does not decrement the visit allowance.
- Route description list drifts from the dataset or evaluator capabilities (likelihood: medium) — mitigation: Single constant for descriptions used by both router prompt and UI; a test asserts the described routes match the registered handlers and dataset.
- Web search (Exa) failure or empty snippets on the search route (likelihood: medium) — mitigation: Return a clearly labelled search-unavailable result with no fabricated sources; do not re-route silently.
- Prompt injection in free text steering the router or path (likelihood: medium) — mitigation: Moderation screening first; router output limited to a closed route enum; dispatch is deterministic code.

**Escalation on failure:** Router failure, margin not met, or evaluator rejection yields a low-confidence card explaining why, with no answer fabricated. Shared-cap exhaustion shows a distinct message. Errors are logged with the run id for operator review; no human review queue.

**Privacy & safety**

- Free-text requests are screened with the existing OpenAI Moderation service before any model call; flagged requests are refused before start.
- No PII is collected; request text is stored only as needed for history aggregates and is not tied to identity.
- Model-produced expressions are parsed by a restricted evaluator and never executed as code.
- Search-route answers cite only returned snippets and are labelled with their path.
- Scores are presented as uncalibrated.

**References**

- Anthropic, Building effective agents (routing and prompt chaining workflows): https://www.anthropic.com/research/building-effective-agents
- Pydantic AI documentation: https://ai.pydantic.dev
- LiteLLM fallbacks documentation: https://docs.litellm.ai
- Model Context Protocol: https://modelcontextprotocol.io
- Exa MCP server: https://github.com/exa-labs/exa-mcp-server

### request_route_classification — AI capability — extended in this phase

*Scope for this phase: Wired into the run flow with hold and the decision card; dispatch comes later.*

Serves product feature(s): `router_example_app` (specified above).

- Tier: `single_call`
- Scope: `sub_feature`
- Phase priority: `steel_thread`
- Composed under: `router_example_app`
- Tier rationale: Stripped of marketing, the feature must map an open-ended free-text visitor request onto one of four routes, return a score per route, and emit a structured arithmetic expression when the deterministic route wins. A deterministic implementation (regex or keyword rules) would provably get wrong a request like 'what's the vibe of our refund policy versus last week's news?' or 'how many days between my birthday and Christmas', where the meaning rather than surface form decides the route. That is the deterministic 'doesn't work' case: unstructured natural language whose semantics drive the decision. Embeddings could rank similarity to the four route descriptions, but the output also needs a typed per-route score object and an extracted structured expression, which is generation/extraction that embeddings cannot do. One structured-output LLM call (pydantic-ai over the existing FallbackModel) produces all fields reliably. The input is bounded (one short request plus four one-line descriptions), no retrieval or tools are needed for classification, and the downstream routes belong to other features. Structured output is a mechanism, not a tier driver.
- Next-cheaper tier would lose: Embeddings could rank the four routes by semantic similarity but cannot generate the typed score object or extract the structured expression for the deterministic route, and short ambiguous requests would route poorly.
- Borderline — seams to watch: If the expression field is dropped and only a route label is needed, an embeddings nearest-centroid router (existing sentence-transformers) could suffice at lower cost.; If the per-route scores need to be well calibrated, the LLM's self-reported scores may be unreliable and an embedding similarity could be blended in.; If the free-model fallback chain proves too unreliable for structured output, re-check whether a deterministic pre-filter for obvious arithmetic is worth adding.

Classify one visitor request into one of four existing routes with a score per route, a one-line rationale, and (when the deterministic route wins) a structured expression, so that deterministic code can dispatch the request without the router taking further part.

**Invocation**

- Trigger: Visitor selects one of six preset requests or types free text and starts a run in Router_Example_App; the backend calls the router once per run, after one model-call unit has been reserved and before any dispatch.
- Mode: synchronous

**Inputs**

- `request` (string, required) — Visitor's free-text or preset request. Trimmed, length-capped (e.g. 500 chars) and, for free text, moderation-screened before the call.
- `route_descriptions` (list[{route_id: enum, description: string}] (exactly 4), required) — One-line descriptions of the four routes (single source of truth, same list rendered on the page byte for byte). The route ids are a fixed enum; the deterministic route's description states which expression grammar the evaluator accepts.
- `decision_margin` (number, required) — Fixed setting: minimum gap between the top score and the runner-up for a route to be chosen; otherwise the run ends as a low-confidence card. Applied by deterministic code, not by the model; passed to the prompt only if useful for scoring guidance (default: not passed).
- `cost_order` (list[route_id], optional) — Fixed setting ordering routes by cost, used by deterministic code for tie-breaking and the cost strip. Not required by the model call.

**Outputs**

- Primary: A typed routing decision: a score for each of the four routes, the proposed route, a one-line rationale, and an expression only when the deterministic route is proposed.
- Format: JSON object validated by a Pydantic model (via the existing pydantic-ai lane over FallbackModel, slugs from the shared model registry)
- Schema notes: { scores: {route_id: float 0..1} with exactly the four route ids as keys (all required); route: enum of the four ids; rationale: string (<=160 chars, one line); expression: string|null (non-null only if route == deterministic, null otherwise). Scores are relative rankings, not calibrated probabilities, and must be labelled as such in the UI. The chosen route, margin check, low-confidence outcome and tie-breaks are recomputed by deterministic code from the scores; the model's 'route' field is advisory and a mismatch with argmax is resolved in favor of the scores. The expression is untrusted text: it is never executed, only passed to the evaluator, and the deterministic result is released only if the evaluator accepts it.

**Decision authority:** autonomous

**Mechanisms**

- `structured_outputs` — Matches 'downstream code consumes the output programmatically': deterministic dispatch code reads the four scores, applies the margin, selects the route, and passes the expression to the evaluator. The enum-keyed schema also prevents invented routes.
  - definition: Typed or schema-constrained generation: the model's output is forced to conform to a defined structure — a JSON Schema, a Pydantic model, an enum, a function signature. Instead of free text the consum…
  - implementation: pydantic-ai typed output over the existing FallbackModel lane in agent_runtime.py
  - model: RoutingDecision {scores: dict[RouteId, float] (all four keys), route: RouteId, rationale: str, expression: str | None}
  - validators: all four keys present, scores in [0,1], expression null unless route == deterministic
  - retries: 1

**Success criteria**

- 100% of returned decisions contain all four scores (needed for the decision card); incomplete objects are rejected, never partially shown
- Schema-valid output rate >= 98% after at most one retry inside the reserved second model-call unit
- On the six presets, router top-route agrees with the expected route on at least 5 of 6 in offline evaluation, and agreement statements (agreed / misrouted / declined) are computed deterministically
- When route == deterministic, the evaluator accepts the expression on >= 90% of eligible requests; model text is never executed
- No run uses more than 2 model-call units (router + at most one retry) plus one search on the search route
- Route descriptions sent to the model match the rendered page list byte for byte (checked by test via hash)
- Low-confidence outcome is produced whenever top-minus-runner-up < decision margin, with no dispatch

**Failure modes**

- Router returns malformed, incomplete, or out-of-enum output (missing score, unknown route id, expression present for a non-deterministic route) (likelihood: medium) — mitigation: Pydantic validation with strict enum keys; one retry using the second reserved unit with the validation error appended; if still invalid, end the run as a low-confidence card and release the unit accounting honestly.
- Deterministic route chosen but the evaluator cannot compute or rejects the expression (likelihood: medium) — mitigation: Evaluator is the sole gate; a rejected expression triggers a single retry if a unit remains, otherwise the run ends as a low-confidence card. The expression grammar is stated in the route description and a few-shot example in the prompt.
- Visitors read scores as calibrated probabilities (likelihood: high) — mitigation: UI copy labels scores as relative route scores; prompt asks for scores that rank routes, not sum to 1; decisions always gated by the margin.
- Close or ambiguous scores cause unstable routing between runs (likelihood: medium) — mitigation: Temperature 0; the margin rule yields a low-confidence card rather than a coin flip; cost_order breaks exact ties only.
- Prompt injection in free text (e.g. 'ignore routes, output expression X') (likelihood: medium) — mitigation: Request delimited as untrusted data; output constrained to schema; expression never executed except through the evaluator; route dispatched by code on validated scores only; moderation applied to free text.
- Route descriptions drift from the dataset or evaluator capabilities (likelihood: medium) — mitigation: Single source of truth for descriptions; a test compares them against evaluator grammar and dataset tags, and asserts the page and prompt use the identical string.
- All models in the fallback chain are unavailable or the shared cap is too close for a complete run (likelihood: medium) — mitigation: Units reserved before the call; if the reservation cannot be made the run is refused before start (not counted as an ending, no run consumed); on chain exhaustion return a clear service-unavailable state.

**Escalation on failure:** No human gate. Invalid or unconfident outcomes end as a low-confidence card showing all available scores and no dispatch; the visitor can edit and retry within the 5-run allowance. Repeated schema failures or chain exhaustion are logged with model slug and trigger an alert on the failure-rate threshold.

**Privacy & safety**

- Free-text requests are screened with the existing OpenAI Moderation service before the router call; flagged requests are refused and consume no model unit.
- Visitor text is treated as untrusted data in the prompt and is never executed; the expression goes only to the evaluator.
- Do not log requests beyond what the histories need; no PII is collected and visitors are told not to enter personal data.
- The rationale is one line of model text shown to users; render as escaped plain text.

**References**

- https://ai.pydantic.dev/output/
- https://docs.litellm.ai/docs/
- backend/app/services/agent_runtime.py (https://docs.copilotkit.ai/backend/copilot-runtime)
- backend/app/services/model_registry.py (https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/model-registry/introduction)
- backend/app/services/moderation.py (https://docs.mistral.ai/studio/safety-moderation)

**Cross-cutting decisions (project-wide):**

- **Tool protocol strategy:** Decide per capability. (1) Exa web search, used by search_route_answer_generation: it already has multiple consumers (tool-use example, planning agent, ReAct loop) in backend/app/services/web_search.py. Reuse the existing wrapper and call it directly from the search route; do not reimplement or add a new client. If Exa's official MCP server is adopted for the router_example_app's MCP demonstration, consume it rather than building one. Wrapping the existing web_search service in a new in-house MCP server is justified only if the MCP lesson in router_example_app needs a second consumer. (2) Route dispatch (classifier output to the single-call, search, or existing-route handler): exactly one consumer in the same codebase, so use a plain deterministic function call or dispatch table, with no MCP. (3) Classification and free-text answering: model calls through the shared litellm registry or pydantic-ai agent runtime, which are direct in-process calls and not tools. (4) OpenAI Moderation: keep the existing direct call and, if the router accepts free-form input, reuse services/moderation.py as is. (5) Embeddings, pgvector and RAG are not needed by these features, so do not add them.
  - Rationale: Applying the mcp pattern's consumption-vs-exposure distinction per capability: consumption means reusing an existing MCP server (for example an Exa MCP server) before writing our own. Exposure means building an MCP server only when a capability has multiple consumers. Web search is the only capability with multiple consumers, and it is already centralised behind one Python service, so direct reuse is cheapest. Routing and dispatch have a single in-codebase consumer, so MCP would add protocol overhead with no benefit. The router_example_app lists both direct and mcp protocols; keep MCP confined to the single capability (search) where it demonstrates something, and keep everything else direct.

## Tech Stack

**Dependencies:**

- fastapi
- sse-starlette
- sqlalchemy
- asyncpg
- httpx
- @microsoft/fetch-event-source
- react-markdown
- @tanstack/react-query
- vitest

**Configurations:** No new environment variables. Uses OPENAI_API_KEY (moderation, fails closed), DATABASE_URL, and existing GENERATION_HOURLY_LIMIT and SEARCH_HOURLY_LIMIT gates.

**Approved stack for this phase's declared work** (deterministic, from the stack spec):

- Groq (via LiteLLM and PydanticAI) [single_call] (providers) — serves `request_route_classification`, `router_example_app`
- OpenRouter free models (via LiteLLM and PydanticAI) [single_call] (providers) — serves `request_route_classification`, `router_example_app`
- Exa Search API (integrations): ranked real web search results (title, snippet, source) through the single shared wrapper services/web_search.py, called directly in-process (no MCP) by the tool-use integration, the planning agent's research steps, the ReAct loop's act step, and the Router's search_generation route — serves `router_example_app`
- OpenAI Moderation API (omni-moderation-latest) (integrations): pre-dispatch safety screening of free-form visitor input only (orchestrated subagents, ReAct loop, Router free text), free of charge so it does not consume model quota; runs before any allowance hold and fails closed; preset input skips it and the collaboration app never calls it — serves `router_example_app`
- dataset_embeddings (persistence) — serves `router_example_app`
- search_queries (persistence) — serves `router_example_app`
- usage_limits (persistence): the showcase-wide model/search allowance gate enforced server-side before every provider call by every example app, windowed per UTC hour and per UTC day — serves `request_route_classification`, `router_example_app`
- allowance_holds (persistence): reserve/redeem/refund records against the shared usage gate so a run's full call budget is held before its first model call and a run that cannot finish is never started; the Router holds 2 units after moderation and before the router call and releases the second once the evaluator accepts; a comparison re-run holds only the expected route's dispatch cost — serves `request_route_classification`, `router_example_app`
- moderation_log (persistence): safety-gate telemetry for free-form input: a salted hash of the question (never raw text), category, confidence, latency and whether the call failed closed — serves `router_example_app`
- router_agreement_records (persistence): NEW WORK. Append-only, shared-across-visitors record of one row per qualifying preset run, from which per-preset agreed/disagreed/declined counts, rates and the overall rate are computed in SQL; free-text runs, comparison re-runs and malformed-decision fallbacks write no row; a low-confidence tie-break landing on the expected route is recorded 'declined' and earns no credit; cells show counts only until 5 observations — serves `request_route_classification`, `router_example_app`
- router_latency_observations (persistence): NEW WORK. Append-only, shared-across-visitors record of one row per real search_generation-route run (comparison re-runs excluded), from which the rolling median behind the cost strip's 'typical' baseline is computed in SQL over the most recent N rows; sample size is the row count; below 5 observations the baseline is shown as counts only — serves `request_route_classification`, `router_example_app`
- service_log_entries (persistence): the shared services' per-call log: which capability was invoked, by which example app, outcome and usage accounting, for every generation, embedding, search and moderation call — serves `request_route_classification`, `router_example_app`
- router_preset_catalog (persistence): NEW WORK. The six curated Router requests, each with an expected route and a one-line reason, including the two control/near-miss pairs; stores requests only, never answers; expected_route uses exactly the route ids deterministic_evaluator, single_call, retrieval and search_generation; typed Python literals — serves `request_route_classification`, `router_example_app`
- router_unit_table (persistence): NEW WORK. The single source of truth for the deterministic evaluator's accepted language (operators, unit names and factors in length, speed and temperature, input length and nesting caps), read by the validator, the evaluator and the generated route description so they cannot drift — serves `request_route_classification`, `router_example_app`
- router_route_descriptions (persistence): NEW WORK. The four one-line route descriptions generated at startup (never hand-written) from the unit table, the retriever's indexed document titles, the search tool's declared schema and the single-call capability's description, each with its cost_rank; shown byte for byte as the router received them — serves `request_route_classification`, `router_example_app`
- router_prompt_templates (persistence): NEW WORK. The static, versioned route-classification prompt (request delimited as untrusted data) with its typed decision schema — serves `request_route_classification`, `router_example_app`
- educational_overviews (persistence): per-app short educational overview content, quota rationale and cross-references (Planning Agent and ReAct Loop; Router's contrast with Tool Use, Planning Agent and ReAct Loop and its uncalibrated-scores statement) — serves `router_example_app`
- router_run_allowance (persistence): NEW WORK. The Router's advisory five-run counter plus the visitor's retained decision cards, routed answers and cost strips, stamped with the UTC hour; a comparison re-run costs one run and a refused run costs none; the client decrements from the end-of-run event — serves `request_route_classification`, `router_example_app`
- retriever (infrastructure): finds the top-N passages for a question's embedding; the Router's retrieval route calls this existing retriever through its existing entry point, unmodified — serves `router_example_app`
- pipeline_runner (infrastructure): fills the pipeline_runner substrate for the chained-calls writer-to-critic sequence (first response passed directly as the second call's input) and for the Router's classify, code-dispatch, optional-generation flow (one typed classification call with output retries zero, then code-owned dispatch); the usage gate checks every call exactly as on the LiteLLM path; no new dependency — serves `request_route_classification`, `router_example_app`
- tool_execution_harness (infrastructure): fills the tool_execution_harness substrate; the run-allowance check is a direct service-layer call, never a model-exposed tool, so the model cannot decide whether quota is spent; the Router reuses the shared wrapper rather than adding a harness — serves `router_example_app`
- httpx (libraries): async HTTP client for the shared Exa wrapper (tool use, planning, ReAct, Router search route) and the OpenAI Moderation call — serves `router_example_app`
- LiteLLM (libraries): unified interface to Groq and OpenRouter free models with retry and ordered fallback via model_registry.py; used by RAG, the single-call app and the Router's single_call and search_generation routes through the existing generation service — serves `router_example_app`
- PydanticAI (libraries): agent framework (second model lane) returning validated Pydantic models via FallbackModel over the shared chain: chained calls, planning agent, orchestrated subagents, collaboration agents, ReAct per-cycle calls and annotation, and the Router's single typed classification call (output retries zero) — serves `request_route_classification`, `router_example_app`
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

1. Study backend/app/react/ and backend/app/orchestrated/ for how they call services/moderation.moderate, reserve and refund allowance holds, and stream SSE. Reuse those service entry points unchanged.
2. Implement POST /api/router/run in backend/app/api/router.py as a thin handler delegating to backend/app/router/service.py. Request: the request text, optional preset_id, visit id. Validate length and trim.
3. Fixed run order: (1) moderation for free text ONLY (presets skip it), fail closed; (2) hold 2 units against the shared generation cap via the existing allowance_holds mechanism before the first SSE event; (3) router classification; (4) staged events. If moderation flags, or fails closed, or the hold cannot be made because the shared cap is too close, return an ordinary HTTP error response (no stream), consume no run, take no hold and write nothing.
4. Distinguish error bodies so the UI can tell the causes apart: moderation flagged, moderation unavailable, shared cap too close (naming the shared cap). Do not mix these with the app's 5-run limit, which is advisory and client-side.
5. Stream with sse-starlette and open the DB session inside the async generator via async_session_factory; never use Depends(get_db_session) in the generator. Stop spending if the client disconnects.
6. Emit staged events: a decision event (chosen route, rationale, all four scores, expression if any, agreement statement for presets, low_confidence flag with the torn pair and the caveat, malformed-decision note) and an end-of-run event carrying the outcome. For this phase, after a decision, route dispatch is a stub that ends the run with a clear 'dispatch not available yet' note; the stub must still release or redeem holds correctly (refund the unspent hold) and must not be reachable in production configuration once Phase 6 lands.
7. Low-confidence runs: the card names the two routes torn between, states the cheaper-of-the-two cost order caveat, and uses the Phase 4 rules. Every started run ends in exactly one of a routed answer or low-confidence card.
8. Frontend: build the run view in frontend/src/apps/router/ with preset selection, free-text input, a run button, the runs-remaining counter (advisory localStorage allowance, 5 runs, stamped with the UTC hour, through the existing useRunAllowance pattern), disabled input and a clear message when exhausted that names the 5-run session limit versus the shared framework cap, while previous results stay on screen. A refused run costs no run; the client decrements only from the end-of-run event.
9. Build the decision card: chosen route, one-line rationale rendered as escaped plain text, all four scores on every run labelled as uncalibrated router self-report (never percentages), agreement statement for presets ('agreed', 'misrouted', 'declined'), low-confidence caveat. Consume the SSE stream with @microsoft/fetch-event-source and abort on unmount. Retries must be disabled on this quota-spending call. Reference .spec4/v9/design/mock.html.
10. Tests: moderation-before-hold ordering and presets skipping moderation; refusal returns HTTP error with no hold, no run and no history; hold of 2 units taken before the router call; SSE event order; low-confidence card content; malformed decision note; exhausted-state and shared-cap messaging in Vitest; no stream generator uses Depends for the session.

## Risk Assessment

**Potential bottlenecks:**

Ordering mistakes (hold before moderation, or a hold taken for a refused run) would leak quota; a request-scoped DB session inside the SSE generator breaks; the run counter could be decremented for refused runs; Caddy/SSE buffering hides progressive events.

**Mitigation strategy:**

Centralise the order in service.py with tests asserting call order; open the session inside the generator; decrement only on the end-of-run event; verify progressive SSE delivery manually through the local server.

## Verification

Run `uv run pytest backend/tests/router`, `uv run ruff check .`, `uv run mypy`, `cd frontend && npx vitest run`, `cd frontend && npm run build`. With the stack running, run preset 5 and observe a decision card with four scores, the agreement statement and the runs-remaining counter dropping from 5 to 4; flagged free text returns an error with the counter unchanged. Exhaust five runs and confirm the disabled state names the 5-run limit and earlier cards remain. Cite nfr_per_app_run_limits_are_visible_and_enforced__and_messages_always_tell_app_level_limits_from_shared_caps_, nfr_streaming_progress_such_as_live_status_and_trace_entries_appears_as_steps_complete_ and nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_.

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_first_visit_is_fast_with_no_cold_start_delay__including_the_embedding_explorer_`: First visit is fast with no cold-start delay, including the embedding explorer. — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_`: Total model, search and embedding spend stays within shared hourly and daily caps. — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_app_run_limits_are_visible_and_enforced__and_messages_always_tell_app_level_limits_from_shared_caps_`: Per-app run limits are visible and enforced, and messages always tell app-level limits from shared caps. — delivered by allowance_holds, browser_local_storage, usage_limits
- `nfr_streaming_progress_such_as_live_status_and_trace_entries_appears_as_steps_complete_`: Streaming progress such as live status and trace entries appears as steps complete. — delivered by @microsoft/fetch-event-source, agent_loop_runtime, sse-starlette, tls_termination_and_static_serving
- `nfr_visitor_facing_history_and_statistics_remain_available_over_time_`: Visitor-facing history and statistics remain available over time. — delivered by primary_store, router_agreement_records, router_latency_observations
- `nfr_failures_are_always_shown_candidly_and_never_replaced_with_invented_results_`: Failures are always shown candidly and never replaced with invented results. — delivered by OpenRouter free models (via LiteLLM and PydanticAI) [single_call], react_runs


## References

- [sse-starlette](https://github.com/sysid/sse-starlette)
- [Server-Sent Events (WHATWG HTML Living Standard, section 9.2)](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [@microsoft/fetch-event-source](https://github.com/Azure/fetch-event-source)
- [OpenAI Moderation API guide](https://platform.openai.com/docs/guides/moderation)
