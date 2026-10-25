---
{
  "phase_number": 7,
  "total_phases": 10,
  "phase_title": "Retrieval and Search-plus-Generation Dispatch",
  "phase_summary": "Complete the four routes: dispatch to the RAG example's existing retriever, and to the shared Exa web search followed by exactly one grounded generation call. Search answers cite snippet indices, and empty or failed searches are reported candidly with no invented sources.",
  "features": [
    {
      "id": "router_example_app",
      "role": "extended",
      "scope_note": "Retrieval and search-generation dispatch plus their answer views; histories, cost strip and re-run come later."
    }
  ],
  "capabilities": [
    {
      "id": "router_example_app",
      "role": "extended",
      "scope_note": "Dispatch to the retrieval and search_generation routes, completing all four."
    },
    {
      "id": "search_route_answer_generation",
      "role": "introduced",
      "scope_note": "One grounded generation call from Exa snippets with validated citation indices; no tool loop."
    }
  ],
  "tech_stack_spec": {
    "dependencies": [
      "httpx",
      "litellm",
      "pydantic-ai",
      "pgvector",
      "sentence-transformers",
      "react-markdown",
      "pytest",
      "vitest"
    ],
    "configurations": "No new environment variables. Uses EXA_API_KEY and SEARCH_HOURLY_LIMIT via services/web_search.py, and the existing embedding model and dataset_embeddings table via the RAG retriever."
  },
  "instructions": [
    "Retrieval route: call the RAG example's existing retriever through its existing service entry point, unmodified, then show the retrieved passages (document title, excerpt, similarity). Decide from the existing RAG service whether it already composes an answer with one generation call; reuse its existing answering entry point if so and count its model calls toward the run's unit ceiling. If it would exceed the 2-unit ceiling, show passages only and say so. Record retrievals count for the cost strip. Report 'dataset does not cover this' candidly when nothing is relevant, as the RAG app does.",
    "Search route: call services/web_search.py directly in-process (no MCP, no new client, no tool registration), one search per run, passing the visitor's request. Trim to the top 5 snippets, each truncated to about 600 characters, with title, URL, excerpt and published date when available. Display the exact query used.",
    "Create backend/app/router/prompts/search_answer_v1.md (versioned) and call generation once through the shared registry (litellm lane, no hard-coded slug). Inject the current server date and the delimited snippets, instruct the model to treat snippet text as untrusted, answer in 2-5 sentences using only the snippets, cite [n] indices, say plainly when snippets lack the answer or conflict, and never output URLs not in the list. Cap max_tokens.",
    "Post-check that every cited index exists in the supplied list and strip or flag invalid ones. If search returns zero snippets, skip the generation call and return a fixed 'no usable results found' result, refunding the unspent unit. If search fails, return a clearly labelled search-unavailable result with no fabricated sources and no silent re-route. If generation fails, return the fixed 'search ran but an answer could not be composed' message with the raw snippet titles and links.",
    "Record per-run measured time for the search route (the later latency history uses it) and search and generation counts.",
    "Frontend: add Router-local wrappers importing the existing Tool Use and RAG presentational components unchanged where they fit, with payloads as props, each labelled with its path. Show the snippet list beside the answer so bracket indices resolve. Render model text through the Markdown component. No existing app file is edited. Reference .spec4/v9/design/mock.html.",
    "Tests: retrieval dispatch calls the retriever unmodified (patch to assert); search route makes exactly one search and one generation call; invalid citation indices are handled; empty and failed search paths with no generation call and correct refunds; snippet injection text is delimited and not followed (prompt-construction test); total never exceeds 2 units plus one search; preset 3, 4 and 5 end to end with stubs."
  ],
  "risk_assessment": {
    "potential_bottlenecks": "The existing RAG entry point may do its own generation and consume extra units; the Exa wrapper's response shape and quota failures; model hallucination of numbers or invented citations; leaking units on empty search.",
    "mitigation_strategy": "Inspect the real entry points before coding and wrap in backend/app/router/; hard cap on snippets and tokens; post-validation of citations; refund tests for every early-exit path; fixed fallback messages instead of invented text."
  },
  "verification": "Run `uv run pytest backend/tests/router`, `uv run ruff check .`, `uv run mypy`, `cd frontend && npx vitest run`, `cd frontend && npm run build`. Manually run preset 3 (retrieved Apollo 11 passages shown), preset 4 and preset 5 (one search, one generation call, answer with [n] citations resolving to the displayed snippets, labelled search path). Simulate an Exa failure and confirm a candid search-unavailable result. Confirm total units never exceed 2 plus one search. Cite nfr_failures_are_always_shown_candidly_and_never_replaced_with_invented_results_ and nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_.",
  "references": [
    {
      "standard": "Exa Search API",
      "url": "https://exa.ai/docs/reference/search-api-guide"
    },
    {
      "standard": "LiteLLM",
      "url": "https://docs.litellm.ai/docs"
    },
    {
      "standard": "pgvector",
      "url": "https://github.com/pgvector/pgvector"
    },
    {
      "standard": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (Lewis et al.)",
      "url": "https://arxiv.org/abs/2005.11401"
    }
  ]
}
---

