# Deployment Plan

> **Revision v9: Router example app.** The v8 deployment is already provisioned and live on the netcup VPS. This plan carries it forward unchanged and revises only what the Router touches: the Coding Agent Guidance (the v9 phase files), one additive Alembic migration, the SSE verification for the new run endpoint, the Router's monitoring and eval conventions, and the Notes.

## Coding Agent Guidance

**Agent:** Claude Code (Anthropic, terminal-based)

### Starting the agent

Launch Claude Code from the BWS4 repository root. All `@` paths are relative to that directory.

```shell
cd /path/to/bws4
claude
```

If you start elsewhere and `cd` afterwards, `@` references can miss.

### Where the Spec4 files live

Spec4 has already written this round's artifacts into `.spec4/` in the project directory. This round is **v9**:

| Path | Contents |
|---|---|
| `.spec4/v9/vision.json` | Project vision statement |
| `.spec4/v9/stack.json` | Ratified technology stack |
| `.spec4/v9/code_review.json` | Brownfield review of the current deployment |
| `.spec4/v9/phases/phase1.md` … `phase7.md` | Seven phase files, each with JSON frontmatter and a prose body |
| `.spec4/v9/design/mock.html` | UI mock (only if Designer produced one) |

Confirm `.spec4/` and `deploy/` are not gitignored, since that can hide them from the agent.

### Referencing phase files

The `@` prefix pulls a file straight into context:

```
Read @.spec4/v9/phases/phase1.md and implement it. Consult
@.spec4/v9/stack.json for the ratified stack and
@.spec4/v9/code_review.json for what the deployed project already does.
```

### Recommended workflow

Work **one phase per session**, in order, and run `/clear` between phases. The docs recommend clearing aggressively. If you correct the same issue twice, `/clear` and restart with a sharper prompt, because `/compact` preserves a bad assumption.

For each phase:

1. Enter plan mode (`/plan`, or `Shift+Tab`). Have Claude read the phase file and propose its approach before it edits anything.
2. Review and correct the plan, then let it execute.
3. Run the phase's verification steps yourself and **paste the real output back into the session**.
   - Backend: `uv run pytest`, `uv run ruff check .`, `uv run mypy`, `uv run alembic upgrade head` (config at `backend/alembic.ini`)
   - Frontend: `cd frontend && npm run build`, `npm run lint`, `npm test`
4. Don't start the next phase until the current one is green.

Useful commands: `/context` (how full the window is), `/compact <instructions>` (for example "preserve the Router constants and test commands"), `Esc Esc` or `/rewind` (undo a phase that went wrong), `/memory` (edit `CLAUDE.md`).

| Phase | Focus | Deployment-relevant note |
|---|---|---|
| 1 | Router slice wired into API, database and frontend | Adds the Alembic migration for the two history tables. Review it before applying it. |
| 2 | Deterministic evaluator and unit table | Pure code, with no deployment impact. |
| 3 | Route descriptions, preset catalog, classification call | Keep model calls mocked in tests. |
| 4 | Run endpoint: moderation, allowance hold, dispatch, staged SSE | The new SSE surface. It is verified through Caddy after deploy. |
| 5 | Histories, typical-latency baseline, comparison re-run | No migration here. The tables exist from Phase 1. |
| 6 | Frontend: overview, knowledge panel, request flow, decision card | Same-origin `/api/*`. |
| 7 | Frontend: cost strip, re-run, agreement panel, limit states | Retries are disabled on quota-spending calls. |

### Revision-specific cautions

- **Phase 1 migration runs against live Neon.** Your `DATABASE_URL` points at the production database. The Router tables are additive, so the running app should be unaffected. Even so, read the generated migration before applying it. For local development, use a Neon branch so you aren't testing against production data.
- **Live calls spend shared allowance.** Phases 3–5 touch OpenRouter and Exa. Keep tests mocked and run any live check once, by hand. Real runs draw on the same hourly and daily caps your visitors use.
- **Enforce rules with hooks, not just `CLAUDE.md`.** `CLAUDE.md` is advisory, while hooks and permissions are enforced. Keep the `PreToolUse` deny rule for writes matching `*.env` inside the repo. The updated `CLAUDE.md` is under Configuration Files.
- **Export `VITE_SENTRY_DSN` into the build step.** The systemd `EnvironmentFile` does not reach `npm run build`, and Vite inlines this variable at build time. `deploy/deploy.sh` already handles it. Don't let an agent "simplify" that away in Phases 6–7.

