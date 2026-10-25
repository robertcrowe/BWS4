# Deployment Plan

> **Revision v10: Codebase quality and config cleanup.** The v9 deployment is provisioned and live on the netcup VPS. This plan carries it forward unchanged and revises only what v10 touches. That means the Coding Agent Guidance (the v10 phase files), the startup credential contract, the Router's best-effort warm-up and its monitoring, `deploy/deploy.sh`, `CLAUDE.md`, and the Notes.

## Coding Agent Guidance

**Agent:** Claude Code (Anthropic, terminal CLI)

### Starting the agent

Launch Claude Code from the BWS4 repository root. All `@` paths are relative to that directory.

```shell
cd /path/to/bws4
claude
```

### Where the Spec4 files live

Spec4 has already written this round's artifacts into `.spec4/` in the project directory. This round is **v10**:

| Path | Contents |
|---|---|
| `.spec4/v10/vision.json` | Project vision statement |
| `.spec4/v10/stack.json` | Ratified technology stack |
| `.spec4/v10/code_review.json` | Brownfield review of the current deployment |
| `.spec4/v10/phases/phase1.md` … `phase8.md` | Eight phase files, each with JSON frontmatter and a prose body |
| `.spec4/v10/design/mock.html` | UI mock (only if Designer produced one) |

Confirm `.spec4/` and `deploy/` are not gitignored, since that can hide them from the agent.

### Referencing phase files

The `@` prefix pulls a file into context. Explicit paths are preferred over letting the agent search.

```
Read @.spec4/v10/phases/phase1.md and implement it. Consult
@.spec4/v10/stack.json for the ratified stack and
@.spec4/v10/code_review.json for what the project already does.
```

### Recommended workflow

Work **one phase per session**, in order.

1. Enter plan mode (`Shift+Tab` twice, or `/plan`). Have Claude read the phase file and propose its approach before it edits anything.
2. Review and correct the plan. When you approve it, the CLI offers a "Yes, clear context" option. It drops the conversation history and keeps the approved plan, which suits eight sequential phases.
3. Run the phase's verification steps yourself and **paste the real output back into the session**.
   - Backend: `uv run ruff check .`, `uv run mypy`, `uv run pytest`, `uv run alembic upgrade head` (config at `backend/alembic.ini`)
   - Frontend: `cd frontend && npm run lint && npm test && npm run build`
4. Commit the phase, then run `/clear`. Don't start the next phase until the current one is green.

Prefer `/clear` to `/compact`, because `/compact` can carry a wrong assumption forward. If you need to carry state, write progress to a file, run `/clear`, and resume from that file. Use `Esc Esc` or `/rewind` to undo a phase that went wrong, `/context` to check how full the window is, and `/memory` to edit `CLAUDE.md`.

| Phase | Focus | Deployment-relevant note |
|---|---|---|
| 1 | Baseline gates and required credential contract | `GROQ_API_KEY` and `OPENAI_API_KEY` become enforced at startup. Release check added to `deploy.sh`. |
| 2 | Best-effort Router warm-up and backend unavailable state | Keep `--workers 1`, because route-description state is per-process. **Must log a warm-up failure at ERROR level or capture the exception**, since the Sentry alert depends on it. |
| 3 | Router unavailable page state and Retry button | Same-origin `/api/router/*`. Confirm the presets availability field name and the Retry endpoint in `/docs`. |
| 4 | Whole-backend ruff gate | Config only. `[tool.ruff]` ends with no `extend-exclude`. |
| 5 | Whole-backend mypy strict gate | Config only. No `exclude`, no per-module `ignore_errors`, and no `files` list that omits parts of `backend/`. |
| 6 | Render sweep and startup docstring | Docs and comments only. Must not alter live deployment behaviour. |
| 7 | Unrecorded-edits review note | Read-only except for documenting. |
| 8 | Acceptance: Router coverage and behaviour-preservation | The `-m live` smoke run is opt-in and spends shared allowance. |

### Revision-specific cautions