# Phase 7 of 10: Retrieval and Search-plus-Generation Dispatch

Complete the four routes: dispatch to the RAG example's existing retriever, and to the shared Exa web search followed by exactly one grounded generation call. Search answers cite snippet indices, and empty or failed searches are reported candidly with no invented sources.

## Feature Specifications

These specifications are authoritative for this phase. Implement to them; the instructions below tell you how and in what order.

### Router_Example_App — product feature — extended in this phase

*Scope for this phase: Retrieval and search-generation dispatch plus their answer views; histories, cost strip and re-run come later.*

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

### router_example_app — AI capability — extended in this phase

*Scope for this phase: Dispatch to the retrieval and search_generation routes, completing all four.*

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

### search_route_answer_generation — AI capability — introduced in this phase

*Scope for this phase: One grounded generation call from Exa snippets with validated citation indices; no tool loop.*

Serves product feature(s): `router_example_app` (specified above).

- Tier: `single_call`
- Scope: `sub_feature`
- Phase priority: `mvp`
- Composed under: `router_example_app`
- Requires: `request_route_classification`
- Tier rationale: This sub-feature takes a request plus already-fetched web search snippets and writes an answer from them. A deterministic implementation cannot do this, because the input is unstructured natural-language snippets and the output is a composed written answer, which no template or lookup produces. Once the search has run, the work is a single bounded transform from input to output. The snippets are passed directly in the prompt (a few thousand tokens at most), so there is no retrieval step against a corpus and no need for rag. The search call itself is deterministic plumbing, an Exa query by request text, and the route decision belongs to the separate request_route_classification feature. There is no stated sequential LLM-to-LLM dependency, and no tool-calling loop is described inside this feature, so chained_calls and tool_agent are not warranted. One LLM call through the existing litellm registry covers it.
- Next-cheaper tier would lose: Embeddings or deterministic logic could only rank or pass through snippets and cannot generate a written answer from unstructured search text, which is the core requirement.
- Borderline — seams to watch: If the app lets the model decide when and what to search inside this step, the feature becomes tool_agent.; If answers must carry verified citations through a separate audit pass, that is a stated validation or reflection mechanism and stays at single_call, but watch for an actual second LLM step.

Compose a short, written, source-grounded answer to a time-variable factual request (e.g. current prices, recent events) from web search snippets, serving as the search route of the Router_Example_App.

**Invocation**

- Trigger: The router's deterministic dispatcher selects the search route; backend code first calls the existing Exa web search service (backend/app/services/web_search.py), then invokes this call with the request and returned snippets.
- Mode: synchronous

**Inputs**

- `request` (string, required) — The visitor's original request text, passed unchanged from the router input.
- `snippets` (list[object], required) — Search result snippets from Exa, each with index, title, url, snippet text and published date if available. Capped (e.g. top 5, each truncated to ~600 chars).
- `current_date` (string (ISO date), required) — Server date injected so the model can reason about recency of snippets.

**Outputs**

- Primary: A concise written answer (2-5 sentences) composed only from the snippets, with bracketed source indices such as [1], and a plain statement when the snippets do not contain the answer or conflict.
- Format: Plain text
- Schema notes: Shown on screen labelled with the search path; no parsed schema. Citation indices refer to the snippet list shown alongside. Answers must not include facts absent from the snippets.

**Decision authority:** autonomous

**Success criteria**

- Answer is produced and returned for at least 98% of search-route runs that reach this call, within the run's 1 model-call unit plus one search budget.
- At least 95% of golden-set answers are judged grounded: every factual claim is supported by a supplied snippet.
- At least 90% of answers on golden-set questions contain the key expected fact when the snippets contain it.
- When snippets lack the answer, at least 90% of answers say so rather than guessing.
- 100% of cited indices exist in the supplied snippet list.
- Uses only the shared model registry (litellm fallback chain); no hard-coded model slug or cost figure.

**Failure modes**