---

## Target

### `web_client`

- **Type:** on-premise (self-hosted VPS)
- **Provider:** netcup — VPS 500 G12 (2 vCore, 4 GB DDR5 ECC, 128 GB NVMe, always-on)
- **Service:** Caddy 2 serving static files from `/srv/bws4/frontend/dist`, with SPA history fallback
- **Region:** netcup European datacenter, as chosen in v8 (unchanged)
- **Transport:** HTTPS only. Caddy handles Let's Encrypt issuance and renewal and the HTTP→HTTPS redirect.
- **CORS:** not applicable. It serves the browser origin itself.

**Revision impact:** the Router adds route-based lazy-loaded chunks to the Vite build. `npm run build` in `deploy.sh` produces them and Caddy serves them unchanged. The Router overview, preset UI and agreement panels call same-origin `/api/*` only.

### `api`

- **Type:** on-premise (self-hosted VPS), same host as `web_client`
- **Provider:** netcup — same VPS 500 G12
- **Service:** Uvicorn under `uv`, supervised by systemd (`bws4-api`), reverse-proxied by Caddy
- **Transport:** HTTPS only, terminated by Caddy. Uvicorn binds `127.0.0.1:8000` only and is never directly reachable.
- **CORS:** only the single non-wildcard `CORS_ORIGIN` (`https://bw.spec4.ai`). It is retained unchanged. In production the SPA and API share an origin, so the policy is exercised chiefly in local development.

**Runtime:** Python 3.12, `--workers 1`, async concurrency only. This is mandatory: the embedding model, fitted PCA projection, in-process peer message bus, ReAct duplicate-guard cache and Router route descriptions are all per-process state. The Router's route descriptions, including the RAG subject list read from the retriever's indexed document titles, are derived once at startup, so a release re-derives them at boot.

**Router endpoints on this surface** (all under the existing `/api/*` proxy; confirm exact paths in the generated OpenAPI at `/docs` after Phase 4):

| Endpoint | Method | Behaviour |
|---|---|---|
| Router run | POST | Staged SSE: decision card → routed answer **or** low-confidence card → cost strip → end-of-run event. |
| Router presets | GET | Presets with route descriptions, decision margin and cost order. |
| Router agreement history | GET | Per-preset agreement history and typical-latency baseline. |
| Router comparison re-run | POST | One re-run through the expected route. |

A run that is flagged by moderation, fails closed, or is refused because the shared cap is too close returns an **ordinary error response, not a stream**, because the run never began. Smoke tests must treat both response shapes as correct behaviour.

---

## Containerization

- **Enabled:** No (unchanged)

The Router is more Python on the same single `uv`-managed process, so there is nothing to containerize. `uv` pins Python 3.12 and locks dependencies, and systemd provides supervision.

## CI/CD

- **Enabled:** No (unchanged)

Quality gates (`ruff`, `mypy`, `pytest`, `vitest`) remain developer-run before push. Release delivery is `deploy/deploy.sh`, run on the VPS. The new Alembic migration is applied by its existing `alembic upgrade head` step.

## Environment

**Required variables** (**no additions, removals or renames in this revision**; all seven phases confirm this):

- `DATABASE_URL`: Neon Postgres with pgvector. The Router's two history tables are created here by Alembic.
- `OPENROUTER_API_KEY`: shared model chain, including the Router's classification call and its routed generation calls.
- `GROQ_API_KEY`: carried in the existing contract.
- `EXA_API_KEY`: used by the Router's `search_generation` route through the shared Exa wrapper.
- `OPENAI_API_KEY`: moderation gate. The Router's free-text moderation depends on it, and a bad key makes every run fail closed.
- `CORS_ORIGIN`: `https://bw.spec4.ai`. It must fail clearly when missing.