- **Real keys for pytest vs. the "no `.env` in the repo" rule.** Phases 1, 4 and 8 need real `GROQ_API_KEY` and `OPENAI_API_KEY` values for pytest runs. They suggest the shell or a repo-root `.env`. Your invariant forbids a repo `.env`. **Export the keys in the shell that launches `claude`** and don't create the file. Keep the `PreToolUse` deny rule on `*.env` writes inside the repo. Hooks are enforced by Claude Code, while `CLAUDE.md` is only advisory.
- **No exclusions to get green.** Phases 4 and 5 must end with no ruff `extend-exclude`, no mypy `exclude` and no `ignore_errors` overrides. If the agent proposes an exclusion, reject it and have it fix the code instead.
- **Phase 6 leaves live deployment files alone.** The Render sweep must not change `deploy/Caddyfile`, `deploy/bws4-api.service`, the `--workers 1` rule or the `deploy.sh` release logic. Only stale Render references and the startup docstring change.
- **Commit or stash first.** The code review found uncommitted changes (12 modified, 68 untracked files). The VPS pulls from the remote, so resolve this before the first deployment step.
- **Keep the `VITE_SENTRY_DSN` export in `deploy.sh`.** The systemd `EnvironmentFile` does not reach `npm run build`. Don't let an agent "simplify" it away.

---

## Target

Both surfaces are unchanged from v9.

### `web_client`

- **Type:** on-premise (self-hosted VPS)
- **Provider:** netcup, VPS 500 G12 (2 vCore, 4 GB RAM, 128 GB NVMe, always-on)
- **Service:** Caddy 2 serving static files from `/srv/bws4/frontend/dist`, with SPA history fallback
- **Region:** netcup European datacenter, as chosen in v8 (unchanged)
- **Transport:** HTTPS only. Caddy handles Let's Encrypt issuance and renewal and the HTTP→HTTPS redirect.
- **CORS:** not applicable. It serves the browser origin itself.

**Revision impact:** Phase 3 adds a Router "unavailable" page state and a Retry button to the frontend. `npm run build` in `deploy.sh` rebuilds it and Caddy serves it unchanged. It calls same-origin `/api/router/*` only.

### `api`

- **Type:** on-premise (self-hosted VPS), same host as `web_client`
- **Provider:** netcup, same VPS 500 G12
- **Service:** Uvicorn under `uv`, supervised by systemd (`bws4-api`), reverse-proxied by Caddy
- **Transport:** HTTPS only, terminated by Caddy. Uvicorn binds `127.0.0.1:8000` only.
- **CORS:** only the single non-wildcard `CORS_ORIGIN` (`https://bw.spec4.ai`), retained unchanged.

**Runtime:** Python 3.12, `--workers 1`, async concurrency only. This remains mandatory because the embedding model, PCA projection, message bus, ReAct duplicate-guard cache and Router route descriptions are all per-process state.

**What changes at boot:**
- **Required credentials.** Startup refuses to proceed if `GROQ_API_KEY` or `OPENAI_API_KEY` is missing.
- **Best-effort warm-up.** The lifespan warm-up steps (embedding model load, PCA fit and Router route-description derivation) are each best-effort. A failure is logged and the API still boots.
- **Router unavailable state.** While route descriptions are not ready, the Router presets response reports availability as false. A run that cannot begin returns an ordinary error response, not a stream, and reserves no usage units.
- **Retry action.** It re-attempts the route-description warm-up without an API restart. It does not re-run the embedding model load or PCA fit, which stay boot-only.

Confirm the exact paths and field names in the generated OpenAPI at `https://bw.spec4.ai/docs` after Phase 3.

---

## Containerization

- **Enabled:** No (unchanged). `uv` pins Python 3.12 and locks dependencies, and systemd provides supervision.

## CI/CD

- **Enabled:** No (unchanged)
- **Release delivery:** `deploy/deploy.sh`, run on the VPS.
- **Quality gates:** `ruff`, `mypy`, `pytest`, `oxlint`, `tsc` and `vitest` remain developer-run before push. After Phases 4 and 5, ruff and mypy cover the whole backend with no exclusions.

## Environment

**Required variables** (**no additions, removals or renames in this revision**):

- `DATABASE_URL`: Neon Postgres with pgvector.
- `OPENROUTER_API_KEY`: shared model chain.
- `GROQ_API_KEY`: **now enforced at startup**. The service will not boot without it.
- `EXA_API_KEY`: Exa web search.
- `OPENAI_API_KEY`: **now enforced at startup**. It is also the moderation credential, and a bad key makes moderated runs fail closed.
- `CORS_ORIGIN`: `https://bw.spec4.ai`.