- Model states facts not present in snippets (hallucination), especially numeric values (likelihood: medium) — mitigation: Strict system prompt: use only snippets, quote numbers as written, state the date of the source; post-check that cited indices are valid; golden-set grounding evals.
- Snippets are stale or conflicting for a time-variable question (likelihood: medium) — mitigation: Pass published dates and current_date; instruct the model to mention the source date and flag conflicts instead of choosing silently.
- Search returns zero or irrelevant snippets (likelihood: medium) — mitigation: Skip the model call when there are no snippets and return a fixed 'no usable results found' message; otherwise the prompt tells the model to say the answer is not in the results.
- All free models in fallback chain fail or are rate limited (likelihood: medium) — mitigation: Rely on the registry's ordered fallback chain; on exhaustion return the fixed unavailable message and release reserved units per run rules.
- Prompt injection in snippet text (likelihood: low) — mitigation: Wrap snippets in delimited data blocks, instruct the model to treat them as untrusted content, never follow instructions in them, and never output links not in the list.
- Over-long or off-format answer (likelihood: low) — mitigation: max_tokens cap and length instruction; truncate gracefully at sentence boundary.

**Escalation on failure:** On model failure or empty output, return a fixed message ('The search ran but an answer could not be composed') with the raw snippet titles and links so the visitor still sees results; log the failure. No human review; the run still ends as a routed answer per the app's ending rules.

**Privacy & safety**

- Visitor request text is sent to Exa and the model provider; do not log beyond the existing run records and add no user identifiers.
- Request is assumed already screened by the existing moderation approach where the app applies it; the prompt refuses to produce harmful content.
- Treat snippet content as untrusted; no execution of any model text and no output of URLs not in the supplied list.
- Answers are informational; instruct the model not to present time-variable facts as current beyond the source date.

**References**