**Optional:**

- `SENTRY_DSN`: backend error tracking, runtime.
- `VITE_SENTRY_DSN`: frontend error tracking, **build-time only**.

**Not environment variables:** `EVALUATOR_MAX_INPUT_LENGTH`, `EVALUATOR_MAX_NESTING_DEPTH`, `LATENCY_MEDIAN_WINDOW_N` and `MIN_OBSERVATIONS` live in `backend/app/router/constants.py`. Changing them is a code change and a redeploy.

**Secrets management:** unchanged. A single root-owned `0600` file at `/etc/bws4/bws4.env`, outside the repository, loaded via systemd `EnvironmentFile=`. Never committed. Committed files reference variable names only.

## Monitoring

- **Error tracking:** Sentry (`SENTRY_DSN` runtime, `VITE_SENTRY_DSN` build-time), as already wired. **New for this revision:** add a Sentry alert rule that emails you when moderation-provider errors appear. The Router's moderation gate fails closed, so a moderation outage or invalid `OPENAI_API_KEY` blocks every Router run. Nothing else would tell you.
- **Metrics:** systemd journal via `journalctl` (`SystemMaxUse=500M`), with structlog JSON. No external metrics platform.
- **Availability:** Better Stack free tier with the two existing monitors (`https://bw.spec4.ai/` and `https://bw.spec4.ai/api/health`). They detect host-level and process-level failure but **not** a Router-specific moderation failure. No Router monitor is added.
- **Model observability:** existing tooling only. Quota spend goes to `usage_limits` / `service_log_entries` in Neon. Routing agreement and latency go to the Router's two history tables. Run detail goes to structlog JSON in the journal. No hosted LLM-observability service.
- **Eval cadence:** a **manual pre-change check**, with no schedule. Before changing the Router's route descriptions, classification prompt or the shared model chain in `model_registry.py`, run the preset catalog once through the live endpoint. Compare the results with the stored agreement history, and deploy only if agreement holds. See Deployment Step 8.
- **Feedback loop:** passive signals only. These are the agreement history, the comparison re-run records, the per-preset typical-latency baseline and Sentry, all reviewed during the pre-change check. An explicit thumbs up/down control is on the roadmap.
- **Safety/guardrails:** code-enforced in application code and not an infrastructure matter. The pieces are the free-text moderation gate that runs before other model calls, the fail-closed behaviour, the 2-unit allowance hold against the shared caps, zero output retries on the classification call, and the closed-grammar evaluator with input-length and nesting-depth limits. The deployment's contribution is the Sentry alert path above.

## Deployment Steps