**Optional (runtime):** `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `MODERATION_HASH_SALT`, `PORT`, `EMBEDDING_MODEL_NAME`, and the existing limit and `REACT_*` tuning variables.

**Build-time only:** `VITE_API_BASE_URL`, `VITE_SENTRY_DSN`. They must be exported in the shell that runs `npm run build`.

**Secrets management:** unchanged. A single root-owned `0600` file at `/etc/bws4/bws4.env`, outside the repository, loaded via systemd `EnvironmentFile=`. Never committed.

**New release guard:** `deploy.sh` now checks that `GROQ_API_KEY` and `OPENAI_API_KEY` are present and non-empty in `/etc/bws4/bws4.env` **before** `git pull` and before the restart. A missing key aborts the release while the old process is still serving. Without this guard, systemd would restart-loop (`Restart=always`, `RestartSec=3`) on a process that refuses to start.

## Monitoring

- **Error tracking:** Sentry (`SENTRY_DSN` runtime, `VITE_SENTRY_DSN` build-time), as already wired. **New for this revision:** a Sentry alert that emails you when the Router warm-up failure event appears (Step 9). It depends on Phase 2 logging that failure at ERROR level or capturing the exception, so confirm this in the Phase 2 review. The v9 moderation-failure alert remains.
- **Metrics:** systemd journal via `journalctl` (`SystemMaxUse=500M`), with structlog JSON. No external metrics platform.
- **Availability:** Better Stack free tier, with the two existing monitors (`https://bw.spec4.ai/` and `https://bw.spec4.ai/api/health`). They cannot see a failed Router warm-up, because the API boots healthy either way. **New:** after each restart, `deploy.sh` reads the presets availability flag and prints a loud warning if it is false. A third monitor was considered and not added.
- **Model observability:** unchanged from v9. v10 adds no new model-calling feature. Quota spend goes to `usage_limits` / `service_log_entries` in Neon, Router history goes to its two history tables, and run detail goes to structlog JSON.
- **Eval cadence:** unchanged. The manual pre-change check before altering Router route descriptions, the classification prompt or the shared chain in `model_registry.py` still applies. Phase 8's behaviour-preservation pass and its opt-in `-m live` smoke run serve as this round's acceptance check.
- **Feedback loop:** unchanged, with passive signals only. The Retry button's usage is not instrumented.
- **Safety/guardrails:** unchanged and code-enforced. The deployment's contribution is the Sentry alert paths.

## Deployment Steps

The VPS provisioning from v8 and the Router release from v9 are **already complete and not repeated**. The steps below cover only this revision's release.

### 1. Commit or stash the working tree

The code review found uncommitted changes. Production pulls from the remote, so clean this up first.

```shell
cd /path/to/bws4
git status
git add -A && git commit -m "v10: <describe>"   # or: git stash
```

### 2. Run the quality gates locally

Export the real keys in your shell. Don't create a repo `.env`.

```shell
cd /path/to/bws4
export GROQ_API_KEY=<real key>
export OPENAI_API_KEY=<real key>
# also export DATABASE_URL (use a Neon branch), CORS_ORIGIN, OPENROUTER_API_KEY, EXA_API_KEY
uv run ruff check .
uv run mypy
uv run pytest
cd frontend
npm run lint
npm test
npm run build
```

Confirm `pyproject.toml` has no `extend-exclude` under `[tool.ruff]`, and no `exclude`, `ignore_errors` overrides or partial `files` list under `[tool.mypy]`.

### 3. Install the updated `deploy.sh` and push

`deploy.sh` is version-controlled, so the updated script (see Configuration Files) arrives on the VPS with the next `git pull`. Because the old script runs for that pull, **the key pre-check takes effect from the release after the one that delivers it**. So verify the keys by hand in Step 4.

```shell
git push
```

### 4. Verify the required keys on the VPS before releasing

```shell
ssh root@<VPS_IP>
stat -c '%U %a' /etc/bws4/bws4.env      # expect: root 600
for k in DATABASE_URL OPENROUTER_API_KEY GROQ_API_KEY EXA_API_KEY OPENAI_API_KEY CORS_ORIGIN; do
  grep -Eq "^${k}=.+" /etc/bws4/bws4.env && echo "ok   $k" || echo "MISSING $k"
done
```

