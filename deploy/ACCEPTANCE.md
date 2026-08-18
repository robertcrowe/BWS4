[Built with Spec4 AI](https://spec4.ai)

# Phase 5 acceptance record — behaviour preservation at https://bwtemp.spec4.ai

This is the written acceptance record for the v8 Render → VPS migration,
produced 2026-08-17/18 against the staging origin `https://bwtemp.spec4.ai`
with Render still live at `https://bw.spec4.ai` for side-by-side comparison.
It is the gate that must show no open FAIL before the Phase 6 DNS cutover.

## Constraints that shape this pass — read first

1. **Nothing here is mechanically enforced.** The ratified stack defers
   Playwright; no automated browser suite exists. Every "Observed" line below
   is manual observation in a real browser, corroborated where possible by
   curl, the systemd journal on the VPS, and SQL against the Neon store.
2. **A green test suite proves nothing about live providers.** pyproject.toml
   sets `addopts = "-m 'not live'"`, deselecting every test that reaches a real
   model provider or real Exa. The gates below ran green AND say nothing about
   live provider behaviour; the manual pass is doing the real work.
3. **Both hosts share one Neon database, therefore one set of usage caps.**
   Every run in this pass spends free-tier model and Exa allowance that live
   Render visitors also draw from. The pass was planned as the minimum number
   of runs that proves each behaviour — one run per app, with a single run
   doing double duty as both UI evidence and journal/DB evidence — and the
   allowance state was checked before starting so the pass did not begin near
   a cap boundary.

## Spec-vs-code notes (recorded, not silently adjusted)

- The phase spec says "all ten example apps"; the roster source of truth
  (`frontend/src/data/example-apps.ts`) defines **nine** live apps and no
  coming-soon entries. This record verifies nine apps plus the landing page.
- The phase spec asks for "the per-UTC-hour and per-UTC-day windows". No
  per-UTC-day window exists in code: migration
  `0009_usage_limit_hourly_window.py` replaced the v5-era daily window with an
  hourly one. The only window in `usage_limits`/`allowance_holds` is the UTC
  hour. The configured hourly caps and the documented worst-case daily
  ceilings are recorded in § Shared usage caps.
- The phase spec says "all four server-sent-event streams"; there are **five**
  SSE handlers across the four streaming apps, because the orchestrated app
  streams `/api/orchestrated/run` (delegation) and
  `/api/orchestrated/dispatch` (specialist fan-out) separately. Both were
  verified; progressive specialist columns are carried by `/dispatch`.

## Quality gates (developer-run; Phase 1 baseline comparison)

| Gate | Command | Phase 1 baseline | This pass | Verdict |
|---|---|---|---|---|
| Backend tests | `uv run pytest` | 1815 passed / 21 skipped / 5 deselected | **1815 passed, 21 skipped, 5 deselected in 67.2 s** — identical | PASS |
| Python lint | `uv run ruff check .` | clean | **All checks passed!** | PASS |
| Type check | `uv run mypy backend` | clean, 202 files | **Success: no issues found in 202 source files** | PASS |
| Frontend tests | `npm run test` (frontend/) | green | **29 files, 420 tests, all passed** (vitest 4.1.10, 32.7 s) | PASS |

Caveats recorded per the phase spec: `[tool.ruff] extend-exclude` and mypy's
scoping exempt pre-v5/pre-v6 paths file by file, so a clean run does not mean
every module was linted or type-checked; and the pytest suite runs entirely on
recorded fixtures (see constraint 2).

## Allowance state before the pass

Observed (Neon snapshot via staged script, 2026-08-17 ~22:40 UTC):
`usage_limits` current rows — generation used 18 of cap 100 (window
2026-08-17 18:00 UTC, i.e. the Phase-4 verification runs; the window rolls to
zero on the next reservation), search 2/30 (same stale window), planning 1/8
and representation 0/50 (older windows). Effectively the full hourly allowance
was available at pass start. `allowance_holds` (24 h): 3 redeemed holds
totalling 32 units, none reserved. Ten stale `reserved` holds exist from
2026-08-05…08-13 — all pre-migration (Render-era) debris that predates the
hold-settlement fix; none belong to VPS traffic, and holds cannot outlive
their window, so they are dead rows, not claimed budget.

## Phase-4 open flag: ReAct `budget_exhausted`/`malformed_step` diagnosis

Both Phase 4 verification runs (presets p1, p2) ended `budget_exhausted` with
reason `malformed_step` after cycle 1. `AgentLaneError` deliberately collapses
"every model in the chain failed" and "output would not validate" into one
exception, so full chain rot presents as `malformed_step`.

Observed (journal, 2026-08-17 20:37–20:39 CEST, runs `f0b410d8…` p1 and
`8c2d7a71…` p2): the failures were **not** chain exhaustion. Zero
`models_benched` / `model_rate_limited` / `chain_head_not_serving` events
exist in the journal. The actual per-run sequence, identical in both runs:

- Cycle 1 succeeded (search issued, 5 results observed). Both fallbacks fired
  first: `groq/openai/gpt-oss-120b` → HTTP **400**, then
  `groq/llama-3.3-70b-versatile` → HTTP **404** on every single call in the
  window — that slug has been retired by the provider (genuine, host-independent
  slug rot for one chain entry).
- Cycle 2 died with `agent_step_hit_request_limit` (`limit: 1`) →
  `react_cycle_request_limit` → `StepRequestLimitExceeded` → `MalformedStep`:
  the model that finally served returned output that failed validation, and the
  per-step request limit of 1 blocked the retry. The loop then correctly ran
  hop annotation, settled the hold (`reserved 10, spent 3, refunded 7`,
  `react_run_settled`), and ended in the honest `budget_exhausted` card.
- The `groq/openai/gpt-oss-*` 400s are request-shape dependent (the same slug
  served other calls successfully in the same window), i.e. provider-side model
  behaviour, not host configuration.

Disposition (agreed before the pass): **provider problem, recorded, not a
migration FAIL.** Nothing in the failure path involves the edge, the process
model, or the environment; the run's own quota accounting and candid terminal
card behaved exactly as specified. Follow-up work after Phase 5, outside this
phase's no-app-code constraint: refresh the free-model chains
(`discover_models`), removing the 404 slug.

---

# Landing page

Checks: every existing app appears exactly once in the roster; no entry points
at a non-existent app; Spec4 provenance statement visible without scrolling
past the introduction; header navigation lists the same set; both roster and
nav derive from the single shared directory (`frontend/src/data/example-apps.ts`,
consumed by `LandingScreen.tsx` and `NavMenu.tsx`, so listing and reality
cannot diverge); every route resolves from both roster and nav; direct
deep-link reload resolves through Caddy's SPA history fallback.

Observed (automated, curl against https://bwtemp.spec4.ai): all ten paths
(`/` plus the nine app routes `/embeddings /single-call /rag /tool-use
/chained-calls /planning /orchestrated /collab /react`) return HTTP 200 with
the SPA index document — the Caddy history fallback resolves every deep link
directly. The served landing chunk contains the provenance heading "Built with
Spec4 (BWS4)" and the introduction sentence "Every example below — including
this landing page — was built using Spec4…" ahead of the Example App Directory
section. Single-source derivation confirmed in code: the roster and NavMenu
both map over `exampleApps` from `frontend/src/data/example-apps.ts` (nine
entries, all `status: 'live'`).

Observed (browser): operator confirmed the roster shows the nine apps exactly
once with no dead entries, the provenance statement is visible without
scrolling, the header navigation lists the same set, and click-through into
the apps works (after the edge caching fix below).

Verdict: PASS

## Edge caching / stale-bundle finding (host configuration, found by this pass)

**FINDING (RESOLVED):** clicking into any example app failed in a real browser
with "Failed to fetch dynamically imported module" for a chunk hash no longer
on disk. Two edge defects combined, both absent on Render: (1) Caddy sent no
`Cache-Control` headers at all, so browsers applied heuristic freshness to
index.html and kept serving a pre-deploy entry chunk long after a redeploy —
Render sends `public, max-age=0` (revalidate every use); (2) the SPA
history fallback also applied to `/assets/*`, so a missing chunk returned
**200 with index.html as its body** instead of the 404 Render returns, turning
a recoverable miss into a module-MIME failure. Neither is visible to curl
checks against current URLs — it required a real browser holding a stale
index.html, which is exactly why this pass re-verifies through a browser.

Fix (host configuration, `deploy/Caddyfile`): a dedicated `handle /assets/*`
block with `Cache-Control: public, max-age=31536000, immutable` (filenames
are content-hashed) and **no** index fallback, so missing chunks 404; the SPA
shell block now sends `Cache-Control: no-cache`, so index.html revalidates
against its etag on every use — matching Render's max-age=0 revalidation
semantics. Verified after reload: headers present, stale chunk URL returns
404, fresh navigation works.

Observed after the fix: `/` serves `Cache-Control: no-cache`, `/assets/*`
serve `public, max-age=31536000, immutable`, the stale chunk URL returns 404,
and the operator's browser navigates into every app normally after one hard
reload (the last stale copy any visitor will ever need to shed by hand).

Verdict: PASS

# Embeddings example app

Checks: map renders promptly on first arrival after a quiet period (warm
boot-time projection — the migration's most visible improvement); same custom
text submitted twice lands identically; visitor point rendered in a distinct
colour against the curated clusters; educational overview present and
unchanged.

Observed (automated): `GET /api/embeddings/presets` answered in 0.23 s warm
with the 24 curated points — no on-demand build. **FINDING (host
configuration, open): `POST /api/embeddings/place` with custom text returns
503 `moderation_unavailable`** — the free-form-text moderation gate fails
closed. The journal shows `moderation_failed_closed` with `HTTPStatusError`:
the OpenAI moderation endpoint was reached and returned an error status. The
identical request against Render's API (`https://bws4.onrender.com`) returns
200 with a placed point, so this is a VPS-side configuration defect —
most plausibly a wrong or missing `OPENAI_API_KEY` in `/etc/bws4/bws4.env` —
not an application or provider difference. It affects every free-form-text
input on the VPS (embeddings custom text, orchestrated and ReAct custom
questions); preset flows are unaffected because presets bypass moderation.
Per the phase rule this is fixed as host configuration, then re-verified.

**RESOLVED as host configuration:** the operator corrected `OPENAI_API_KEY` in
`/etc/bws4/bws4.env` and restarted `bws4-api`. A staged probe of the OpenAI
moderation endpoint with the corrected key returns HTTP 200, and
`POST /api/embeddings/place` now returns 200. Determinism re-verified: the
same custom text submitted twice returned byte-identical placements
(x=0.0931681…, y=0.1054095…), and the coordinates and nearest-neighbour list
agree with Render's response for the identical input to ~7 decimal places
(identical neighbour ordering) — the same model, projection and behaviour on
both hosts.

Observed (browser): map rendered immediately on arrival with no warm-up wait
(boot-time projection: `embeddings_projection_built` in 6.2 s at service
start, hours before); custom text placed with the visitor point distinct from
the curated clusters; overview present. Double-submission determinism is
carried by the API evidence above (byte-identical placements, cross-host
match with Render to ~7 decimal places).

Verdict: PASS

# Tool-use example app

Checks: a search returns ranked findings with title, source reference and
excerpt; the exact issued query is returned verbatim for display, never
paraphrased; unavailability is reported distinctly from an empty result.

Observed: one search through the edge returned 5 ranked findings with title,
source and excerpt, and displayed the issued query verbatim (operator
observation). Journal: `tool_search_succeeded` with `searches: 1,
result_count: 5` — exactly one Exa search spent. The unavailable-vs-empty
distinction is carried by the service contract and fixture suite rather than
live-provoked (no way to make Exa unavailable to order); recorded as
not-live-proven.

Verdict: PASS

# Single-call example app

Checks: same prompt in both modes; Simple returns plain text; Structured shows
both the requested result shape and the returned result; exactly one model
call per submission (journal `generation_completed` count); any schema
non-conformance surfaced verbatim with the mismatch flagged — that candour is
the behaviour the example exists to show and records as PASS.

Observed: Simple mode returned plain text; journal shows exactly one
`generation_completed` and `single_call_completed mode: "plain"` for the
submission (one model call). Structured mode (operator confirmed the
requested result shape and the returned result are both displayed): journal
shows exactly one `generation_completed` and `single_call_completed
mode: "structured", schema: "DemoResult", schema_conforming: true` — one
model call, and the serving model honoured the schema on this run, so the
non-conformance display path was not provoked live (it is covered by the
fixture suite and remains the documented behaviour; a conforming result is
the common case and shows the mode working).

Verdict: PASS

# Chained-calls example app

Checks: both stage roles described before the run; exactly two model calls;
intermediate writer output displayed and visibly feeding the critic; the page
states the two-call limit is a quota-conservation choice for the demo, not a
property of the pattern.

Observed: both stage roles described up front (served by
`GET /api/chained-calls/plan` before the run), intermediate writer output
displayed and feeding the critic, limit wording present (operator
observation). Journal: exactly two `agent_step_completed` events
(`struggling_writer` then `harsh_critic`, both `requests: 1`), and the
post-audit ran: `chained_calls_chain_completed` with `quoted_detail_found:
true, match_ratio: 1.0, references_story: true` — the critic verifiably
engaged with the writer's actual text.

Verdict: PASS

# RAG example app

Checks: preset question shows retrieval as a distinct stage from the answer;
the answer names the passages it relied on; citations audited
(`rag/citations.py`); a deliberately out-of-scope question produces the honest
not-covered outcome rather than an invented answer.

Observed: both behaviours confirmed in one pair of runs. The out-of-scope
free-form question (moderated, then answered) ended `rag_ask_succeeded
status: "unsupported"` with `cited_passages: []` — the app reported the
material does not cover it. The preset question (journal: `text_gate_skipped
reason: "curated_example"` — presets bypass moderation as designed) ended
`status: "grounded"` with `cited_passages: [1, 2]` and
`unresolved_citations: []` — retrieval shown as a distinct stage, the answer
naming its passages, and the citation audit populated (passage ids
`james-webb-space-telescope-1/2/3` retrieved). One generation per question.

Verdict: PASS

# Planning-agent example app

Checks: full plan displays before any step executes; nothing runs until the
advance control is clicked; per-step results appear progressively as each
completes; final itinerary reflects both the research findings and the stated
interests; overview cross-references the ReAct Loop app as the interleaved
counterpart.

Observed: all behaviours confirmed in the browser (plan first, nothing until
advance, per-step progressive arrival in the devtools EventStream view, final
itinerary reflecting interests and findings, ReAct cross-reference present).
Journal: `planning_run_completed` with `steps_planned: 3, steps_executed: 2,
steps_failed: 0`. Note: the run's provider-request count is inflated by the
free-chain fallbacks (the retired `groq/llama-3.3-70b-versatile` 404s on
every attempt before a live slug serves) — visible in the journal as
`model_fallback` warnings, invisible to the visitor beyond slower steps.

Verdict: PASS

# Orchestrated-subagents example app

Checks: delegation names exactly two specialists from the fixed roster of four
with a rationale and a distinct brief each; nothing dispatches until advance;
the two specialist columns update independently; merged answer draws on both;
exactly three model calls (`orchestrated_run_summary`); runs-remaining
indicator decrements by one; messaging distinguishes the per-visit run limit
from the gallery's shared usage cap.

Observed: all behaviours confirmed in the browser (exactly two of four named
with rationale and distinct briefs, nothing dispatched until advance,
independently updating columns on the `/dispatch` stream, merged answer
drawing on both, runs-remaining 3→2). Journal `orchestrated_run_summary`:
pairing `historical`+`practical`, `fit_quality: "strong"`, both specialists
`ok`, dispatched concurrently with **2.8 ms skew** (`dispatch_skew_ms`),
`visitor_facing_calls: 3` — the exactly-three contract — with the 12-unit
hold reserved before delegation and redeemed at dispatch confirmation
(`hold_state: "redeemed"`), and the merge audit fields populated
(1 agreement, 1 complement, 0 contradictions).

Verdict: PASS

# Multi-agent collaboration example app

Checks: each negotiation stage streams as it completes; the three agent
identity cards are inspectable; the private-position reveal unseals only after
the run ends; the award rationale refers explicitly to the priorities set; the
raw message log shows no message addressed from one seller to the other
(opacity enforced by which messages the bus returns, not by prompt
instruction).

Observed: all behaviours confirmed in the browser (stages streamed one at a
time, identity cards inspectable, reveal unsealed only after run end, award
rationale referencing the chosen priorities, message log showing no
seller→seller message). Journal `collab_run_summary` for run
`collab-998574d372064769` (scenario `refurbished_laptops_school`, weighting
`lowest_price`): `outcome: "complete"`, `negotiation_stage_calls: 6`,
`seller_to_seller_messages: 0`, `leak_lint_hits: 0`, `degradation: {}`, both
explanation calls conformant. The award turn needed one in-budget
reconciliation retry (9 total model calls against the 12-unit hold, redeemed
cleanly) — the run's declared negotiation budget of six stage calls held.

Verdict: PASS

## Opacity invariant proven from the store

The code-enforced claim is verified against `peer_messages` directly, not only
the rendered log. Agent ids are `buyer`, `northwind`, `meridian`.

```sql
SELECT count(*) FROM peer_messages
 WHERE sender IN ('northwind', 'meridian')
   AND recipient IN ('northwind', 'meridian');

-- robust form (any non-buyer to non-buyer traffic):
SELECT count(*) FROM peer_messages
 WHERE sender <> 'buyer' AND recipient <> 'buyer';
```

Observed (pre-pass, Neon via staged script): over **all 88 peer_messages rows
ever written** — every negotiation run in the store's history, Render-era and
VPS alike — both queries return **0**: `seller_in_seller_in: 0,
non_buyer_to_non_buyer: 0, total_messages: 88`. To be re-run after this pass's
collab run so the count covers a run performed through the new edge.

Observed (post-pass re-run, covering the run performed through the new edge):
`seller_in_seller_in: 0, non_buyer_to_non_buyer: 0, total_messages: 96`.
This pass's run `collab-998574d372064769` decomposes to a pure star topology —
buyer→meridian 2, buyer→northwind 2, meridian→buyer 2, northwind→buyer 2 —
with zero seller-to-seller rows. The store agrees with the rendered message
log and with `collab_run_summary`'s `seller_to_seller_messages: 0`.

Verdict: PASS

# ReAct loop example app

Checks: trace fills cycle by cycle — thought, exact query issued unaltered,
observation snippets — with the cycle counter advancing visibly; no plan shown
up front; no approval requested mid-run; a later query visibly incorporates a
fact from an earlier observation; run ends in exactly one of the two terminal
cards; runs-remaining reflects the two-run session limit.

Observed: the run (preset p3) showed no up-front plan, requested no mid-run
approval, streamed cycle 1 progressively (thought, exact query, observation
snippets from a real search — journal: `react_observation` with 5 results),
then ended in the **budget-exhausted terminal card** — one of the two
legitimate endings, presented candidly with the partial trace retained.
Journal: cycle 2 died on the known provider-side path (chain fallbacks
`400`/`404`, then `agent_step_hit_request_limit limit: 1` →
`malformed_step`), identical to the Phase-4 signature and to the diagnosis
recorded at the top of this document: provider rot plus a validation failure
on the serving model, not a host or edge difference. The run then completed
its post-run hop annotation, and settled its hold exactly as specified:
`react_run_settled reserved: 10, spent: 3, refunded: 7`. The candid-failure
behaviour this project treats as first-class was therefore observed live, on
the new host, working. What this pass could NOT observe on the VPS — a
multi-cycle run reaching the final-answer card — is blocked by the provider
chain, not the migration, and afflicts both hosts equally since the chain is
code-side and identical; resolution is the deferred post-phase chain refresh.

Verdict: PASS (behaviour-preservation proven for the observed path; healthy
full-loop demonstration deferred to the chain refresh, tracked as follow-up)

# Streaming edge (progressive delivery in a real browser)

Phase 3 proved progressive delivery with curl; this pass re-proves it in a
real browser (devtools network panel, events accumulating over time rather
than one burst at stream close) for all five SSE responses:
`/api/planning/run`, `/api/orchestrated/run`, `/api/orchestrated/dispatch`,
`/api/collab/run`, `/api/react/run` — the path that exercises
`@microsoft/fetch-event-source` through Caddy.

Observed: with the devtools network panel open, events accumulated over time
on all the run requests — planning per-step results, the orchestrated
delegation and then the two independently updating specialist columns on
`/dispatch`, the collab stages one at a time (including through the award
stage's ~50 s of provider fallbacks, during which earlier stages stayed on
screen and keep-alive held the stream), and the ReAct cycle events followed
by its terminal card. No stream delivered in a single burst at close; the
Phase-3 curl result is confirmed under a real browser client.

Verdict: PASS

# Abandoned-run quota protection

Checks: a streaming run abandoned mid-flight (tab closed) is ended by
client-disconnect detection rather than completing against a vanished client
(journal `*_run_abandoned` event), and its allowance hold is refunded.

Observed: a planning run was started, advanced, and the tab closed after the
first step's result. Journal: `planning_run_abandoned` with
`steps_completed: 1` — the disconnect detection cancelled the stream and
ended the run mid-execution; no further step calls appear after the event.
(An earlier attempt where the tab was closed *before* advancing produced no
`/api/planning/run` request at all — incidentally confirming that nothing
spends until the visitor advances.) Planning gates per-run through the
`planning` capability counter rather than an allowance hold; the hold-refund
path was separately proven by the ReAct run's settle
(`reserved 10 / spent 3 / refunded 7`).

Verdict: PASS

# Candid failure behaviour

Checks: at least one failure path presents clearly and actionably; the
session-run-limit message is distinguishable from the shared-usage-cap message
(`SESSION_LIMIT_MESSAGE` vs `SHOWCASE_LIMIT_MESSAGE` in each app's
`runAllowance.ts`); when a limit state is shown, inputs are disabled with a
clear explanation while earlier results remain on screen.

Observed: with the ReAct session allowance set to exhausted (2/2 for the
current UTC window via localStorage — the client-side advisory counter,
exercised without spending runs), the question input and start control were
disabled with a message clearly describing this device/session's two-run
limit, distinct from the shared-gallery-cap wording; earlier results stayed
on screen; removing the record restored the app. Live candid-failure
behaviour was additionally observed twice during the pass without being
provoked: the ReAct budget-exhausted terminal card (partial trace retained,
unresolved part named), and the collab award stage surviving ~50 s of
provider fallbacks with all earlier stages still on screen.

Verdict: PASS

# Shared usage caps unchanged

Code defaults (`backend/app/core/config.py`): generation 50/UTC-hour, storage
75/UTC-hour, search 15/UTC-hour, planning 3 runs/UTC-hour; ReAct cycle budget
8; env-var overrides carry the same upper-cased names. There is no enforced
daily window (see spec-vs-code notes). Per-app session limits: planning 3,
orchestrated 3, ReAct 2 per UTC hour (client-side advisory, localStorage).

Observed (Neon, the live rows both hosts share): the enforced caps are the
**environment-configured** values — generation **100**/UTC-hour, search
**30**/UTC-hour, planning **8**/UTC-hour, representation **50**/UTC-hour —
higher than the code defaults, carried in the environment contract on both
hosts. These are the same physical rows Render's traffic gates against
(single shared database), and VPS traffic through them (Phase-4 runs, window
2026-08-17 18:00 UTC) left every cap value unchanged — the migration altered
no cap and no window. No per-app run limit was tightened or loosened (values
above confirmed in `frontend/src/apps/*/runAllowance.ts`, unchanged).

Observed (closing values, after the full pass): generation cap **100**
(used 10 in the fresh 2026-08-18 00:00 UTC window), search cap **30**
(used 4), planning cap **8** (used 1), representation cap **50** — every cap
identical to the pre-pass snapshot; the windows rolled over on the UTC hour
exactly as designed. All three allowance holds created by this pass
(orchestrated 12, collab 12, ReAct 10) finished `redeemed`; none stuck
`reserved`. Per-app service-log accounting for the pass matches the runs
performed (chained-calls 2 generations, RAG 2 generations + 2
representations, single-call 3 generations, tool-use 1 search, orchestrated
2, planning 11 across three runs including the abandoned one).

Verdict: PASS

Verdict: pending

# Visitor-facing wording parity vs Render (bw.spec4.ai)

Checks: educational overviews, call-cost disclosures and limit notices
spot-checked side by side against the still-live Render origin; automated
comparison of the served bundles' string content between origins.

Observed (automated): both origins' served index.html are identical except the
hashed entry-chunk filename. All 19 JS chunk pairs were downloaded from both
origins and compared after normalising the three intentional build-config
differences (hashed chunk names in import specifiers; the Sentry DSN, present
only in the VPS build; the API base URL — Render bakes
`https://bws4.onrender.com` into every request path, the VPS build uses
same-origin relative URLs). Result: the chunks carrying all visitor-facing
prose — `index` (app directory, pattern summaries), `LandingScreen`,
`LayoutShell`, `PatternSummary`, `Markdown`, plus `CollabScreen` — are
byte-identical after normalisation. The remaining per-screen differences are
minifier artifacts of the API-base fold-in (identifier renames and string
literals split at different apostrophe boundaries — e.g. the same "Could not
reach the backend…" sentence tokenised differently), with no wording change.
Both origins are demonstrably serving a build of the same source revision.

Observed (browser spot-check): operator compared apps side by side on
bw.spec4.ai and bwtemp.spec4.ai — overviews, call-cost disclosures and limit
notices identical, consistent with the automated bundle result above.

Verdict: PASS

Verdict: pending

# Layout, responsiveness, theme

Checks: shared layout shell and navigation across all apps; legible at a
narrow viewport; light/dark toggle persists via localStorage.

Observed: operator confirmed the shared layout shell and navigation across
apps, legibility at a narrow viewport, and the theme toggle persisting across
reload.

Verdict: PASS

# Error tracking (Sentry)

Checks: with SENTRY_DSN and VITE_SENTRY_DSN set, backend and frontend both
report from the new host. (The unset no-op path is evidenced by code review
and the fixture suite, not live-proven in this pass.)

Observed: backend logs `sentry_enabled` at boot (with `environment:
"development"` — the default tag, noted for a possible cosmetic
SENTRY_ENVIRONMENT setting later, not a behaviour difference); the deployed
bundle references the Sentry ingest host (proven in Phase 4); and the Sentry
dashboard shows events arriving from the bwtemp origin.

Verdict: PASS

---

# Overall verdict

**PASS — the migration is behaviour-preserving, and Phase 6 may proceed.**
Every section above carries a PASS with no open FAIL. The two defects the pass
found were both host configuration, both fixed and re-verified during the
pass, and both are precisely the kind of difference this gate exists to catch
before DNS moves:

1. A wrong `OPENAI_API_KEY` in `/etc/bws4/bws4.env` made the moderation gate
   fail closed, breaking every free-form-text input (fixed by the operator;
   probe and endpoint re-verified).
2. The Caddy edge served no Cache-Control headers and let the SPA fallback
   swallow missing `/assets/*` chunks, so any browser holding a pre-deploy
   index.html broke on navigation after a release (fixed in
   `deploy/Caddyfile`; headers and 404 behaviour re-verified).

Constraint audit at close: `git diff --stat` shows only `deploy/Caddyfile`
modified plus this new file — nothing under `backend/app/` or
`frontend/src/`; `render.yaml` is present; bw.spec4.ai still resolves to
Render (216.24.57.x) and bwtemp.spec4.ai to the VPS (159.195.17.63).

Named follow-up work, outside this phase's scope, not blocking Phase 6:

- **Free-model chain refresh** (`discover_models`, then update
  `model_registry.py`): `groq/llama-3.3-70b-versatile` is retired (404 on
  every call) and the `groq/openai/gpt-oss-*` slugs 400 on some request
  shapes, which makes the ReAct loop end at cycle 2 via the `malformed_step`
  path and slows several stages by fallback cascades. Provider-side,
  identical on both hosts, fully documented above.
- Optional cosmetic: set `SENTRY_ENVIRONMENT` on the VPS so backend events
  stop tagging `development`.

## What this pass did NOT prove mechanically

Stated plainly, mirroring the constraints at the top of this document:

- **No browser automation exists.** Playwright is deferred in the ratified
  stack, so every browser observation above is a human observation made on
  2026-08-17/18 and written down — repeatable by following this document, but
  not enforced by any suite.
- **The automated test suites never touched a live provider.** pytest runs
  with `-m 'not live'` (all provider/Exa-reaching tests deselected) and the
  vitest suite is jsdom-only. The green gates prove the code matches its
  fixtures, not that providers behave; the live behaviour evidence is the
  journal and store records quoted throughout this document.
- **Not every failure path was live-provoked.** Schema non-conformance in
  single-call, Exa unavailability, and the Sentry-unset no-op were not
  provocable to order; they rest on the fixture suite and code review, as
  noted in their sections. Provider-failure candour, by contrast, WAS
  observed live (ReAct's budget-exhausted card; collab's award surviving a
  50 s fallback cascade).
- **The ReAct final-answer terminal card was not observed on either host**,
  because the current free-model chain cannot reliably produce a valid
  cycle-2 step. Its counterpart terminal card (budget-exhausted) and the
  run's full accounting were observed working; the healthy full loop awaits
  the chain refresh.
