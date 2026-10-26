# v10 cleanup — review note

Running record for the v10 cleanup. Phases 1–7 appended to it; Phase 8
finalised it (this summary, the results table and the complete flagged list
below, plus the Phase 8 section at the end).

## Summary

v10 is a behaviour-preserving cleanup on top of `b22522b` (v1.1.0). All v10
work is uncommitted in the working tree.

- **Required credentials (Phase 1).** `GROQ_API_KEY` and `OPENAI_API_KEY` are
  required in every environment. Missing or empty means startup fails naming
  the key. There is no placeholder and no opt-out. The test suite now needs
  real keys and keeps providers offline. The `-m live` smoke run stays opt-in.
- **Best-effort Router warm-up (Phases 2–3).** A failed route-description
  warm-up is logged (`router_warmup_failed`) and boot continues.
  `GET /api/router/presets` reports `available: false`, runs are refused with
  `descriptions_not_ready` before any hold, and the page shows "temporarily
  unavailable" with **Retry** (`POST /api/router/retry`). A successful retry
  restores the Router without a restart.
- **Whole-backend gates (Phases 4–5).** Every Ruff exclusion and every mypy
  `ignore_errors` override is gone. Ruff covers the whole repo and mypy runs
  strict over all of `backend/`. 394 Ruff findings and 35 mypy errors were
  fixed by formatting, literal splits and annotation-only changes (AST-checked).
  There are two targeted `noqa: N818`s and one `type: ignore[call-arg]`.
- **Retired-host sweep (Phase 6).** Render references are rewritten to
  describe the VPS, except the statements that record its retirement. The
  lifespan docstring now describes the always-on instance.
- **Unrecorded edits (Phase 7).** All eight `b22522b` edits were reviewed.
  They were kept or flagged; none were reverted. The README was fixed as
  documentation only.
- **Acceptance (Phase 8).** A Router gating check confirmed that Ruff and mypy
  flag Router code, its API file and its tests. Every gate passes. The
  contracts are intact: the route ids, `critique_failed`, startup credential
  failure, and the unavailable/Retry state. No usage cap, run limit or
  response shape changed. The only visitor-facing text changes are the ones
  the spec asked for: the "temporarily unavailable" Router messages and the
  new Router unavailable state.

## Baseline vs final

| Gate | Baseline (`b22522b`) | Final (Phase 8) |
|---|---|---|
| `uv run ruff check .` | passed, with a 45-entry `extend-exclude` + migrations per-file-ignores | All checks passed, 0 exclusions |
| `uv run ruff format --check .` | not in the baseline table; Phase 2 saw it flag `tests/collab/test_deploy_readiness.py` | 353 files already formatted |
| `uv run mypy` | no issues in 234 files, with `ignore_errors` overrides | no issues in 237 files, strict, `files = ["backend"]`, no `ignore_errors` |
| `uv run pytest` | 2115 passed, 21 skipped, 6 deselected | **2140 passed**, 21 skipped, 6 deselected |
| `npm run lint` (oxlint) | not recorded at baseline | 0 errors, 13 pre-existing `only-export-components` warnings in `src/routes.tsx` |
| `npx tsc --noEmit` | not recorded at baseline | exit 0 (checks nothing; see flag 13) — `-p tsconfig.app.json` also exit 0 |
| `npx vitest run` | 38 files, 484 passed | **38 files, 475 passed** |
| `npm run build` | passed, 764 modules | passed, 765 modules |

Count differences are explained by comparing the collected test ids at
baseline (snapshot) with the final tree:

- **pytest +25** (2136 → 2161 collected; deselected stays 6, skipped stays 21):
  - +11 `backend/tests/core/test_required_credentials.py` (new, Phase 1)
  - +11 `backend/tests/router/test_router_availability.py` (new, Phase 2)
  - +2 `backend/tests/router/test_route_descriptions.py` (18 → 20, Phase 2)
  - +1 `backend/tests/router/test_run.py` (17 → 18, Phase 2)

  The Phase 2 section says "12 in the new file, net +1 in
  `test_route_descriptions.py`". The collected ids show 11 and +2. The Phase 2
  total (+14) is the same either way. The other id changes are renames with
  no change in count: five `E501` renames (Phase 4), three
  `test_react_gate_registration.py` renames (Phases 4–5), and two re-pinned
  presets tests in `test_route_descriptions.py` (Phase 2).
- **vitest −9** (484 → 475; files 38 → 38): +7 in the new
  `frontend/tests/router-unavailable.test.tsx` (Phase 3, +1 file). −16 from
  deleting `frontend/tests/planning-untouched.test.ts` (Phase 5, −1 file; 4
  `it`s plus an `it.each` over its path list). That deletion was an explicit
  **owner decision** to retire the v7 planning guard. It is not a regression,
  so this drop is the one accepted exception to "test counts must not drop".
  No other frontend test file changed (`git diff b22522b --stat --
  frontend/tests` lists only the deletion and `routerFixtures.ts`).

## Flagged for owner decision

The complete list for v10. Nothing here was reverted or "fixed". Each item
points back to the phase section with the detail.

**Surfaced real bugs:** none. Neither the Ruff pass (Phase 4) nor the mypy
pass (Phase 5) found a runtime bug.
**Type fixes that required a test change:** none (Phase 5).

### Test changes that re-pin configuration (items 1–2 approved by the owner)

1. **Ruff half (Phase 4):** `backend/tests/react/test_react_gate_registration.py`
   used to assert that ten legacy paths and migration 0013 keep their Ruff
   exemption. It now asserts the opposite: no exclusions.
2. **mypy half (Phase 5):** in the same file, three tests were renamed. They
   now assert strict mypy over `backend` with no `ignore_errors` override.
3. **Five `E501` test renames (Phase 4):** only the names were shortened. No
   body or assertion changed.

### Unrecorded edits (Phase 7)

4. **`.claude/settings.json` lost its `.env` Write denials.** `b22522b`
   removed `Write(**/.env*)` and `Write(**/*.env)`. Only the two `Edit(...)`
   denials remain, so nothing denies creating a `.env` file. The intent is
   unrecorded, and the change runs against the CLAUDE.md invariant.
5. **Navigation label mismatch.** The ReAct app is named `ReAct-Loop Example
   App`, while the Router is named `Router`. `ReAct Loop` and `Router` are only
   `patternTag` values. Changing this is visible to visitors.
6. **Stale test wording (minor).** The `react-loop.test.tsx` test titled
   "is appended last …" now asserts adjacency to collaboration. The
   `collab.test.tsx` comment still points "is last" at `react-loop.test.tsx`.

### Stale visitor text and docs (Phase 6, Phase 8)

7. **Visitor-facing stale text:** in `frontend/src/apps/collab/CollabApp.tsx`
   (~line 65), the `connecting` message said that the backend "sleeps when
   idle on its free tier". **Resolved by the owner after Phase 8:** the
   cold-start clause was removed; the message now reads "Reserving the run's
   budget and composing the request for quotation…".
8. **CLAUDE.md** "Deployment shape" listed the retired staging origin
   `https://bwtemp.spec4.ai`. **Resolved by the owner after Phase 8:** the
   staging part was dropped; the line now names only `https://bw.spec4.ai`.
9. **`pyproject.toml` stale comment (new in Phase 8):** the comment above
   `[tool.ruff]` (lines ~50–54) still says the gates are "scoped
   deliberately … the four already-shipped example apps are left alone".
   Since Phases 4–5 that is false: the `[tool.mypy]` comment below it
   correctly says there are no exclusions. It is comment only, so the gates
   are unaffected. It was left alone because this phase only verifies.

### Required-credential contract (Phase 1)

10. `tests/services/test_moderation.py::…test_a_missing_api_key_fails_closed_without_a_call`:
    its docstring still says "a deployment without the key must still start".
    It tests a defensive branch that is still in the code.
11. Code paths for a missing key that a running service can no longer reach:
    - the moderation `if not api_key` fail-closed branch
    - `provider_api_key` dropping unkeyed providers
    - the "GROQ_API_KEY is unset" path in `services/discover_models.py`
    - `tests/test_model_registry.py::test_ensure_provider_credentials_omits_groq_when_unset`,
      which tests the unset-Groq path

    All kept.
12. Test-environment dependencies:
    - `tests/test_observability.py::_settings` is the only test helper that
      takes the two keys from `.env` or the environment.
    - The suite still fakes `DATABASE_URL`, `CORS_ORIGIN`,
      `OPENROUTER_API_KEY` and `EXA_API_KEY` in `conftest.py`.

### Router unavailable state (Phases 2–3)

13. `npx tsc --noEmit` at `frontend/` checks nothing (`"files": []` with
    references). No tsconfig includes `frontend/tests/`, so test files are
    never type-checked. This predates v10.