If `GROQ_API_KEY` or `OPENAI_API_KEY` is missing, add it to `/etc/bws4/bws4.env` now. **Do not test the refuse-to-start behaviour on production.** The Phase 1 tests cover it.

### 5. Choose a quiet window

A release restarts the single process. In-flight SSE streams are cut, and the embedding model, PCA projection and Router route descriptions are rebuilt at boot.

### 6. Run the release on the VPS

```shell
export VITE_SENTRY_DSN=<your frontend DSN, if you use frontend Sentry>
/srv/bws4/deploy/deploy.sh
```

Expect: key check → git pull → `uv sync --frozen` → `npm ci && npm run build` → `alembic upgrade head` → restart → health wait → Router availability check. v10 adds no migration, so `alembic upgrade head` should apply nothing. If it tries to apply a revision, stop and investigate.

### 7. Verify the service and the Router state

```shell
systemctl status bws4-api --no-pager
journalctl -u bws4-api -n 80 --no-pager
ps -ef | grep uvicorn | grep -v grep   # confirm a single worker
curl -sS https://bw.spec4.ai/api/router/presets | head -c 600
```

Look in the journal for the warm-up steps. If any step failed, the log should show it clearly while the API stays up. Then open the Router page in a browser and hard-refresh. It should show normal presets with no warm-up wait. If it shows the unavailable state, click Retry and confirm it recovers without a restart.

### 8. Optional: exercise the unavailable state and Retry

Phase 8 covers this in tests, so skip it on production unless you want a live check. A live check would need a real route-description failure and spends no allowance, because a run that never began reserves no units. A deliberately broken configuration on production risks visitors seeing the unavailable state, so don't do it.

### 9. Add the Sentry alert for Router warm-up failure

After Phase 2 is deployed, find the warm-up failure event in Sentry (filter on the logger or module name and the message Phase 2 chose). Create an alert rule on the BWS4 backend project that emails you on new events of that kind. To test it without touching production, trigger the failure in a local or Neon-branch environment with `SENTRY_ENVIRONMENT=local-test`, and confirm the event reaches Sentry. If no event arrives, return to Phase 2 and have it log at ERROR level or capture the exception.

## Configuration Files

`deploy/bws4-api.service` and `deploy/Caddyfile` are unchanged and carried forward. `deploy/deploy.sh` and `CLAUDE.md` are updated.

### `deploy/deploy.sh` (updated)

New in v10:
- The required-key pre-check runs before any change to the host.
- The post-restart Router availability check warns loudly and does not fail the release.

The check finds the availability field by key name. Confirm the actual field name in `/docs` after Phase 3, and adjust `AVAIL_KEYS` if it differs.

```bash
#!/usr/bin/env bash
#
# BWS4 release script — run ON the VPS as root.
#
#   required-key check -> git pull -> uv sync -> npm ci && npm run build
#   -> alembic upgrade head -> systemctl restart bws4-api
#   -> health wait -> Router availability check
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
PRESETS_URL="http://127.0.0.1:8000/api/router/presets"
# Key names that may carry the Router availability flag. Confirm in /docs.
AVAIL_KEYS="available,availability"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
fail() { printf '\n\033[1;31mFAILED:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "must run as root"
[[ -f "$ENV_FILE" ]] || fail "missing ${ENV_FILE}"
command -v "$UV" >/dev/null || fail "uv not found at ${UV}"
command -v npm >/dev/null || fail "npm not found"
command -v python3 >/dev/null || fail "python3 not found"

# The API refuses to start without these two keys. Catch it before touching
# anything, while the current process is still serving.
log "Checking required startup credentials in ${ENV_FILE}"
for key in GROQ_API_KEY OPENAI_API_KEY; do
  value="$(
    set -a; . "$ENV_FILE" >/dev/null 2>&1; set +a
    printf '%s' "${!key:-}"
  )"
  [[ -n "$value" ]] || fail "${key} is missing or empty in ${ENV_FILE}; the API would refuse to start. Nothing was changed."
done
echo "    GROQ_API_KEY and OPENAI_API_KEY are present"

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
healthy=0
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null --max-time 3 http://127.0.0.1:8000/docs; then
    log "Service healthy after ${i}s"
    systemctl status "$SERVICE" --no-pager | head -n 12
    healthy=1
    break
  fi
  sleep 1
done

if [[ "$healthy" -ne 1 ]]; then
  journalctl -u "$SERVICE" -n 60 --no-pager
  fail "service did not become healthy within 60s"
fi

# The API boots healthy even if the Router warm-up failed, so /docs alone
# cannot tell. Read the presets availability flag and warn loudly. This does
# not fail the release: the rest of the app is serving.
log "Checking Router availability"
router_state="$(
  curl -fsS --max-time 5 "$PRESETS_URL" 2>/dev/null | AVAIL_KEYS="$AVAIL_KEYS" python3 -c '
import json, os, sys
keys = set(os.environ["AVAIL_KEYS"].split(","))
def find(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys and isinstance(v, bool):
                return v
        for v in o.values():
            r = find(v)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find(v)
            if r is not None:
                return r
    return None
try:
    r = find(json.load(sys.stdin))
except Exception:
    r = None
print("unknown" if r is None else ("true" if r else "false"))
' || echo unknown
)"

case "$router_state" in
  true)
    echo "    Router route descriptions are available"
    ;;
  false)
    warn "Router is UNAVAILABLE: route descriptions are not ready."
    warn "Check: journalctl -u ${SERVICE} -n 100 --no-pager"
    warn "Visitors will see the unavailable state. Use the Retry button once the cause is fixed."
    ;;
  *)
    warn "Could not read the Router availability flag from ${PRESETS_URL}."
    warn "Confirm the endpoint path and field name in /docs and update PRESETS_URL / AVAIL_KEYS."
    ;;
esac

log "Deploy complete"
```