- backend/app/services/web_search.py (Exa tool wrapper, reused) (https://pydantic.dev/docs/ai/harness/exa-search)
- backend/app/services/model_registry.py (litellm fallback chain, reused) (https://docs.litellm.ai/docs/proxy/reliability)
- https://docs.litellm.ai/docs/routing
- https://exa.ai/docs

**Cross-cutting decisions (project-wide):**

- **Tool protocol strategy:** Decide per capability. (1) Exa web search, used by search_route_answer_generation: it already has multiple consumers (tool-use example, planning agent, ReAct loop) in backend/app/services/web_search.py. Reuse the existing wrapper and call it directly from the search route; do not reimplement or add a new client. If Exa's official MCP server is adopted for the router_example_app's MCP demonstration, consume it rather than building one. Wrapping the existing web_search service in a new in-house MCP server is justified only if the MCP lesson in router_example_app needs a second consumer. (2) Route dispatch (classifier output to the single-call, search, or existing-route handler): exactly one consumer in the same codebase, so use a plain deterministic function call or dispatch table, with no MCP. (3) Classification and free-text answering: model calls through the shared litellm registry or pydantic-ai agent runtime, which are direct in-process calls and not tools. (4) OpenAI Moderation: keep the existing direct call and, if the router accepts free-form input, reuse services/moderation.py as is. (5) Embeddings, pgvector and RAG are not needed by these features, so do not add them.
  - Rationale: Applying the mcp pattern's consumption-vs-exposure distinction per capability: consumption means reusing an existing MCP server (for example an Exa MCP server) before writing our own. Exposure means building an MCP server only when a capability has multiple consumers. Web search is the only capability with multiple consumers, and it is already centralised behind one Python service, so direct reuse is cheapest. Routing and dispatch have a single in-codebase consumer, so MCP would add protocol overhead with no benefit. The router_example_app lists both direct and mcp protocols; keep MCP confined to the single capability (search) where it demonstrates something, and keep everything else direct.

## Tech Stack

**Dependencies:**

- httpx
- litellm
- pydantic-ai
- pgvector
- sentence-transformers
- react-markdown
- pytest
- vitest

**Configurations:** No new environment variables. Uses EXA_API_KEY and SEARCH_HOURLY_LIMIT via services/web_search.py, and the existing embedding model and dataset_embeddings table via the RAG retriever.

**Approved stack for this phase's declared work** (deterministic, from the stack spec):

- Groq (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`, `search_route_answer_generation`
- OpenRouter free models (via LiteLLM and PydanticAI) [single_call] (providers) — serves `router_example_app`, `search_route_answer_generation`
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

1. Retrieval route: call the RAG example's existing retriever through its existing service entry point, unmodified, then show the retrieved passages (document title, excerpt, similarity). Decide from the existing RAG service whether it already composes an answer with one generation call; reuse its existing answering entry point if so and count its model calls toward the run's unit ceiling. If it would exceed the 2-unit ceiling, show passages only and say so. Record retrievals count for the cost strip. Report 'dataset does not cover this' candidly when nothing is relevant, as the RAG app does.
2. Search route: call services/web_search.py directly in-process (no MCP, no new client, no tool registration), one search per run, passing the visitor's request. Trim to the top 5 snippets, each truncated to about 600 characters, with title, URL, excerpt and published date when available. Display the exact query used.
3. Create backend/app/router/prompts/search_answer_v1.md (versioned) and call generation once through the shared registry (litellm lane, no hard-coded slug). Inject the current server date and the delimited snippets, instruct the model to treat snippet text as untrusted, answer in 2-5 sentences using only the snippets, cite [n] indices, say plainly when snippets lack the answer or conflict, and never output URLs not in the list. Cap max_tokens.
4. Post-check that every cited index exists in the supplied list and strip or flag invalid ones. If search returns zero snippets, skip the generation call and return a fixed 'no usable results found' result, refunding the unspent unit. If search fails, return a clearly labelled search-unavailable result with no fabricated sources and no silent re-route. If generation fails, return the fixed 'search ran but an answer could not be composed' message with the raw snippet titles and links.
5. Record per-run measured time for the search route (the later latency history uses it) and search and generation counts.
6. Frontend: add Router-local wrappers importing the existing Tool Use and RAG presentational components unchanged where they fit, with payloads as props, each labelled with its path. Show the snippet list beside the answer so bracket indices resolve. Render model text through the Markdown component. No existing app file is edited. Reference .spec4/v9/design/mock.html.
7. Tests: retrieval dispatch calls the retriever unmodified (patch to assert); search route makes exactly one search and one generation call; invalid citation indices are handled; empty and failed search paths with no generation call and correct refunds; snippet injection text is delimited and not followed (prompt-construction test); total never exceeds 2 units plus one search; preset 3, 4 and 5 end to end with stubs.

## Risk Assessment

**Potential bottlenecks:**

The existing RAG entry point may do its own generation and consume extra units; the Exa wrapper's response shape and quota failures; model hallucination of numbers or invented citations; leaking units on empty search.

**Mitigation strategy:**

Inspect the real entry points before coding and wrap in backend/app/router/; hard cap on snippets and tokens; post-validation of citations; refund tests for every early-exit path; fixed fallback messages instead of invented text.

## Verification

Run `uv run pytest backend/tests/router`, `uv run ruff check .`, `uv run mypy`, `cd frontend && npx vitest run`, `cd frontend && npm run build`. Manually run preset 3 (retrieved Apollo 11 passages shown), preset 4 and preset 5 (one search, one generation call, answer with [n] citations resolving to the displayed snippets, labelled search path). Simulate an Exa failure and confirm a candid search-unavailable result. Confirm total units never exceed 2 plus one search. Cite nfr_failures_are_always_shown_candidly_and_never_replaced_with_invented_results_ and nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_.

**Non-functional acceptance** (deterministic, from the stack spec):

- `nfr_first_visit_is_fast_with_no_cold_start_delay__including_the_embedding_explorer_`: First visit is fast with no cold-start delay, including the embedding explorer. — delivered by embedding_pipeline, embedding_projection_cache, process_supervision, scikit-learn, sentence-transformers
- `nfr_total_model__search_and_embedding_spend_stays_within_shared_hourly_and_daily_caps_`: Total model, search and embedding spend stays within shared hourly and daily caps. — delivered by Groq (via LiteLLM and PydanticAI) [rag], Groq (via LiteLLM and PydanticAI) [single_call], allowance_holds, issued_query_embeddings, usage_limits
- `nfr_per_app_run_limits_are_visible_and_enforced__and_messages_always_tell_app_level_limits_from_shared_caps_`: Per-app run limits are visible and enforced, and messages always tell app-level limits from shared caps. — delivered by allowance_holds, browser_local_storage, usage_limits
- `nfr_streaming_progress_such_as_live_status_and_trace_entries_appears_as_steps_complete_`: Streaming progress such as live status and trace entries appears as steps complete. — delivered by @microsoft/fetch-event-source, agent_loop_runtime, sse-starlette, tls_termination_and_static_serving
- `nfr_visitor_facing_history_and_statistics_remain_available_over_time_`: Visitor-facing history and statistics remain available over time. — delivered by primary_store, router_agreement_records, router_latency_observations
- `nfr_failures_are_always_shown_candidly_and_never_replaced_with_invented_results_`: Failures are always shown candidly and never replaced with invented results. — delivered by OpenRouter free models (via LiteLLM and PydanticAI) [single_call], react_runs


## References

- [Exa Search API](https://exa.ai/docs/reference/search-api-guide)
- [LiteLLM](https://docs.litellm.ai/docs)
- [pgvector](https://github.com/pgvector/pgvector)
- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (Lewis et al.)](https://arxiv.org/abs/2005.11401)