14. **Intended behaviour changes (please confirm):**
    - The presets endpoint no longer retries the title read on every GET.
      Recovery is through `POST /api/router/retry` only.
    - A comparison re-run is also refused while unavailable, even though it
      never calls the router.
15. **Changed Router refusal text, as the spec asked:**
    - `NOT_READY_MESSAGE` (run refusal) now begins "The Router is temporarily
      unavailable: …" and adds "nothing was held".
    - `DESCRIPTIONS_NOT_READY` (now the retry 503 message; it used to be the
      presets 503) is reworded the same way.
    - The code `descriptions_not_ready` is unchanged.
16. The unavailable notice repeats the runs-remaining badge, because the run
    controls are hidden. This is a design choice.
17. `fetchRouterPresets` keeps the old 503 `not_ready` path for
    compatibility, although the backend no longer returns it.
    `REFUSAL_HEADINGS` still labels `descriptions_not_ready` "Router not
    ready". The unavailable notice usually replaces that banner.
18. Pre-existing: the structlog JSON output logs `exc_info: true` but no
    traceback for `logger.exception` calls (`router_warmup_failed`,
    `router_retry_failed`). That makes failures hard to diagnose from the
    journal.

### Optional follow-up (Phase 5)

19. The `pydantic.mypy` plugin would remove the `type: ignore[call-arg]` in
    `core/config.py`. It would also make five existing test `type: ignore`s
    unused, which means editing tests. It was not adopted.

Resolved during v10:
- The owner retired the v7 planning guard
  (`frontend/tests/planning-untouched.test.ts`, deleted in Phase 5).
- The Phase 2 lifespan Render docstring was rewritten in Phase 6.
- `test_deploy_readiness.py` formatting was fixed in Phase 4.
- The frontend's expectation of the old presets 503 was replaced by the
  Phase 3 unavailable state.

## Baseline

Recorded 2026-10-25, before any v10 change.