### `deploy/bws4-api.service` (unchanged)

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
# GROQ_API_KEY and OPENAI_API_KEY are enforced at startup.
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

### `deploy/Caddyfile` (unchanged)

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

### `CLAUDE.md` (repo root, updated)

The v9 Router section is replaced by a v10 section. Copy it over the existing file.

```markdown
# BWS4 — Agent Context

## Hard invariants

- **Secrets never enter the repository.** Runtime configuration lives in
  `/etc/bws4/bws4.env` on the VPS — root-owned, chmod 0600, outside the
  repository tree. Never create a `.env` file inside this repo. Committed
  files reference environment variable NAMES only, never values. For pytest,
  export the keys in the shell instead.
- **The API runs with `--workers 1`.** This is a requirement, not a default.
  The loaded embedding model, the fitted PCA projection, the in-process peer
  message bus, the ReAct duplicate-guard cache and the Router's route
  descriptions are all per-process state. Never add workers, never suggest
  Gunicorn with multiple workers.
- **Postgres is external.** Neon + pgvector, unchanged by the VPS migration.
  Never propose installing Postgres on the host.

## v10 cleanup rules

- v10 adds NO new environment variables, NO new API keys and NO new example app.
- GROQ_API_KEY and OPENAI_API_KEY are REQUIRED: startup must refuse to proceed
  if either is missing. Do not make them optional again.
- Lifespan warm-ups (embedding model, PCA fit, Router route descriptions) are
  best-effort: a failure is logged at ERROR level (or captured to Sentry) and
  the API still boots. The credential check is the only startup failure.
- The Router reports unavailable while route descriptions are not ready. A run
  that never began returns an ordinary error response, not a stream, and
  reserves no usage units. The Retry action re-attempts route descriptions only.
- ruff and mypy cover the WHOLE backend. Never add ruff `extend-exclude`, mypy
  `exclude`, per-module `ignore_errors` or a partial mypy `files` list. Fix the
  code instead.
- Render is retired. Do not reintroduce Render references. Do not change
  deploy/Caddyfile, deploy/bws4-api.service or deploy/deploy.sh behaviour in
  documentation or cleanup phases.
- Tests must mock model and Exa calls. The `-m live` smoke run is opt-in and
  spends shared free-tier caps that production visitors use.
- Alembic migrations run against the live Neon database. Keep them additive.
- Model slugs come only from the shared registry. The quota gate is a direct
  service-layer call, never a model-exposed tool.

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
Optional: `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `MODERATION_HASH_SALT`, `PORT`,
`EMBEDDING_MODEL_NAME`, limit and REACT_* tuning variables
Build-time only: `VITE_API_BASE_URL`, `VITE_SENTRY_DSN` (the systemd
EnvironmentFile does NOT reach `npm run build`)

## Quality gates (developer-run, no CI)