The VPS provisioning from v8 (SSH hardening, `ufw`, swapfile, journald caps, `uv`, Node 20, Caddy from Debian, `/etc/bws4/bws4.env`, the systemd unit, the Caddyfile, DNS and Let's Encrypt, Better Stack, and the Render cutover) is **already complete and is not repeated**. The steps below cover only this revision's release.

### 1. Run the quality gates locally

Run these before each phase is considered done, and again once all seven are complete.

```shell
cd /path/to/bws4
uv run ruff check .
uv run mypy
uv run pytest
cd frontend
npm run lint
npm test
npm run build
```

### 2. Review the Phase 1 migration before it touches production

The Router adds two append-only history tables (agreement records and latency observations). Check that the migration only creates tables and indexes, and drops or alters nothing existing.

```shell
cd /path/to/bws4/backend
ls -t app/db/migrations/versions/ | head -n 3
git diff --stat -- app/db/migrations/versions/
```

For local testing, point `DATABASE_URL` at a Neon branch, not at production:

```shell
uv run alembic upgrade head
uv run alembic current
```

### 3. Push to the Git remote

Production pulls from the remote, so push once the gates are green.

```shell
git status
git push
```

### 4. Choose a quiet window

A release restarts the single process. In-flight SSE streams are cut and the warm state (embedding model, PCA projection, Router route descriptions) is rebuilt at boot. Deploy when traffic is low, and optionally post a notice on the Better Stack status page.

### 5. Run the release on the VPS

`deploy.sh` applies the migration **before** it restarts the service. The old process keeps running against a schema that only gained new tables, which is safe.

```shell
ssh root@<VPS_IP>
export VITE_SENTRY_DSN=<your frontend DSN, if you use frontend Sentry>
/srv/bws4/deploy/deploy.sh
```

Expect git pull → `uv sync --frozen` → `npm ci && npm run build` → `alembic upgrade head` → restart → health wait. This time `alembic upgrade head` should apply the Router migration, and only that one.

### 6. Verify the migration and the service

```shell
cd /srv/bws4/backend
set -a; . /etc/bws4/bws4.env; set +a
/root/.local/bin/uv run alembic -c alembic.ini current
unset DATABASE_URL OPENROUTER_API_KEY GROQ_API_KEY EXA_API_KEY OPENAI_API_KEY CORS_ORIGIN SENTRY_DSN

systemctl status bws4-api --no-pager
journalctl -u bws4-api -n 60 --no-pager
ps -ef | grep uvicorn | grep -v grep   # confirm a single worker
```

### 7. Verify the Router through Caddy

Presets cost no allowance. Confirm the exact paths against `https://bw.spec4.ai/docs` first.

```shell
curl -sS https://bw.spec4.ai/api/router/presets | head -c 600
```

Then verify that the run endpoint **streams progressively** through the edge. A buffering misconfiguration still returns HTTP 200, so a status code alone won't catch it. Run this **once**. A run spends up to two model-call units from the shared caps.

```shell
curl -N -sS -X POST https://bw.spec4.ai/api/router/run \
  -H 'Content-Type: application/json' \
  -d '{"request":"<a preset request from the presets response>"}'
```

You should see the decision card first, then the routed answer (or the low-confidence card), then the cost strip, then an end-of-run event with units spent and released. The request body shape above is a placeholder, so use the schema shown in `/docs`. Then open the Router page in a browser, hard-refresh, and click through one preset end to end. Check that the first visit after the restart has no warm-up wait.

### 8. Pre-change check for Router prompts and the model chain (ongoing procedure)

Run this before **any** change to the route descriptions, the classification prompt or the shared chain in `model_registry.py`. It is not part of the first release.

1. Read the current per-preset agreement history from the Router's agreement endpoint and record the baseline.
2. Apply the change locally, run the quality gates, and deploy during a quiet window.
3. Run each preset once through the live endpoint, which spends at most two units per run, so it is a bounded cost. Compare agreement with the baseline.
4. If agreement drops, revert with `git revert <sha>`, push, and rerun `deploy.sh`.

### 9. Add the Sentry alert for moderation failures

In Sentry, create an alert rule on the BWS4 backend project. It should trigger on new error events from the moderation path (filter on the moderation module or logger name in the event) and email you. To test it safely, briefly set an invalid `OPENAI_API_KEY` in `/etc/bws4/bws4.env`, restart, trigger one Router run (it should return an ordinary error response), and confirm the alert fires. **Then restore the real key and restart.**

## Configuration Files

No new deployment files are needed for the Router. The files below are the established ones, carried forward. `deploy/deploy.sh`, `deploy/Caddyfile` and `deploy/bws4-api.service` are unchanged. `CLAUDE.md` gains a Router section.

### `deploy/bws4-api.service`

```ini
[Unit]
Description=BWS4 API (FastAPI/Uvicorn)
Documentation=https://bw.spec4.ai
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=root
WorkingDirectory=/srv/bws4/backend

# Root-owned 0600 file OUTSIDE the repository tree.
# Supplies: DATABASE_URL, OPENROUTER_API_KEY, GROQ_API_KEY, EXA_API_KEY,
#           OPENAI_API_KEY, CORS_ORIGIN, and optional SENTRY_DSN.
EnvironmentFile=/etc/bws4/bws4.env

Environment=PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=PYTHONUNBUFFERED=1

# Single worker is mandatory, not incidental: the embedding model, fitted PCA
# projection, in-process message bus, ReAct duplicate-guard cache and Router
# route descriptions are all per-process state.
ExecStart=/root/.local/bin/uv run uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --no-access-log

Restart=always
RestartSec=3

TimeoutStartSec=300
TimeoutStopSec=30

StandardOutput=journal
StandardError=journal
SyslogIdentifier=bws4-api

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/srv/bws4

[Install]
WantedBy=multi-user.target
```

### `deploy/Caddyfile`

The canonical-origin block, already live. `handle /api/*` precedes the SPA fallback. `flush_interval -1` keeps the SSE example apps, **now including the Router run endpoint**, streaming progressively. `response_header_timeout 5m` comfortably covers the Router's longest run.

```
bw.spec4.ai {
	encode zstd gzip

	handle /api/* {
		reverse_proxy 127.0.0.1:8000 {
			flush_interval -1
			transport http {
				response_header_timeout 5m
				dial_timeout 5s
			}
		}
	}

	handle {
		root * /srv/bws4/frontend/dist
		try_files {path} /index.html
		file_server

		@hashed path_regexp \.[0-9a-f]{8,}\.(js|css|woff2?|png|jpe?g|svg|webp)$
		header @hashed Cache-Control "public, max-age=31536000, immutable"

		@shell path /index.html /
		header @shell Cache-Control "no-cache, must-revalidate"
	}

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
		-Server
	}

	log {
		output file /var/log/caddy/bws4.log {
			roll_size 20MiB
			roll_keep 5
		}
		format json
	}
}
```

### `deploy/deploy.sh`

```bash
#!/usr/bin/env bash
#
# BWS4 release script — run ON the VPS as root.
#
#   git pull -> uv sync -> npm ci && npm run build -> alembic upgrade head
#   -> systemctl restart bws4-api
#
# Runtime secrets are NOT handled here: they reach the application through
# systemd's EnvironmentFile at /etc/bws4/bws4.env.
#
# BUILD-time variables required by Vite must be exported into the environment
# of the `npm run build` step, because the systemd EnvironmentFile does not
# apply to the build. VITE_SENTRY_DSN is the only such variable.
#
# A release is a brief restart. The embedding model load, PCA projection fit
# and Router route-description derivation are re-paid at boot, and in-flight
# SSE streams are cut.

set -euo pipefail

REPO_DIR="/srv/bws4"
FRONTEND_DIR="${REPO_DIR}/frontend"
BACKEND_DIR="${REPO_DIR}/backend"
DIST_DIR="${FRONTEND_DIR}/dist"
SERVICE="bws4-api"
ENV_FILE="/etc/bws4/bws4.env"
UV="/root/.local/bin/uv"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31mFAILED:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "must run as root"
[[ -f "$ENV_FILE" ]] || fail "missing ${ENV_FILE}"
command -v "$UV" >/dev/null || fail "uv not found at ${UV}"
command -v npm >/dev/null || fail "npm not found"

log "Pulling latest revision"
cd "$REPO_DIR"
git pull --ff-only
git log --oneline -1

log "Syncing Python dependencies"
cd "$REPO_DIR"
"$UV" sync --frozen

log "Building frontend bundle"
cd "$FRONTEND_DIR"
if [[ -n "${VITE_SENTRY_DSN:-}" ]]; then
  echo "    VITE_SENTRY_DSN is set; frontend Sentry will be enabled"
  export VITE_SENTRY_DSN
else
  echo "    VITE_SENTRY_DSN unset; frontend Sentry will be disabled"
fi
npm ci
npm run build
[[ -f "${DIST_DIR}/index.html" ]] || fail "build produced no ${DIST_DIR}/index.html"

log "Applying database migrations (external Neon)"
cd "$BACKEND_DIR"
set -a; . "$ENV_FILE"; set +a
"$UV" run alembic -c alembic.ini upgrade head
unset DATABASE_URL OPENROUTER_API_KEY GROQ_API_KEY EXA_API_KEY \
      OPENAI_API_KEY CORS_ORIGIN SENTRY_DSN

log "Restarting ${SERVICE}"
systemctl restart "$SERVICE"

log "Waiting for warm-up (model load + PCA fit)"
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null --max-time 3 http://127.0.0.1:8000/docs; then
    log "Service healthy after ${i}s"
    systemctl status "$SERVICE" --no-pager | head -n 12
    log "Deploy complete"
    exit 0
  fi
  sleep 1
done

journalctl -u "$SERVICE" -n 60 --no-pager
fail "service did not become healthy within 60s"
```

### `CLAUDE.md` (repo root)

Updated with a Router section. Copy it over the existing file.

```markdown
# BWS4 — Agent Context

## Hard invariants

- **Secrets never enter the repository.** Runtime configuration lives in
  `/etc/bws4/bws4.env` on the VPS — root-owned, chmod 0600, outside the
  repository tree. Never create a `.env` file inside this repo. Committed
  files reference environment variable NAMES only, never values.
- **The API runs with `--workers 1`.** This is a requirement, not a default.
  The loaded embedding model, the fitted PCA projection, the in-process peer
  message bus, the ReAct duplicate-guard cache and the Router's route
  descriptions are all per-process state. Never add workers, never suggest
  Gunicorn with multiple workers.
- **Postgres is external.** Neon + pgvector, unchanged by the VPS migration.
  Never propose installing Postgres on the host.

## Router example app (v9)

- The Router adds NO new environment variables and NO new API keys. It reuses
  OPENROUTER_API_KEY, EXA_API_KEY, OPENAI_API_KEY (moderation), DATABASE_URL,
  CORS_ORIGIN and optional SENTRY_DSN. Tuning constants live in
  backend/app/router/constants.py, not in the environment.
- Model slugs come only from the shared registry
  (backend/app/services/model_registry.py / agent_runtime.py). Never hard-code
  a slug and never add a Router-only model chain.
- The Router reuses the existing single-call, RAG retriever and Exa wrapper
  services unmodified. Do not add a tool registration or MCP.
- The quota gate is a direct service-layer call, never a model-exposed tool.
- Moderation fails closed: a flagged, failed or cap-refused request returns an
  ordinary error response, not an SSE stream.
- Tests must mock model and Exa calls. Live calls spend the shared free-tier
  caps that production visitors use.
- Alembic migrations run against the live Neon database. Keep them additive.
- The Router run endpoint is POST + SSE and must not be buffered at the edge.

## Deployment shape

- Host: netcup VPS 500 G12, Debian 13 (trixie), 2 vCore / 4 GB / 128 GB NVMe
- Repo on host: `/srv/bws4`; frontend build output: `/srv/bws4/frontend/dist`
- Caddy serves `dist/` with SPA history fallback, reverse-proxies `/api/*`
  to `127.0.0.1:8000` with `flush_interval -1`
- systemd unit: `bws4-api`; release script: `deploy/deploy.sh`
- Canonical origin: `https://bw.spec4.ai`

## Environment contract (names only)

Required: `DATABASE_URL`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`,
`EXA_API_KEY`, `OPENAI_API_KEY`, `CORS_ORIGIN`
Optional: `SENTRY_DSN` (runtime), `VITE_SENTRY_DSN` (build-time only —
the systemd EnvironmentFile does NOT reach `npm run build`)

## Quality gates (developer-run, no CI)

`ruff`, `mypy`, `pytest`, `vitest` — run before push.
```

## Notes

### Cost

No change. The Router adds no new services.

| Item | Cost |
|---|---|
| netcup VPS 500 G12 (12-month) | ~€5.91/mo (~$6.81) |
| Neon Postgres + pgvector (two extra small history tables) | Free tier |
| Caddy, systemd, Debian | Free |
| Sentry | Free (5k errors/mo, 1 user) |
| Better Stack | Free (10 monitors, 3-min checks) |
| **Total** | **~€6/mo** |

A full Router run is at most two model-call units on free-tier models. Exa spend occurs only on the `search_generation` route, and it counts against the shared caps.

### Non-functional goals

**Addressed by this deployment:**

- **`nfr_model_backed_examples_show_progress_as_each_step_completes`**: the stack claims this through `sse-starlette` and `@microsoft/fetch-event-source`. The deployment's part is keeping the edge from undoing it. `flush_interval -1` on the `/api/*` proxy lets the Router's staged events (decision card, answer, cost strip, end-of-run) reach the browser as they are produced. Step 7 verifies this with `curl -N`.
- **`nfr_measured_history_survives_restarts`**: claimed by `primary_store` and the Router's agreement and latency records. The deployment's part is that the history tables live in external Neon, not on the VPS, so they survive restarts, redeploys and host loss. Step 5 applies the migration that creates them.

**Not claimed by any stack component, addressed on their own terms:**

- **`nfr_the_first_visit_is_as_fast_as_any_later_visit__with_no_cold_start_delay`**: the stack did not claim this. The always-on host with `Restart=always` loads the embedding model, the PCA projection and the Router's route descriptions once at boot, so no visitor pays a cold-start cost. A release re-pays that cost briefly at boot (Step 4).
- **`nfr_the_site_is_always_available_at_a_secure_public_address`**: the stack did not claim this. Caddy provides automatic TLS with in-process renewal, systemd restarts a crashed process, and the two Better Stack monitors watch the host and the API. Those monitors cannot see a Router-only moderation failure, which is why Step 9 adds a Sentry alert.
- **`nfr_example_app_pages_respond_immediately_to_input__apart_from_model_and_search_waits`**: the stack did not claim this. The deployment only helps by serving the per-app code-split chunks with immutable cache headers. Input responsiveness itself is frontend code.
- **`nfr_hidden_information_between_agents_is_enforced_by_structure__not_by_instruction`**: the stack did not claim this, and it is not an infrastructure matter. It belongs to the coding agent's code. The single-worker invariant keeps the in-process bus coherent, but hosting does not enforce opacity.

**The coding agent's to satisfy, not this deployment's:**

- `nfr_usage_is_bounded_per_app_per_visit_and_by_shared_hourly_and_daily_caps…` and `nfr_limit_messages_clearly_state_which_limit_was_reached`: the allowance hold, `router_run_allowance` and the shared quota gate. No hosting choice caps API spend.
- `nfr_past_results_stay_visible_after_limits_are_reached`: client-side `router_run_allowance` localStorage handling.
- `nfr_every_example_app_follows_the_same_overall_layout…`: Tailwind CSS and component structure.
- `nfr_educational_content_is_understandable_to_developers_new_to_agentic_patterns`: the educational overview content.

### Operational cautions

- **Releases cut SSE streams.** The single worker cannot be rolled. Deploy in quiet windows. The v8 position stands that zero-downtime updates would need a stack change, such as an out-of-process model server or an externalised bus, and not a deployment change.
- **Router fails closed on moderation.** An invalid or revoked `OPENAI_API_KEY`, or a moderation outage, blocks every Router run with ordinary error responses. The Sentry alert from Step 9 is how you find out.
- **Smoke tests spend shared allowance.** Keep live Router runs to a handful, and do them in a quiet window.
- **Migration expectation.** On the first release after Phase 1, `alembic upgrade head` should apply exactly the Router migration. If it tries to alter anything else, stop and investigate a revision mismatch before restarting.

### Roadmap — recorded, not provisioned

- `remark-gfm` (optional library)
- `Playwright` (deferred library). If adopted, it would be the natural forcing function for CI.
- **CI/CD.** Still out of scope. A GitHub Actions run of the existing gates that then SSHes `deploy.sh` is the smallest sensible step.
- **Router feedback control.** An explicit thumbs up/down on the decision card. It needs a new endpoint, table, migration, UI and abuse protection, none of which any v9 phase includes.
- **Scheduled Router eval.** A weekly cron or systemd timer would catch silent upstream model drift. It was deferred in favour of the manual pre-change check, because it spends shared allowance.
- **Third Better Stack monitor on the Router presets endpoint.** Considered and skipped. It would confirm the Router is mounted but would not detect a failing moderation key.
- **netcup snapshots and backups.** Unchanged from v8. Neon holds all durable data, and the one irreplaceable file on the host is `/etc/bws4/bws4.env`, which you should keep in your password manager.