- HEAD: `b22522b7beeb3b1e5a502568e05a814cf597ffc7` (branch `dev`, "v1.1.0:
  Adding a model router example"). The working tree was clean at that point:
  the v9 Router slice and the 1.1.0 version bump are already in this commit.
- Working-tree snapshot (tracked + untracked, `.gitignore` respected,
  `node_modules/` and `.venv/` excluded, no `.env`):
  `/tmp/claude-1000/-home-rcrowe-Projects-spec4-test-BWS4/c6a5d70c-0431-4179-ac30-c871bd57429f/scratchpad/v10-baseline/`
  — diff later phases against this, or against the commit above.

| Gate | Command | Result |
|---|---|---|
| pytest | `uv run pytest` | 2115 passed, 21 skipped, 6 deselected (`live`), 0 failed |
| ruff | `uv run ruff check .` | All checks passed (with the existing `extend-exclude` list) |
| mypy | `uv run mypy` | Success: no issues in 234 source files (with the existing `ignore_errors` overrides) |
| frontend build | `npm run build` (in `frontend/`) | Passed (`tsc -b && vite build`, 764 modules) |
| vitest | `npx vitest run` (in `frontend/`) | 38 files, 484 tests passed |

Boot check: `uv run uvicorn backend.app.main:app --workers 1` started and
`GET /health` returned `200 {"status":"ok","db":"connected"}` against Neon.
The phase text says `/api/health`; that path is a 404 on the backend. The
liveness route is `/health` (outside the `/api` prefix — `deploy/Caddyfile`
gives it its own matcher), so the check used it.

## Phase 1 — required credential contract

`GROQ_API_KEY` and `OPENAI_API_KEY` are now required `str` fields on
`Settings`. An empty or whitespace-only value counts as missing. There is no
placeholder default and no opt-out. `get_settings()` still caches, still
resolves `.env` from `REPO_ROOT`, and still raises `RuntimeError`; the first
line of the message now names the variable(s) at fault, e.g.
`Invalid or missing configuration: GROQ_API_KEY.`

After counts: pytest 2126 passed, 21 skipped, 6 deselected (baseline plus the
11 new tests in `backend/tests/core/test_required_credentials.py`). ruff and
mypy are clean (235 files). vitest: 484 passed. Startup with
`GROQ_API_KEY=` or `OPENAI_API_KEY=` exits with code 1 and names that key.

A pytest run with a guard that blocked DNS for `groq.com`, `openai.com`,
`openrouter.ai` and `exa.ai` passed in full and recorded no lookups of those
hosts. So the real keys the suite now loads from `.env` never reach a
provider. (The only outbound lookups were `huggingface.co` and
`raw.githubusercontent.com`, which the suite already made at baseline.)

### Test changes (listed, not silent)

- `backend/tests/conftest.py`:
  - Removed `os.environ["OPENAI_API_KEY"] = ""` (the force-clear). Its job,
    keeping the suite away from the live moderation endpoint, now belongs to an
    autouse fixture, `_moderation_endpoint_offline`. That fixture replaces the
    `httpx` that `services/moderation.py` sees with one whose `AsyncClient`
    refuses to be constructed. An un-overridden gate still fails closed
    (`moderation_unavailable`), now via `moderation_failed_closed` instead of
    `moderation_key_missing`.
  - The provider-key loop no longer fakes keys for providers whose Settings
    field is required, which removes the fake `GROQ_API_KEY`. OpenRouter keeps
    its explicit default, which is outside this phase's scope.
- Docstrings that explained the gate failing closed by "no `OPENAI_API_KEY` in
  the test environment" were reworded to say the endpoint is held offline. The
  files are the eight API test modules, `tests/react/conftest.py` and
  `tests/react/test_react_live_smoke.py`. No assertion changed.

### Flagged for the owner (deliberately not changed)

- `tests/services/test_moderation.py::...test_a_missing_api_key_fails_closed_without_a_call`
  patches settings to `openai_api_key=None` and asserts that `moderate()`
  fails closed. Its docstring still says "A deployment without the key must
  still start". That is no longer true, but the test checks a defensive branch
  that is still in the code. Moving it to the fail-fast behaviour would change
  what it asserts.
- `tests/test_model_registry.py::test_ensure_provider_credentials_omits_groq_when_unset`
  checks the unset-Groq path with fake settings. In production this can no
  longer happen. The test still passes.
- Runtime code that still handles a missing key, now unreachable in a running
  service: the `if not api_key` fail-closed branch in `services/moderation.py`
  (kept as defence in depth, comment updated), `provider_api_key` dropping
  unkeyed providers in `services/model_registry.py` (generic, still needed for
  any future optional provider), and the "GROQ_API_KEY is unset" path in the
  developer probe `services/discover_models.py`.
- `tests/test_observability.py::_settings` builds `Settings(**base)` without
  the two keys, so it now takes them from `.env` or the environment. This is
  correct under the new contract, but it is the only test helper that
  depends on that.
- The suite still fakes `DATABASE_URL`, `CORS_ORIGIN`, `OPENROUTER_API_KEY`
  and `EXA_API_KEY` in `conftest.py`. These defaults are outside this phase's
  scope.

## Phase 2 — best-effort Router warm-up and unavailable state

Before this phase, the lifespan in `backend/app/main.py` awaited
`warm_route_descriptions()` outside the `try/except` that protects the
embeddings warm-up. Boot survived a failure only because the function
swallowed its own errors (via `ensure_route_descriptions`). Now:

- `backend/app/router/state.py`: the holder is unavailable at import and ready
  only after a warm-up fully succeeds. It is built locally and stored in one
  assignment, so a failure never leaves partial descriptions. `is_ready()` is
  an in-memory read. `warm_route_descriptions()` can be called again: it
  returns the held value without a DB read when ready, and otherwise raises on
  failure and leaves the state unchanged. There is no background timer.
- `main.py`: the warm-up call alone is wrapped. A failure logs
  `router_warmup_failed` and boot continues. Settings still load at import,
  outside the lifespan, so a missing required credential stays fatal
  (re-checked: `GROQ_API_KEY=` still raises `Invalid or missing configuration:
  GROQ_API_KEY.`).
- `GET /api/router/presets` now carries `available: bool`. When ready, every
  other field is unchanged. When unavailable it returns 200 with
  `available: false`, `route_descriptions: []`, and a null block and
  sha256. The presets and fixed settings are still served.
- New `POST /api/router/retry` returns 200 `{"available": true}` on success.
  On failure it returns 503 with detail `{code: "descriptions_not_ready",
  message}`. It does not reserve usage or touch the allowance tables.
- `POST /run` and `POST /rerun` check availability first. A run is refused
  before preset resolution, moderation and the hold. If unavailable they
  return an ordinary 503 JSON error, `descriptions_not_ready` ("temporarily
  unavailable"), with no stream, no hold, no units and no history row. When
  ready, the run order is availability, moderation (free text only), then the
  2-unit hold and SSE. No DB session is used for the check. The rule that
  streams open their own session is untouched.

After counts: pytest 2140 passed, 21 skipped, 6 deselected (Phase 1 plus 14:
12 in the new `backend/tests/router/test_router_availability.py`, net +1 in
`test_route_descriptions.py`, +1 in `test_run.py`). ruff and mypy are clean
(236 files). vitest: 484 passed (frontend untouched).

Live check (`uvicorn`, one worker, Neon). The indexed-title read was made to
fail while a flag file existed. The log showed `router_warmup_failed` and then
startup completed. `/health` returned 200, `GET /api/embeddings/presets`
returned 200, and router presets returned `available: false`. A free-text
`POST /api/router/run` returned 503 `application/json` with
`descriptions_not_ready`. A retry while the fault was present returned 503.
The Router `allowance_holds` row count was 3 before and 3 after. After the
flag was removed, `POST /api/router/retry` returned 200, and presets
returned `available: true` with 4 routes, all without a restart. The server
was then stopped and port 8000 is free.

### Test changes (listed, not silent)

- `tests/router/test_route_descriptions.py`: the 503 "not ready" presets test
  now asserts 200 with `available: false` and an empty or null description
  field. The "recovers on the next GET" test now recovers through
  `POST /retry`. Two tests were added: one for `available: true`, and one
  checking that GET never re-reads the titles.
- `tests/router/test_run.py`: the not-ready refusal test no longer patches the
  title read, because admission no longer reads it. A new test checks that a
  free-text run is refused before moderation is called.

### Flagged for the owner

- **Behaviour change, intended by the spec:** the presets endpoint no longer
  retries the title read on each request. A Router that failed at boot now
  stays unavailable until `POST /api/router/retry` succeeds. The frontend
  still expects the old 503 and a non-null block until Phase 3 lands. In the
  meantime it gets `available: false`, an empty route list and a null block.
  Runs are refused with the existing `descriptions_not_ready` code, which the
  frontend already labels "Router not ready".
- `NOT_READY_MESSAGE` (the run refusal text) now says "temporarily
  unavailable". The code `descriptions_not_ready` is unchanged.
- A re-run is now also refused while unavailable, as instructed, although its
  forced route never calls the router.
- Pre-existing, not changed: the structlog JSON output logs `exc_info: true`
  but no traceback, for every `logger.exception` call (seen live for
  `router_warmup_failed` and `router_retry_failed`). That makes warm-up
  failures hard to diagnose from the journal.
- Pre-existing, not changed: the lifespan docstring still cites Render's
  free-tier spin-down (retired host, a later phase's sweep). `ruff format
  --check` flags `tests/collab/test_deploy_readiness.py`, which was already
  the case at baseline.

## Phase 3 — Router unavailable page state and Retry button

Frontend only. No backend file changed in this phase.

- `frontend/src/api/router.ts`: `RouterPresetsResponse` now has
  `available: boolean`, and the block and sha256 are `string | null`. The
  mapper is defensive: a response that says `available: true` but has no
  block or hash is treated as unavailable rather than half-drawn. New
  `retryRouter()` (`POST /api/router/retry`, throws `RouterRequestError` with
  the server's code on 503) and `useRouterRetry()` (a mutation with
  `retry: 0` that invalidates the new exported `ROUTER_PRESETS_KEY` on
  success). The `{code, message}` refusal parsing that `streamRouter`'s
  `onopen` did inline is now a shared `refusalError()` helper used by both.
  The `RouteId` spellings are unchanged.
- `frontend/src/apps/router/RouterUnavailable.tsx` (new): an amber notice in
  the same style as the existing refusal banner. It has a fixed "temporarily
  unavailable" message, the runs-remaining badge, and a Retry button that is
  disabled and labelled "Retrying…" while pending.
- `frontend/src/apps/router/RouterApp.tsx`: while unavailable, the notice
  replaces the knowledge panel and the run controls. The screen header,
  pattern summary, overview, stored results and agreement history stay.
  `startRun` returns early, and stored results get no re-run offer, so
  nothing can start a run. The allowance entry is only read. A failed retry
  changes nothing on screen. On success the presets refetch and the normal
  page renders in place. Defensive handling: a run refused with
  `descriptions_not_ready` (an ordinary HTTP error before `run_end`, so no
  run is spent) invalidates the presets so the page switches to the
  unavailable state. A not-ready refusal that a successful retry has made
  stale is not shown again.
- `frontend/tests/router-unavailable.test.tsx` (new, 7 tests), mocked at
  `fetch` as in `router.test.tsx`. It covers the message and Retry with no
  input and the overview kept, stored results kept without a re-run offer, a
  successful retry restoring the input and panel, a failed retry keeping the
  identical text with one alert and no automatic retry, the button disabled
  while pending, the counter and the raw localStorage entry unchanged through
  a failed and then a successful retry, and a not-ready run refusal flipping
  the page with nothing spent.
- `frontend/tests/routerFixtures.ts`: `ROUTER_PRESETS` gains
  `available: true`, `presetsWireBody` sends `available`, and there is a new
  `UNAVAILABLE_PRESETS` fixture. Existing tests are unchanged.

After counts: vitest 39 files, 491 passed (484 + 7). `npx tsc --noEmit`
is clean, and so is `npx tsc --noEmit -p tsconfig.app.json`. `npm run build`
passed (765 modules). oxlint reports 0 errors; its 13 warnings are all the
pre-existing `only-export-components` warnings in `src/routes.tsx`, which
was not touched. Backend gates are unchanged from Phase 2 (pytest 2140/21/6,
ruff and mypy clean). They were not re-run, because no backend file changed.

Manual check: uvicorn (one worker, Neon) ran with the indexed-title read
patched, via a scratchpad launcher, to fail while a flag file existed;
`CORS_ORIGIN` was overridden in the process env for the Vite origin. The log
showed `router_warmup_failed`, then startup completed. `/health` returned 200.
Headless Chromium on `/router` (Vite dev) showed the notice and Retry, with
the overview visible and no input. Retry with the fault still present gave
one `POST /retry` 503, identical notice text and a single alert. After the
flag was removed, Retry gave `POST /retry` 200, then one presets GET, and the
input and the 1152-character block appeared. A `window` marker set before the
retry survived, so there was no reload. The counter showed "Runs left 5 of 5"
throughout. All nine other app routes rendered their h1 with no page errors.
The servers were stopped, ports 8000 and 5173 are free, and the launcher and
flag were deleted.

### Flagged for the owner

- `npx tsc --noEmit` at `frontend/` is a no-op: the root `tsconfig.json` has
  `"files": []` with project references, so it checks nothing. `tsc -b`
  (inside `npm run build`) and `-p tsconfig.app.json` do check `src/`. No
  config includes `frontend/tests/`, so test files are never type-checked.
  This was already the case before this phase.
- The unavailable notice repeats the runs-remaining badge, because the run
  controls that normally carry it are hidden. This is a small design choice,
  made so that the counter stays visible.
- The old 503 path in `fetchRouterPresets` (code `not_ready`) is kept for
  compatibility. The Phase 2 backend no longer returns it, and the existing
  `router.test.tsx` test for it still passes.
- Pre-existing: `RouterApp`'s `REFUSAL_HEADINGS` still labels
  `descriptions_not_ready` "Router not ready". With the defensive refetch,
  that banner is replaced by the unavailable notice once the presets report
  unavailable, so a visitor rarely sees it.

## Phase 4 — whole-backend ruff gate

### Ruff exclusions removed

All of these were in `pyproject.toml` before this phase. All are now gone.
`[tool.ruff]` keeps `line-length = 88`, `target-version = "py312"`, double
quotes and the same `select` list and bugbear `extend-immutable-calls`.
`grep -n "exclude" pyproject.toml` now matches nothing.

- `[tool.ruff] extend-exclude` (45 entries):
  - `backend/app/main.py`
  - `backend/app/api/`: `__init__.py`, `chained_calls.py`, `embeddings.py`,
    `health.py`, `orchestrated.py`, `planning.py`, `rag.py`,
    `single_call.py`, `tools.py`
  - `backend/app/core/`: `__init__.py`, `config.py`, `logging.py`
  - `backend/app/services/`: `__init__.py`, `agent_runtime.py`,
    `discover_models.py`, `embedding.py`, `generation.py`,
    `model_registry.py`, `prompt_loader.py`, `shared.py`, `storage.py`,
    `web_search.py`
  - whole packages: `backend/app/chained_calls`, `backend/app/db` (which
    includes the Alembic migrations), `backend/app/embeddings`,
    `backend/app/planning`, `backend/app/rag`, `backend/app/single_call`,
    `backend/app/tools`
  - tests: `backend/tests/chained_calls`, `backend/tests/embeddings`,
    `backend/tests/single_call`, `backend/tests/conftest.py`,
    `backend/tests/test_*.py`
- `[tool.ruff.lint.per-file-ignores]`: `"backend/app/db/migrations/**" =
  ["E501", "I001", "UP035", "UP006"]`. This did not skip files, but it did
  switch rules off for the migrations, so it was removed too. It only hid 15
  findings (14 `UP035` `typing.Sequence` imports and 1 `I001`), and all of
  them were auto-fixable.
- No `exclude`, `force-exclude` or `extend-per-file-ignores` setting existed.
  There is no separate `ruff.toml` either.

The comment on the mypy override for `services.web_search` said the file
"stays in ruff's `extend-exclude`". That sentence was updated, and nothing
else in the mypy section changed.

### Findings and how they were fixed

With the exclusions removed, `uv run ruff check .` reported **394** findings
(the old comment estimated 366; the files have grown since). `ruff format
--check` said **54** files would be reformatted (the estimate was 57).

| Batch | Rule(s) | Count | Fix |
|---|---|---|---|
| 1 | `I001`, `F401` | 26 + 6 | Safe `--fix`. The unused imports were `date`/`Date` in `db/models.py` and `services/shared.py`, `Iterator` and an in-function `agents` import in `test_planning_api.py`, and `PlanStep` in `test_planning_orchestrator.py`. The sorts only reorder within contiguous import blocks. No import moved past the `os.environ` set-up in `conftest.py`. |
| 2 | `UP007`, `UP017`, `UP037`, `UP035` | 42 + 22 + 1 + 14 | Safe `--fix`, then `I001`/`F401` again for the `Union`/`timezone` imports this left unused. The changes are `Optional`/`Union` → `X \| None`, `timezone.utc` → `UTC`, `typing.Sequence` → `collections.abc`. All 14 migrations and `env.py` were touched (annotations only). |
| 3 | `B905` | 6 | All six were in tests. `zip(words, words[1:])` and `zip(passages, passages[1:])` → `itertools.pairwise` (same semantics). `test_structured_mode.py` already asserts equal lengths just above its loop, so it got `strict=True`. The three `_cosine_*` helpers compare equal-length embedding vectors, so they got `strict=True`. Nothing that currently passes can be affected. |
| 4 | `N818` | 3 | The private `_UnsupportedSchema` in `api/single_call.py` was renamed `_UnsupportedSchemaError`. Its message and the 422 `unsupported_response_schema` code are unchanged. The other two got `noqa`s, listed below. |
| 5 | `ruff format .` | 54 files | See the verification below. |
| 6 | `E501` | 283 → 46 after format | Long string literals were split into implicit concatenations, so the runtime value is byte-identical. Single-line keyword or dict values were wrapped in parentheses. One module docstring summary line was shortened (`api/chained_calls.py`: dropped "the"). Five test functions had names too long for any `def` line, so they were renamed (listed below). |

`uv run pytest -x -q` ran after every batch, and each run gave 2140 passed,
21 skipped, 6 deselected.

**How "formatting only" was verified.** The phase started from a snapshot of
`backend/`. I rebuilt the lint-fixed, pre-format tree in the scratchpad by
running the same safe `--fix` passes on that snapshot. Then I compared
every changed file with it by AST (`ast.dump`, with docstrings normalised by
`inspect.cleandoc`). After the format and the `E501` string splits, every
file was AST-identical except the hand-edited ones: `api/single_call.py`
(identical once the rename is undone), the `api/chained_calls.py` docstring,
the five renamed tests, the `B905` edits, and the two test files below. So
the 54-file reformat and every literal split changed only whitespace, quoting
and wrapping. Python joins implicitly concatenated literals at parse time, so
the visitor-facing strings, preset prompts and error messages are unchanged.
The route-id constants, the `critique_failed` 200 path, the usage caps, the
uvicorn worker setting and the streaming-session rule were not touched.

### `noqa` suppressions added (each targeted, with a reason)

- `backend/app/planning/budget.py` — `class CallCeilingExceeded(Exception):
  # noqa: N818 -- public name tests import`.
- `backend/app/services/agent_runtime.py` — `class
  StepRequestLimitExceeded(AgentLaneError):  # noqa: N818 -- public name tests
  import`.

Renaming either one would mean editing the tests that import and
`pytest.raises` them (`test_planning_orchestrator.py`,
`test_planning_agents.py`, `test_probe_capabilities.py`,
`react/test_react_cycle.py`). Renaming also touches `planning/service.py`
and `react/service.py`. These are the only two new `noqa`s. The `# noqa:
E402` already in `db/migrations/env.py` was there before this phase and is
unchanged.

### Test changes (listed, not silent) — flagged for the owner

Removing the exclusions conflicted with two existing tests, because each one
pinned the old configuration. To meet the verification gate, both were
adjusted rather than left failing. The owner should confirm both:

- `backend/tests/react/test_react_gate_registration.py` read
  `CONFIG["tool"]["ruff"]["extend-exclude"]` (a `KeyError` once it is
  gone). `test_no_legacy_path_was_un_excluded_by_this_phase` asserted that
  ten legacy paths **keep** their ruff exemption, and the migration test
  asserted that 0013 sits under the `backend/app/db` exclusion. These were
  changed as follows:
  - `RUFF_EXCLUDE` now uses `.get(..., [])`.
  - The legacy test is renamed `test_no_legacy_path_is_excluded_from_ruff`
    and asserts the opposite. It requires an empty inventory, no `exclude`
    key, and none of those ten paths excluded.
  - The migration test asserts that 0013 is not excluded.
  The module docstring was updated to match. The test count is unchanged,
  and the mypy half is untouched (Phase 5).
- `frontend/tests/planning-untouched.test.ts` asserts that `git diff
  7877845 -- backend/app/planning` is empty, meaning v7 left the planning
  agent alone. This phase's reformat, string splits and one `noqa` comment
  necessarily changed five files there. All five are AST-identical to before.
  For that one path, the diff now runs from `7877845` to the v10 baseline
  `b22522b` instead of to the working tree (new `V10_BASELINE` and
  `RUFF_REFORMATTED` constants, with a comment). The anchor check also
  requires `b22522b`. Every other path still diffs to the working tree.
  Owner decision: keep this re-anchoring, or retire the v7 guard now that a
  later revision has deliberately edited the path.
  **Resolved:** the owner chose to retire the v7 guard, and the file was
  deleted in Phase 5. vitest went from 39 files / 491 tests to 38 files /
  475 tests, because the file held 16 tests. Phase 8's baseline comparison
  should expect this drop.
- Five tests were renamed for `E501`. No body or assertion changed, and
  nothing else refers to them:
  - `embeddings/test_placement.py`:
    `…placement_endpoint_answers_503…` → `test_placement_answers_503_with_a_retryable_code_when_embedding_fails`
  - `test_citations.py`: → `test_build_answer_marks_uncited_answer_unsupported_despite_the_threshold`
  - `test_dataset_embeddings.py`: → `test_index_dataset_writes_an_embedding_and_representation_row_per_passage`
    and `test_cosine_distance_query_for_a_known_passages_embedding_returns_itself`
  - `test_tool_use.py`: → `test_search_endpoint_returns_unavailable_message_when_search_cap_reached`
- The six `B905` edits above are in tests, and no assertion changed.

### Real bugs surfaced — owner decision

None. The findings were style, import and modernisation rules, plus six
`B905`s, all of them in tests. No unawaited coroutine, mutable default,
shadowed exception or `raise` without `from` came up under the selected rule
set.

### After counts

| Gate | Result |
|---|---|
| `uv run ruff check .` | All checks passed (0 exclusions) |
| `uv run ruff format --check .` | 353 files already formatted |
| `uv run pytest` | 2140 passed, 21 skipped, 6 deselected (same as Phase 3) |
| `uv run mypy` | Success: no issues in 236 source files (unchanged config) |
| `npx vitest run` | 39 files, 491 passed |
| `npx oxlint` | 0 errors, the same 13 `src/routes.tsx` warnings |

The earlier notes' known issues that are now resolved: `config.py`,
`main.py` and the legacy test modules are now ruff-formatted, and
`tests/collab/test_deploy_readiness.py` now passes `ruff format --check`.

## Phase 5 — whole-backend mypy strict gate

### mypy exclusions removed

All of these were in `pyproject.toml` `[tool.mypy]` before this phase. All
are now gone. `strict = true` and `python_version = "3.12"` are unchanged.
There is no `exclude` setting, and no separate `mypy.ini` or `setup.cfg`.

- `files = ["backend/app", "backend/tests"]`. This left out only
  `backend/__init__.py`, but it is now `files = ["backend"]`, so nothing
  under the package can drop out of the checked set.
- `ignore_errors = true` override for 17 module patterns:
  `backend.app.api.{chained_calls, embeddings, health, orchestrated,
  planning, rag, single_call, tools}`, `backend.app.chained_calls.*`,
  `backend.app.core.*`, `backend.app.db.*`, `backend.app.embeddings.*`,
  `backend.app.planning.*`, `backend.app.rag.*`,
  `backend.app.single_call.*`, `backend.app.tools.*` and
  `backend.app.main`.
- `ignore_errors = true` override for `backend.app.services.*`.
- `ignore_errors = false` override re-enabling `services.moderation`,
  `services.allowance_holds`, `services.untrusted`, `services.message_bus`,
  `services.prompt_context`, `services.probe_capabilities`,
  `services.chain_health` and `core.observability`.
- `ignore_errors = false` override naming `backend.app.api.react`,
  `backend.app.react.*`, `backend.app.services.web_search`,
  `backend.app.api.router` and `backend.app.router.*`. It did not exempt
  anything, but it was a per-module `ignore_errors` toggle. With nothing left
  to re-enable against, the strict default covers all of these.
- No `follow_imports` override existed.

### Stub overrides (third-party only)

- `[[tool.mypy.overrides]] module = ["sklearn.*"]`,
  `ignore_missing_imports = true`. scikit-learn ships neither stubs nor
  `py.typed`, and `embeddings/service.py` imports `sklearn.decomposition`.
  This is the only override left.
- The previous stub override also listed `litellm.*`,
  `sentence_transformers.*` and `pgvector.*`. All three now ship
  `py.typed`, and mypy is clean without them, so they were dropped.

### Findings and how they were fixed

With the overrides removed, `uv run mypy` reported **35 errors in 10 files**
(237 source files checked). That is far fewer than the risk assessment
expected, because the legacy code was already well annotated. Every fix is
annotation-only. The only runtime-visible edits are an import path that
resolves to the identical class and one declared local, both described below.

| File | Errors | Fix |
|---|---|---|
| `chained_calls/service.py` (via `api/chained_calls.py`) | 1 `arg-type` | `ChainOutcome.status` and `STATUS_COMPLETE` / `STATUS_CRITIQUE_FAILED` typed as the existing `schemas.ChainStatus` literal. The values (`"complete"`, `"critique_failed"`) and the 200 path are unchanged. |
| `single_call/service.py`, `services/shared.py` (via `api/single_call.py`) | 1 `arg-type` | `SingleCallResult.mode` typed as `schemas.SingleCallMode`. `shared.MODE_PLAIN` / `MODE_STRUCTURED` gained `Final`, so mypy reads them as their literal values. |
| `planning/service.py`, `planning/schemas.py` | 3 `arg-type`, 3 `no-untyped-def` | `STATUS_COMPLETED` / `STATUS_FAILED` gained `Final`. The ternary result is annotated `Literal["completed", "failed"]`. `gate`, `_search_for` and `_gate` now use the existing `agents.GateHook` / `agents.ExecuteSearch` aliases. `execute_plan` is declared `AsyncGenerator[ExecutionEvent, None]` (it is an async generator, and the route calls `.aclose()` on it). |
| `api/planning.py`, `api/orchestrated.py` | 2 `attr-defined`, 2 `type-arg`, 1 `attr-defined` (`aclose`) | `ServerSentEvent` / `EventSourceResponse` are now imported from `sse_starlette` (the package's `__all__`) instead of `sse_starlette.sse`. These are the same objects (`is` was checked), and `api/router.py` and `api/react.py` already import this way. `_event(payload: dict)` became `dict[str, object]`. `aclose` is fixed by the `AsyncGenerator` return above. |
| `core/config.py` | 6 `call-arg` | One `# type: ignore[call-arg]` (listed below). |
| `db/models.py` | 1 `type-arg` | `RagInteraction.retrieved_passages: Mapped[list[dict[str, object]]]`. The column type is unchanged. |
| `services/discover_models.py` | 6 `type-arg` | New `ProbeResult` TypedDict for `probe_model` / `probe_with_backoff`. The ranking helpers take `Sequence[Mapping[str, Any]]` (alias `_RankEntry`), because `test_model_registry.py` passes partial `dict[str, Any]`s without `query`. Typing them as `ProbeResult` would mean changing the test. This is the one new `Any`: it describes the probe dict's heterogeneous values. |
| `services/embedding.py` | 1 `no-any-return` | sentence-transformers' constructor is inferred as `Any` in the installed release. The model is bound to a declared `model: SentenceTransformer` local before it is returned. The load and the `lru_cache` are unchanged. |
| `tools/agent.py` | 6 `type-arg`, 3 `attr-defined` | Bare `dict`s became `dict[str, object]`. Small read-only Protocols (`_ToolFunction`, `_ToolCall`, `_Message`, `_Choice`, `_Completion`) name the slice of a LiteLLM response the loop reads, because `litellm.acompletion` is typed as returning `Any`. `_complete` is declared to return `_Completion` instead of `object`, and `_parse_query` takes `_ToolCall`. The `return` inside the `try` now returns a declared local. The exception scope is identical. |

The `pydantic.mypy` plugin was tried as the fix for `config.py`. It made the
`Settings()` call clean, but it also made five existing `# type: ignore`s in
tests unused (`core/test_required_credentials.py:95`,
`react/test_react_suitability_golden.py:269`,
`test_planning_schemas.py:68/71/74`). Removing them would have meant editing
tests, so the plugin was not adopted. The owner may want it later.

`get_settings`, `run_typed_step`, `get_db_session` and `moderate` were not
touched. Nor were the Router route-id constants, the usage caps or any
visitor-facing string.

### `type: ignore` added (each with a reason comment)

- `backend/app/core/config.py` `get_settings`: `return Settings()  # type:
  ignore[call-arg]`. Every field comes from the environment or `.env`, which
  mypy cannot see without the pydantic plugin. This matches the existing
  ignore on the same call in `tests/core/test_required_credentials.py`.

This is the only new suppression. No `cast` was added.

### Test changes (listed, not silent) — flagged for the owner

As in Phase 4, removing the exclusions conflicted with tests that pinned the
old configuration. Both were adjusted rather than left failing, and the owner
should confirm them:

- `backend/tests/react/test_react_gate_registration.py` (the mypy half that
  Phase 4 left alone). The test count is unchanged (8), and the module
  docstring was updated.
  - `test_the_react_package_is_covered_by_a_wildcard_not_an_inventory`
    asserted that an `ignore_errors = false` override names
    `backend.app.react.*`. It is renamed
    `test_no_mypy_override_switches_errors_off`, and it now asserts that no
    override carries `ignore_errors` and that the ReAct modules fall to the
    strict default.
  - `test_the_test_tree_is_in_the_checked_file_set` asserted
    `files == ["backend/app", "backend/tests"]`. It now asserts
    `["backend"]`, `strict is True` and no `exclude`.
  - `test_the_files_this_phase_appended_to_kept_their_own_gating` asserted
    that `shared` / `config` / `main` stay excluded and `web_search` /
    `observability` stay re-enabled. It is renamed
    `…_are_type_checked`, and it asserts that all five are matched by no
    override.
- `frontend/tests/planning-untouched.test.ts` was **deleted** on the owner's
  decision to retire the v7 planning guard (see the resolved Phase 4 item).
  The two type-only fixes in `backend/app/api/planning.py` (the import path
  and `dict[str, object]`) had made its diff from `7877845` non-empty. It
  was deleted outright, not re-anchored a second time. Nothing else in
  `frontend/`, `docs/`, `CLAUDE.md` or the README referenced it. vitest is
  now 38 files / 475 tests (it was 39 / 491).

### Flagged: type fix requires test change

None. No test's logic or assertions needed to change to satisfy mypy. The
test tree was already clean, and the ranking helpers were typed loosely
enough to accept the existing test dicts (see `discover_models.py` above).

### Real bugs surfaced — owner decision

None. No finding was a value that can be `None` at runtime, or a wrong
return type with runtime consequences. The `str` versus `Literal`
mismatches were all literal values, which Pydantic already validated at
runtime. `execute_plan`'s `AsyncIterator` annotation understated an async
generator whose `aclose()` the route correctly relies on.

### After counts

| Gate | Result |
|---|---|
| `uv run mypy` | Success: no issues found in 237 source files (0 `ignore_errors`, `files = ["backend"]`) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 353 files already formatted |
| `uv run pytest` | 2140 passed, 21 skipped, 6 deselected (same as Phase 4) |
| `npx vitest run` | 38 files, 475 passed (planning-untouched.test.ts deleted: was 39 / 491) |
| `npx oxlint` | 0 errors, the same 13 `src/routes.tsx` warnings |

## Phase 6 — Render sweep and startup docstring

Comments, docstrings and docs only. No code path, route, response shape,
usage cap or visitor message changed.

### Lifespan docstring

`backend/app/main.py` `lifespan` docstring rewritten. It now describes the
always-on netcup VPS 500 G12 (one systemd-supervised Uvicorn process behind
Caddy). The embedding model load, preset embedding and 2D PCA fit happen once
per process start and stay warm for the process lifetime; the release
script's readiness gate waits for them. Both warm-ups (embeddings and Router
route descriptions) are documented as best-effort (logged, API still starts),
and a missing `GROQ_API_KEY` or `OPENAI_API_KEY` as fatal at settings import.
The free-tier spin-down text is gone. `Args:`/`Yields:` sections were added
to match the Google-style convention. This documents
nfr_the_first_visit_loads_without_a_cold_start_delay_because_the_embedding_capability_is_ready_at_startup.
It resolves the Phase 2 item "the lifespan docstring still cites Render's
free-tier spin-down" (that Phase 2 line is left as written, as history).

### Render sweep

Searched with `git grep --untracked -i` for `render`, `onrender`,
`render.com`, `render.yaml`, `RENDER_`, `render free`, `render's`, plus
`dyno`, `free tier`, `spin down` and `cold start`, which describe the same
retired host without naming it. `.env` and `.spec4/` were excluded.
`render.yaml` is absent. There were no `onrender.com` URLs and no `RENDER_`
variables in runtime code or config. `.env.example`, `CORS_ORIGIN` examples,
`.claude/settings.json`, `pyproject.toml`, `frontend/index.html`,
`frontend/public/` (robots.txt, sitemap.xml, og-image) and
`frontend/src/seo/siteMeta.ts` had no Render references. Runtime URLs already
use `https://bw.spec4.ai`, so no runtime URL needed replacing or flagging.
Every other `render` hit is a React or Testing Library call, a "Render …"
docstring verb, a `render_*` helper, or structlog's `JSONRenderer`. All left
alone.

Files changed (stale host reference rewritten to describe the VPS, or made
host-neutral):

- `backend/app/main.py`: lifespan docstring (above).
- `backend/app/api/collab.py`, `backend/app/api/react.py`: `PING_SECONDS`
  comments said "Render's proxy closes an idle connection". They now say "a
  proxy between the browser and the API can". The value (15) is unchanged.
- `backend/tests/react/test_react_api.py`: the same wording in a test
  docstring.
- `backend/app/chained_calls/service.py`: "a free dyno spins down between
  clicks" changed to "a release restart can fall between the two clicks".
  Same reasoning, same `writer_model=None`.
- `backend/app/embeddings/service.py`, `backend/app/orchestrated/validator.py`,
  `backend/app/services/chain_health.py`, `backend/app/services/model_registry.py`
  (2 comments), `backend/app/services/shared.py`: "free dyno" / "dyno's life"
  changed to the API process / small shared host / VPS restart or reboot.
- `backend/tests/embeddings/test_embeddings_api.py`: "free-tier cold-start
  mitigation" changed to "warm-at-boot guarantee".
- `frontend/src/apps/collab/runState.ts`, `frontend/src/apps/collab/useCollabRun.ts`:
  comments justified the `connecting` phase with "Render's free tier spins
  down". They now cite the budget reservation and the first model call. The
  logic is unchanged.
- `README.md`: "on a free dyno the burst is the real cost" changed to "on a
  2-vCore VPS".
- `deploy/Caddyfile`: two comments compared behaviour with "as Render
  served it". They are now stated without the comparison. Comment-only, so
  there is no directive change.
- `deploy/README.md`: the env-names bullet ("retired Render dashboard")
  changed to "pre-migration deployment". The historical bwtemp DNS bullet no
  longer names Render.

Retirement-recording mentions kept:

- `README.md` lines 319–321: the single "previously deployed to Render …
  retired at cutover (2026-08-19), `render.yaml` deleted" statement.
- `deploy/README.md` lines 19–26: the cutover/retirement statement in the
  overview. Also the historical verification records at the end of that file
  (Phase 3 "comparison against Render" bullet, Phase 6 cutover summary), which
  that overview explicitly says retain such mentions.
- `deploy/ACCEPTANCE.md`: the whole file is the v8 migration's acceptance and
  cutover record, including side-by-side comparisons against
  `bws4.onrender.com` and the "Render retired" section. It is history and
  was left untouched.
- `backend/tests/collab/test_deploy_readiness.py` (module docstring, plus
  "the retired platform" in one test docstring) and
  `backend/tests/react/test_react_live_smoke.py`: one line each, "originally
  asserted against / formerly scanned render.yaml; since the cutover …".

### Flagged for the owner

- **Visitor-facing stale text, not changed (behaviour-preserving rule):**
  `frontend/src/apps/collab/CollabApp.tsx` line ~65, the `connecting`
  message, tells visitors "the backend sleeps when idle on its free tier, so
  the first response can take a few seconds". On the always-on VPS the
  backend never sleeps. A suggested replacement is "…composing the request
  for quotation… the first response can take a few seconds." No test
  asserts this sentence (checked), so changing it needs only the owner's
  approval.
- **CLAUDE.md, not changed:** the "Deployment shape" section still lists
  "(staging: `https://bwtemp.spec4.ai`)". `deploy/README.md` and
  `deploy/ACCEPTANCE.md` record that bwtemp was retired and its DNS deleted
  at the Phase 6 cutover. This is a retired host, but it is not Render. This
  phase does not explicitly call for a CLAUDE.md edit, so it is left for the
  owner. The suggested fix is to drop the parenthetical.

### After counts

| Gate | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 353 files already formatted |
| `uv run mypy` | Success: no issues found in 237 source files |
| `uv run pytest` | 2140 passed, 21 skipped, 6 deselected (unchanged) |
| `npx vitest run` | 38 files, 475 passed (unchanged) |
| `npx oxlint` | 0 errors, the same 13 `src/routes.tsx` warnings |

## Phase 7 — Unrecorded edits

Read-only inspection, except for the README fixes listed below as
"documentation only". No inspected change was reverted or rewritten.

**History used.** There are no tags. The "unrecorded" edits were committed by
the owner as `b22522b` ("v1.1.0: Adding a model router example"), on top of
the last planned commit, `861c009` ("Phase 6: cutover record …"). Each item
below was inspected with `git diff 861c009 b22522b -- <path>` and
`git log --follow`, and then compared with the working tree. In the working
tree, v10 Phases 1–6 changed only `README.md` (Phase 6, one word),
`generation.py` (Phase 4 reformat) and `pyproject.toml` (Phases 4–5 gates).
`frontend/index.html`, `sitemap.xml`, `siteMeta.ts`, `.claude/settings.json`
and `react-loop.test.tsx` are unchanged since `b22522b`. All eight edits share
one commit message, so the evidence of intent is that message, the v9 Router
slice committed with them (`.spec4/v9/`), and consistency with the code.

### SEO and site metadata (`frontend/index.html`, `frontend/public/sitemap.xml`, `frontend/src/seo/siteMeta.ts`)

- **What changed:** "Nine small example apps" became "Ten", and "… the ReAct
  loop, and a router" was added. This applies to `index.html` (meta, og and
  twitter descriptions) and to `siteMeta.DEFAULT_DESCRIPTION`. A
  `https://bw.spec4.ai/router` `<url>` entry was appended to `sitemap.xml`
  (lastmod 2026-10-15).
- **Intent:** to announce the v9 Router app, the tenth app, in the static and
  per-route metadata.
- **Evidence:** the commit message. The Router entry (`router_example_app`,
  route `/router`) was appended to `src/data/example-apps.ts` in the same
  commit.
- **Checks:**
  - Every absolute URL (`SITE_ORIGIN`, canonical, `og:url`, `og:image`,
    sitemap `<loc>`s, robots `Sitemap:`) uses the single VPS origin,
    `https://bw.spec4.ai`. There are no `bwtemp`, `onrender` or other stale
    hostnames in `index.html`, `public/` or `src/`.
  - The sitemap lists `/` plus the ten routes, which equals the ten `live`
    catalogue entries. Nothing is missing or extra; `/health` is deliberately
    left out and `Disallow`ed in robots.txt.
  - Per-route metadata derives from the catalogue (`metaForPath` →
    `app.name`/`app.description`), so it cannot drift from navigation (the
    `NavMenu` also renders `app.name`).
  - **Label mismatch:** the navigation label is `ReAct-Loop Example App`,
    not `ReAct Loop`. The Router's is `Router`, the only app without the
    "… Example App" suffix. `ReAct Loop` and `Router` are the `patternTag`
    values.
- **Verdict: kept.** The hostnames and the route set are correct. The naming
  inconsistency is **flagged for owner decision** (top list, item 5 in the final numbering). It
  comes from the Router catalogue entry, not from these three files.

### Shared generation service (`backend/app/services/generation.py`)

- **What changed:** `generate_text` gained a keyword-only
  `max_tokens: int | None = None`. It is added to the LiteLLM call only when
  it is not `None`, and the docstring documents it. (Phase 4 later re-wrapped
  one `raise` line; ruff format only.)
- **Intent:** to let the Router's single-call and search routes cap answer
  length without touching the Single-Call slice.
- **Evidence:** `backend/app/router/single_call_route.py`'s module docstring
  says so explicitly ("the one keyword this revision added to the shared
  service"). Both Router routes pass `max_tokens=MAX_ANSWER_TOKENS`.
- **Checks:**
  - The existing callers are `single_call/service.py` (×2),
    `rag/answer.py` and `services/shared.generate_text`. They call the same
    keyword-only entry point unchanged and omit `max_tokens`, so their LiteLLM
    kwargs are identical to before.
  - The service itself never touched the usage gate, before or after. Gating
    stays with the callers. Single-call and RAG still reserve through their
    existing paths. Router runs reserve 2 units via
    `shared.reserve_capability` + `allowance_holds.reserve` in
    `router/service.py` before any route runs. The search route's one search
    goes through the gated `web_search` capability.
  - No cap, limit constant or visitor-facing message changed in this file.
  - `uv run pytest backend/tests/services backend/tests/single_call backend/tests/router -q`:
    **448 passed, 1 deselected** (`live`).
- **Verdict: kept.** It is additive with a backward-compatible default and
  does not bypass the allowance gate.

### README (`README.md`)

- **What changed (`b22522b`):** "Nine" became "Ten" examples, with a router
  sentence. There is a Router feature bullet, Exa usage now lists the
  planning agent and the router's search route, and a note says that the
  router reads `dataset_embeddings` titles at startup. There is a Router
  "Using the app" walkthrough, the router's 2-unit reservation was added to
  `GENERATION_HOURLY_LIMIT`, its 1 search to `SEARCH_HOURLY_LIMIT`, and
  Playwright now lists "seven screens".
- **Intent:** the v9 Router documentation.
- **Evidence:** the commit message. The figures match the code: 2 units
  reserved and the second released on the evaluator route
  (`router/service.py`), 1 search per search-route run, and 5 runs per visit,
  as in `example-apps.ts`.
- **Checks against the real commands and the Phase 1 contract:**
  - `deploy/deploy.sh` and `uv run uvicorn …` are accurate.
  - Stale (not caused by `b22522b`): `GROQ_API_KEY` and `OPENAI_API_KEY` were
    still documented as optional. The test block said "no database or
    provider required" and `uv run mypy backend/app (strict on v5 code)`.
    The ruff/mypy paragraph described the per-path exclusion lists that
    Phases 4–5 removed.
  - The router note said that the presets endpoint "answers 503 'not ready'".
    That was true at `b22522b`, and Phase 2 superseded it.
- **Documentation only, fixed in this phase (README text only, no code):**
  1. Router startup note: the presets endpoint now reports
     `available: false`, and the screen shows the unavailable state with
     **Retry** (`POST /api/router/retry`).
  2. The tests/lint/typecheck block now reads
     `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`
     (strict over all of `backend/`). The pytest comment now says real
     `GROQ_API_KEY` + `OPENAI_API_KEY` are required.
  3. The ruff/mypy scope paragraph now says the v10 cleanup removed every
     exclusion.
  4. The test-suite paragraph now says real Groq/OpenAI keys are needed, the
     moderation endpoint is held offline by an autouse fixture, and `-m live`
     stays opt-in.
  5. The configuration table marks `GROQ_API_KEY` and `OPENAI_API_KEY` as
     required (✅). Missing or empty means startup fails naming the key, with
     no placeholder and no opt-out. The fail-closed text now describes an
     unreachable endpoint, not an unset key.
- **Verdict: kept.** The `b22522b` content is accurate. The stale text from
  earlier phases was fixed as documentation only.

### Claude Code settings (`.claude/settings.json`)

- **What changed:** the deny rules `Write(**/.env*)` and `Write(**/*.env)`
  were removed. Only `Edit(**/.env*)` and `Edit(**/*.env)` remain.
- **Intent:** unknown. A plausible reason is that it lets an assistant
  create a local `.env` (Phase 1 made real keys mandatory for every test
  run). It may also have been accidental.
- **Evidence:** none beyond the shared commit message. No phase or spec asks
  for it, and the CLAUDE.md invariant ("never create a `.env` file inside
  this repo") points the other way.
- **Checks:** no secrets, tokens or values. There is no `allow` list, so
  there are no over-broad permissions. The change *narrows* a guard rather
  than widening an allow.
- **Verdict: flagged for owner decision** (top list, item 4 in the final numbering). The guard
  around `.env` is weaker and the intent is unclear. It was not reverted
  (and this phase may not edit the file).

### Project configuration (`pyproject.toml`)

- **What changed (`b22522b`):** `version` went from `0.1.0` to `1.1.0`
  (also in `uv.lock`, `frontend/package.json` and `package-lock.json`, version
  fields only). `backend.app.api.router` and `backend.app.router.*` were
  added to the mypy `ignore_errors = false` override list, with a comment.
- **Intent:** the release version bump, and gating the v9 Router slice in
  the same way as the ReAct slice.
- **Evidence:** the commit message ("v1.1.0"). The version bump is
  owner-requested and intentional. The override comment names the Router
  slice.
- **Checks:** `b22522b` added **no dependency**; the `dependencies` and
  `dev` lists are byte-identical to `861c009`. Phase 5 superseded the Router
  override: all overrides except `sklearn.*` `ignore_missing_imports` were
  removed, `strict = true` and `files = ["backend"]`, so the Router modules
  fall under the strict default. The Phase 4 ruff gate has no exclusions.
  This is consistent.
- **Verdict: kept** (the version bump is kept as intentional).

### ReAct frontend test (`frontend/tests/react-loop.test.tsx`)

- **What changed:** one assertion. `exampleApps.at(-1)?.id === 'react_loop_example_app'`
  became "ReAct sits directly after `multi_agent_collaboration_example_app`".
  A comment explains that the Router (v9) was appended after it.
- **Intent:** the "newest last" catalogue rule now makes the Router last. The
  same adaptation was made to `collab.test.tsx` in v7.
- **Evidence:** the commit message and the comment. `router.test.tsx` now pins
  `exampleApps.at(-1)?.id === 'router_example_app'`, so "append, never
  insert" is still enforced by the suite. The new assertion is stricter about
  ReAct's position than "is last" would be, once anything is appended.
- **Checks:**
  - `npx vitest run tests/react-loop.test.tsx`: **13 passed**. There is no
    `skip`, `only` or `todo`.
  - The spec's ReAct assertions live in `tests/react-loop-run.test.tsx`
    (unchanged since `861c009`; 24 passed). They are: the 2-run session limit
    wording, the cycle counter advancing, the budget read from the server, a
    budget-exhausted card never worded as an answer, "names this app's limit,
    distinctly from the shared framework cap", and "keeps the two limit
    messages distinct". In `react-loop.test.tsx`, "2 of 2 runs remaining" and
    "no budget control" are intact. None was weakened or removed.
- **Verdict: kept.** The stale test title and the `collab.test.tsx` comment
  are a minor flag (top list, item 6 in the final numbering).

### After counts

| Gate | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 353 files already formatted |
| `uv run mypy` | Success: no issues found in 237 source files |
| `uv run pytest` | 2140 passed, 21 skipped, 6 deselected (unchanged) |
| `npx vitest run` | 38 files, 475 passed (unchanged) |

Files changed in this phase: `docs/v10-cleanup-review-note.md` (the
consolidated top list and this section), and `README.md` (the documentation-only
fixes above). `.claude/settings.json` and `CLAUDE.md` were not touched.

## Phase 8 — Acceptance: Router gating check and behaviour-preservation pass

Verification only. The one exception is this note (the summary, the results
table and the consolidated flagged list at the top, plus this section). No
source, test, config, CLAUDE.md or `.claude/settings.json` file was changed.

### Router gating check

This was a one-time check. No guard, hook or CI job was added. Each of the
three files below was first copied to the scratchpad and its sha256
recorded. Then the same throwaway was appended to each: an unused
`import fractions` and `_v10_throwaway: int = "not an int"`.

- `backend/app/router/cost_strip.py`
- `backend/app/api/router.py`
- `backend/tests/router/test_presets.py`

| Check | Result |
|---|---|
| `uv run ruff check .` | 6 errors, all in those three files: `F401` (`fractions` unused) and `E402` per file, at `cost_strip.py:185`, `api/router.py:275` and `test_presets.py:162` |
| `uv run mypy` | 3 errors, one `[assignment]` per file ("expression has type "str", variable has type "int""): `cost_strip.py:187`, `api/router.py:277`, `test_presets.py:164`, out of 237 files checked |

**Reverting the throwaways:**

- **Method:** each file was restored from its own pre-check copy, with no
  git checkout, restore or stash. That matters because `api/router.py`
  carries uncommitted Phase 2 changes.
- **Byte-identical:** `sha256sum -c` passed for all three, and `cmp` against
  each copy was identical.
- **`git status` unchanged:** the porcelain status of the three paths is
  identical to before the check. `cost_strip.py` and `test_presets.py` are
  clean. `api/router.py` shows only its Phase 2 diff (`+56/−23`, unchanged).
- **Nothing left behind:** `git grep --untracked "_v10_throwaway\|import
  fractions" -- backend` finds nothing.

So Ruff and mypy both gate the Router package, its API file and its tests.

### Gate configuration

`pyproject.toml` has no Ruff `extend-exclude`, `exclude`, `force-exclude` or
`per-file-ignores`. `[tool.mypy]` is `strict = true`, `files = ["backend"]`,
with no `exclude`, no `ignore_errors` and no `follow_imports`. Its only
override is `sklearn.*` `ignore_missing_imports = true`, which covers a
missing third-party stub and is not an exclusion. There is no `ruff.toml`,
`.ruff.toml`, `mypy.ini` or `setup.cfg`. (The stale comment above
`[tool.ruff]` is flag 9.)

### Route-id contract

- `backend/app/router/constants.py` has no diff against `b22522b`. The four ids
  are `deterministic_evaluator`, `single_call`, `retrieval` and
  `search_generation`. `ROUTE_COST_ORDER` lists them in that order, cheapest
  first.
- `frontend/src/api/router.ts` still declares
  `RouteId = 'deterministic_evaluator' | 'single_call' | 'retrieval' |
  'search_generation'`. No `-` line in its diff against `b22522b` touches
  `RouteId`.
- `uv run pytest backend/tests/router -q`: **314 passed, 1 deselected**
  (`live`). This includes `TestRouteIds` (spellings and cost order) and the
  catalogue's expected-route test.
- `npx vitest run tests/catalogue-consistency.test.tsx tests/router*.test.tsx`:
  **10 files, 71 passed**.

### Chained Calls contract

- `uv run pytest backend/tests/chained_calls -q`: **20 passed**.
- `test_chained_calls_api.py` (the critic-failure test, ~line 195) shows a
  critic `AgentLaneError` still gives:
  - HTTP **200**
  - `status == STATUS_CRITIQUE_FAILED`
  - `intermediate_output.text` equal to the first call's story
  - `final_output` and `quality_signal` set to `None`
  - a non-empty `notice`
- `STATUS_CRITIQUE_FAILED` is still `"critique_failed"`. Only its annotation
  (`ChainStatus`) changed, in Phase 5.

### Startup acceptance

All runs used `uvicorn` with one worker against Neon. A missing key was
simulated by overriding it to empty in the process env only. `.env` was not
read or touched.

- **(a)** `env GROQ_API_KEY= uv run uvicorn backend.app.main:app --workers 1`:
  exit code **1**, `RuntimeError: Invalid or missing configuration:
  GROQ_API_KEY.`
- **(b)** The same with `OPENAI_API_KEY=`: exit code **1**,
  `RuntimeError: Invalid or missing configuration: OPENAI_API_KEY.`
- **(c)** Both keys were set. A throwaway scratchpad launcher replaced
  `router.state.load_indexed_document_titles` with a wrapper that raised
  while a flag file existed, then called
  `uvicorn.run(..., workers=1)`.
  - **Startup:** the log showed `router_warmup_failed`, then `Application
    startup complete`.
  - **Other apps:** `/health` returned 200 `{"status":"ok","db":"connected"}`.
    These GET endpoints each returned 200:
    - `/api/rag/dataset`
    - `/api/embeddings/presets`
    - `/api/single-call/presets`
    - `/api/chained-calls/plan`
    - `/api/orchestrated/roster`
    - `/api/collab/identity-cards`
    - `/api/react/presets`
    - `/api/router/history`
  - **Presets:** `GET /api/router/presets` returned 200 with
    `available: false`, `route_descriptions: []`, a null block and a null
    sha256, and still served its 6 presets.
  - **Run refused:** a free-text `POST /api/router/run` returned 503
    `application/json` with `descriptions_not_ready` and "No run was used and
    nothing was held". There was no stream and no model call.
  - **Retry with the fault present:** `POST /api/router/retry` returned 503
    with `{code: "descriptions_not_ready", message}`.
  - **Retry after clearing the fault** (flag removed, no restart):
    `POST /api/router/retry` returned 200 `{"available":true}`. Presets then
    returned `available: true` with 4 routes.
  - **Cleanup:** the server was stopped. Ports 8000 and 5173 are free. The
    launcher, flag and logs were deleted.

### Full gate run

| Gate | Result |
|---|---|
| `uv run ruff check .` | All checks passed (exit 0) |
| `uv run ruff format --check .` | 353 files already formatted (exit 0) |
| `uv run mypy` | Success: no issues found in 237 source files (exit 0) |
| `uv run pytest` | 2140 passed, 21 skipped, 6 deselected (exit 0) |
| `npm run lint` (oxlint) in `frontend/` | exit 0. 0 errors, 13 warnings, all the pre-existing `react(only-export-components)` warnings in `src/routes.tsx` |
| `npx tsc --noEmit` in `frontend/` | exit 0 (also `-p tsconfig.app.json`: exit 0) |
| `npx vitest run` in `frontend/` | 38 files, 475 passed (exit 0) |
| `npm run build` in `frontend/` | exit 0. `tsc -b && vite build`, 765 modules (`dist/` is gitignored) |

The comparison with the baseline and the explanation of the count differences
are in "Baseline vs final" at the top.

### No change to caps, limits, messages or shapes

A scratchpad script compared every `backend/app/**/*.py` in the baseline
snapshot with the working tree by AST. It compared non-docstring string
literals, numeric literals and every module-level UPPER_CASE constant
(migrations excluded; Phase 4 had already AST-checked them). The only
differences are:

- `core/config.py`: the startup error text (Phase 1, intended; it now names
  the missing key). The new literals `"groq_api_key"`, `"openai_api_key"`,
  `"loc"` and `0` belong to the validator.
- `router/service.py` `NOT_READY_MESSAGE` and `api/router.py`
  `DESCRIPTIONS_NOT_READY`: the "temporarily unavailable" rewording (Phase 2,
  intended, flag 15). Also new: the `/retry` path and the `router_retry_*`
  log events.
- `main.py`: the `router_warmup_failed` log event. `router/state.py`: the old
  `router_route_descriptions_unavailable` log event was dropped (log only).
- `planning/service.py`: `"completed"` and `"failed"` now appear inside a
  `Literal[...]` annotation (Phase 5). The values are unchanged.

There is no numeric or constant change anywhere else. In particular:

- **Usage caps:** `generation_hourly_limit = 50`, `storage_hourly_limit = 75`,
  `search_hourly_limit = 15` and `planning_hourly_limit = 3` are identical to
  baseline.
- **Run limits:** ReAct `RUNS_PER_SESSION = 2`, Router `ROUTER_RUN_LIMIT = 5`,
  orchestrated `STEP_REQUEST_LIMIT = 3` and `RUN_CALL_BUDGET`, and planning
  `MAX_MODEL_CALLS = 18` with its step and request limits are all unchanged.
- **Frontend:** nothing under `frontend/src/data` or the orchestrated, ReAct
  and planning app directories changed. `frontend/src/` changed only in:
  - `api/router.ts` and `apps/router/RouterApp.tsx` (Phase 3 unavailable
    state; the other Router strings and the refusal codes are kept)
  - the new `apps/router/RouterUnavailable.tsx`
  - comment-only edits in `apps/collab/runState.ts` and `useCollabRun.ts`

The visitor messages that distinguish the per-app limit from the shared cap
are untouched. They are covered by the unchanged `react-loop-run.test.tsx`
and the Router/collab tests, all of which pass.

**Response shapes:** the only change is the spec'd Router presets field
`available: bool`, with the block and sha256 nullable only while unavailable,
plus the new `RetryResponse`. Every other route's schema is unchanged. The
non-docstring string literals, which include every field name and code, show
no other difference.

**Single worker:** `deploy/bws4-api.service` `ExecStart` still ends
`--workers 1` (with its MANDATORY comment). `deploy/README.md` keeps "The one
architectural rule". Nothing under `deploy/`, `backend/` or the README
mentions a multi-worker Gunicorn except the README's warning against it.

**Streaming sessions:** in every `backend/app/api/*.py` and
`router/service.py`, the counts of `async_session_factory()` (a stream opens
its own session) and `Depends(get_db_session)` are identical to baseline. The
`api/router.py` diff touches no session or `Depends` line.

### Result

Every verification item passed, so `.spec4/v10/IMPLEMENTED` was created. No
flagged item was resolved in this phase.