`ruff`, `mypy`, `pytest`, `oxlint`, `tsc`, `vitest` — run before push.
```

## Notes

### Cost

No change. v10 adds no services.

| Item | Cost |
|---|---|
| netcup VPS 500 G12 (12-month) | ~€5.91/mo (~$6.81) |
| Neon Postgres + pgvector | Free tier |
| Caddy, systemd, Debian | Free |
| Sentry | Free (5k errors/mo, 1 user) |
| Better Stack | Free (10 monitors, 3-min checks) |
| **Total** | **~€6/mo** |

### Non-functional goals

**Addressed by this deployment:**

- **`nfr_the_first_visit_loads_without_a_cold_start_delay…`** (claimed by the embedding pipeline, the projection cache and `process_supervision`): the always-on host with `Restart=always` loads the embedding model and PCA projection once at boot, so no visitor pays that cost. A release re-pays it briefly at boot.
- **`nfr_the_service_refuses_to_start_when_a_required_credential_is_missing`** (claimed by `process_supervision` and `pydantic-settings`): the application enforces it, and the deployment supplies the environment through the root-owned `EnvironmentFile`. The `deploy.sh` pre-check stops a release with a missing key before it restarts anything, so the old process keeps serving instead of a systemd restart loop.
- **`nfr_a_failure_in_one_example_app_or_optional_startup_step_does_not_affect_the_other_apps`** (claimed by `process_supervision` and `router_route_descriptions`): `Restart=always` plus best-effort warm-ups. The deployment's added part is visibility, through the `deploy.sh` availability warning and the Sentry alert, because Better Stack cannot see a failed Router warm-up.
- **`nfr_all_traffic_is_served_over_a_secure_public_address_with_a_valid_certificate`** (claimed by `tls_termination_and_static_serving`): Caddy automatic Let's Encrypt, HTTPS only, HTTP→HTTPS redirect.
- **`nfr_routing_and_agreement_history_persists_across_service_interruptions`** (claimed by `primary_store` and the Router's history records): the history tables live in external Neon, so they survive restarts, redeploys and host loss.

**The coding agent's to satisfy, not this deployment's:**

- `nfr_every_example_app_stays_within_the_shared_hourly_and_daily_usage_limits…`, `nfr_per_run_model_call_counts_are_fixed…` and `nfr_visitors_are_told_clearly_which_limit…`: the allowance holds, `usage_limits` and `browser_local_storage`. No hosting choice caps API spend.
- `nfr_consistent_layout_and_navigation_across_all_example_apps`: React Router, Tailwind CSS and the example-app directory.

### Operational cautions

- **Releases cut SSE streams.** The single worker cannot be rolled. Deploy in quiet windows. Zero-downtime updates would need a stack change, not a deployment change.
- **First-release bootstrap.** The updated `deploy.sh` arrives via `git pull` during the release that delivers it, so its key pre-check first protects the release after that. Step 4 checks the keys by hand for this release.
- **Unavailable Router is not a failed release.** `deploy.sh` warns but doesn't fail on it, because the rest of the app is serving. Check the journal, fix the cause (typically an upstream or database problem during warm-up) and use Retry.
- **Retry is not a full re-warm.** It re-attempts route descriptions only. If the embedding model load or PCA fit failed, a restart is still required.
- **Moderation fails closed.** An invalid or revoked `OPENAI_API_KEY` blocks moderated runs. Both the v9 Sentry alert and the now-enforced startup check protect against it.
- **Don't test refuse-to-start on production.** Phase 1's tests cover it.
- **Keep `/etc/bws4/bws4.env` backed up** in your password manager. It is the one irreplaceable file on the host.

### Roadmap — recorded, not provisioned

- `remark-gfm` (optional library)
- `Playwright` (deferred library). If adopted, it would be the natural forcing function for CI.
- **CI/CD.** Still out of scope. A GitHub Actions run of the existing gates that then SSHes `deploy.sh` is the smallest sensible step.
- **Router feedback control.** An explicit thumbs up/down on the decision card.
- **Scheduled Router eval.** A weekly cron or systemd timer to catch silent upstream model drift. Deferred because it spends shared allowance.
- **Third Better Stack monitor on the Router presets availability flag.** Considered for v10 and skipped. It can flap during release restarts, and the Sentry alert plus the `deploy.sh` check cover the failure moment.
- **netcup snapshots and backups.** Unchanged. Neon holds all durable data.