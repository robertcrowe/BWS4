---
{
  "phase_number": 4,
  "total_phases": 10,
  "phase_title": "Route Classification Call and Decision Rules",
  "phase_summary": "Add the single typed classification call (PydanticAI through agent_runtime, output retries zero) with its versioned prompt, then implement the pure-code decision rules: margin check, torn-between pair from the scores, cost-order tie-break and malformed-decision handling. Everything is tested with a stubbed model; no endpoint is wired yet.",
  "features": [
    {
      "id": "router_example_app",
      "role": "extended",
      "scope_note": "Classification and decision logic as a callable service; the run endpoint and UI arrive in Phase 5."
    }
  ],
  "capabilities": [
    {
      "id": "request_route_classification",
      "role": "introduced",
      "scope_note": "Classification call, typed schema and decision rules; evaluator-rejection fallback and dispatch are wired in later phases."
    }
  ],
  "tech_stack_spec": {
    "dependencies": [
      "pydantic-ai",
      "pydantic",
      "structlog",
      "pytest"
    ],
    "configurations": "No new environment variables. Model slugs come from services/model_registry.py via agent_runtime.run_typed_step (model family: Llama); never pin a model id."
  },
  "instructions": [
    "Create backend/app/router/prompts/route_v1.md (versioned, with a version header) and a loader using the existing services/prompt_loader.py load_prompt. The prompt contains the route-description block imported from the Phase 3 single source, tells the model to score each route 0..1 as a relative ranking, produces a one-line rationale, and sets expression only when the deterministic route is proposed. The request is delimited as untrusted data and never executed. Include a short example of the evaluator's accepted grammar.",
    "Define the RoutingDecision Pydantic model alongside the prompt, as the attached specification describes: all four route-id keys required, scores in [0,1], rationale one line, expression null unless the route is deterministic_evaluator. Use the exact route-id constants.",
    "Create backend/app/router/classifier.py that makes exactly one call through services/agent_runtime.run_typed_step with the RoutingDecision output type and zero output retries (override the one-retry figure in the Agentifier spec; the stack spec is authoritative). Do not add a new model call path or bypass the registry.",
    "Measure the classification call's elapsed time and record the serving model slug for later cost-strip and telemetry use.",
    "Create backend/app/router/decision.py with pure functions: (a) compute argmax route from the scores (the model's 'route' field is advisory and the scores win); (b) low-confidence when the top two scores are within DECISION_MARGIN; (c) the torn-between pair taken from the scores, not any runner-up claim; (d) cheaper-of-two chosen via ROUTE_COST_ORDER; (e) agreement statement for presets: 'agreed', 'misrouted' when a different route was chosen, 'declined' when the router did not choose (low-confidence); free text gets none.",
    "Implement malformed-decision handling per the stack spec's router_malformed_decision_rule: a schema-invalid or failed classification is not retried, dispatches to single_call with a plain card note, inside the routed-answer ending, with no agreement row. It is NOT 'declined'. Represent this as a distinct typed outcome so later phases cannot confuse it with low-confidence.",
    "Emit structlog events (and Sentry spans via the existing wiring) for schema failure, argmax route, margin value and classifier latency. Create no new table.",
    "Tests in backend/tests/router/ using a stubbed run_typed_step: valid decision; each malformed variant (missing score, unknown route, expression on non-deterministic route); margin boundaries (exactly at margin, just under, well over); exact ties broken by cost order; torn pair taken from scores even when the model's 'route' disagrees; agreement statements for agreed, misrouted and declined; malformed decision produces the dedicated outcome with no agreement; assert exactly one model call per classification and zero retries."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "Free-tier chain models may return schema-invalid output; the spec documents conflicting retry counts; the AI coder may trust the model's 'route' field over the scores; confusing 'declined' with 'malformed'.",
    "mitigation_strategy": "Follow the stack: zero retries and a dedicated malformed outcome; decision.py derives everything from scores and ignores the route field except for logging mismatches; separate typed outcomes with tests for each; keep all calls through agent_runtime so the allowance gate cannot be bypassed."
  },
  "verification": "Run `uv run pytest backend/tests/router`, `uv run ruff check .`, `uv run mypy`; all pass, including tests asserting one call and zero retries. Optionally run one live smoke call (`-m live`) classifying preset 1 and confirm a valid four-score object. Cite nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_ (all calls via the shared registry and runtime, no retry spend).",
  "references": [
    {
      "standard": "PydanticAI - Output (structured/typed output)",
      "url": "https://ai.pydantic.dev/output/"
    },
    {
      "standard": "Spec4 pattern library - single_call tier",
      "url": "https://github.com/robertcrowe/Spec4/blob/dev/src/spec4/agentifier/patterns/tiers/03_single_call.md"
    },
    {
      "standard": "Spec4 pattern library - structured_outputs mechanism",
      "url": "https://github.com/robertcrowe/Spec4/blob/dev/src/spec4/agentifier/patterns/mechanisms/structured_outputs.md"
    }
  ]
}
---

# Phase 4 of 10: Route Classification Call and Decision Rules

Add the single typed classification call (PydanticAI through agent_runtime, output retries zero) with its versioned prompt, then implement the pure-code decision rules: margin check, torn-between pair from the scores, cost-order tie-break and malformed-decision handling. Everything is tested with a stubbed model; no endpoint is wired yet.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Router_Example_App — product feature — extended in this phase

*Scope for this phase: Classification and decision logic as a callable service; the run endpoint and UI arrive in Phase 5.*

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

### request_route_classification — AI capability — introduced in this phase

*Scope for this phase: Classification call, typed schema and decision rules; evaluator-rejection fallback and dispatch are wired in later phases.*

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

- pydantic-ai
- pydantic
- structlog
- pytest

**Configurations:** No new environment variables. Model slugs come from services/model_registry.py via agent_runtime.run_typed_step (model family: Llama); never pin a model id.

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

1. Create backend/app/router/prompts/route_v1.md (versioned, with a version header) and a loader using the existing services/prompt_loader.py load_prompt. The prompt contains the route-description block imported from the Phase 3 single source, tells the model to score each route 0..1 as a relative ranking, produces a one-line rationale, and sets expression only when the deterministic route is proposed. The request is delimited as untrusted data and never executed. Include a short example of the evaluator's accepted grammar.
2. Define the RoutingDecision Pydantic model alongside the prompt, as the attached specification describes: all four route-id keys required, scores in [0,1], rationale one line, expression null unless the route is deterministic_evaluator. Use the exact route-id constants.
3. Create backend/app/router/classifier.py that makes exactly one call through services/agent_runtime.run_typed_step with the RoutingDecision output type and zero output retries (override the one-retry figure in the Agentifier spec; the stack spec is authoritative). Do not add a new model call path or bypass the registry.
4. Measure the classification call's elapsed time and record the serving model slug for later cost-strip and telemetry use.
5. Create backend/app/router/decision.py with pure functions: (a) compute argmax route from the scores (the model's 'route' field is advisory and the scores win); (b) low-confidence when the top two scores are within DECISION_MARGIN; (c) the torn-between pair taken from the scores, not any runner-up claim; (d) cheaper-of-two chosen via ROUTE_COST_ORDER; (e) agreement statement for presets: 'agreed', 'misrouted' when a different route was chosen, 'declined' when the router did not choose (low-confidence); free text gets none.
6. Implement malformed-decision handling per the stack spec's router_malformed_decision_rule: a schema-invalid or failed classification is not retried, dispatches to single_call with a plain card note, inside the routed-answer ending, with no agreement row. It is NOT 'declined'. Represent this as a distinct typed outcome so later phases cannot confuse it with low-confidence.
7. Emit structlog events (and Sentry spans via the existing wiring) for schema failure, argmax route, margin value and classifier latency. Create no new table.
8. Tests in backend/tests/router/ using a stubbed run_typed_step: valid decision; each malformed variant (missing score, unknown route, expression on non-deterministic route); margin boundaries (exactly at margin, just under, well over); exact ties broken by cost order; torn pair taken from scores even when the model's 'route' disagrees; agreement statements for agreed, misrouted and declined; malformed decision produces the dedicated outcome with no agreement; assert exactly one model call per classification and zero retries.

## Risk Assessment

**Potential bottlenecks:**

Free-tier chain models may return schema-invalid output; the spec documents conflicting retry counts; the AI coder may trust the model's 'route' field over the scores; confusing 'declined' with 'malformed'.

**Mitigation strategy:**

Follow the stack: zero retries and a dedicated malformed outcome; decision.py derives everything from scores and ignores the route field except for logging mismatches; separate typed outcomes with tests for each; keep all calls through agent_runtime so the allowance gate cannot be bypassed.

## Verification

Run `uv run pytest backend/tests/router`, `uv run ruff check .`, `uv run mypy`; all pass, including tests asserting one call and zero retries. Optionally run one live smoke call (`-m live`) classifying preset 1 and confirm a valid four-score object. Cite nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_ (all calls via the shared registry and runtime, no retry spend).

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_first_visit_is_fast_with_no_cold_start_delay__including_the_embedding_explorer_`: First visit is fast with no cold-start delay, including the embedding explorer. — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_`: Total model, search and embedding spend stays within shared hourly and daily caps. — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_app_run_limits_are_visible_and_enforced__and_messages_always_tell_app_level_limits_from_shared_caps_`: Per-app run limits are visible and enforced, and messages always tell app-level limits from shared caps. — delivered by allowance_holds, browser_local_storage, usage_limits
- `nfr_streaming_progress_such_as_live_status_and_trace_entries_appears_as_steps_complete_`: Streaming progress such as live status and trace entries appears as steps complete. — delivered by @microsoft/fetch-event-source, agent_loop_runtime, sse-starlette, tls_termination_and_static_serving
- `nfr_visitor_facing_history_and_statistics_remain_available_over_time_`: Visitor-facing history and statistics remain available over time. — delivered by primary_store, router_agreement_records, router_latency_observations
- `nfr_failures_are_always_shown_candidly_and_never_replaced_with_invented_results_`: Failures are always shown candidly and never replaced with invented results. — delivered by OpenRouter free models (via LiteLLM and PydanticAI) [single_call], react_runs


## References

- [PydanticAI - Output (structured/typed output)](https://ai.pydantic.dev/output/)
- [Spec4 pattern library - single_call tier](https://github.com/robertcrowe/Spec4/blob/dev/src/spec4/agentifier/patterns/tiers/03_single_call.md)
- [Spec4 pattern library - structured_outputs mechanism](https://github.com/robertcrowe/Spec4/blob/dev/src/spec4/agentifier/patterns/mechanisms/structured_outputs.md)
