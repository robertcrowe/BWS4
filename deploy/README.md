[Built with Spec4 AI](https://spec4.ai)

# BWS4 self-hosted deployment — Phase 1: VPS baseline bring-up

This file records what was actually done to prove the existing BWS4 tree
builds, migrates and boots warm on the project's own VPS, and — more
importantly — **why** each decision was made. Later phases add process
supervision (systemd), the public HTTPS edge (Caddy), and the release
script; none of that exists yet at this phase, deliberately. Render
continues to serve real visitors at `bw.spec4.ai` untouched until the
Phase 6 cutover.

## Host

- **netcup VPS 500 G12** — 2 vCore, 4 GB DDR5 ECC RAM, 128 GB NVMe,
  Debian GNU/Linux 13 (trixie), KVM.
- Measured before bring-up: **3442 MB available** of 3919 MB total, 113 GB
  free disk. The 4 GB of guaranteed RAM is the reason this plan was chosen:
  it removes the memory pressure the previous host's free tier imposed on
  torch and sentence-transformers, and makes keeping the model resident in
  one always-on process comfortable.

## Host prerequisites installed

Exactly what the stack requires and nothing more — no Docker, no
Kubernetes tooling, no process manager other than the systemd the distro
already ships (used from Phase 2):

- `git` 2.47.3 and Node **v20.20.2** (Debian 13 packages, already present)
- **uv 0.12.5** (installed per the uv docs: `curl -LsSf
  https://astral.sh/uv/install.sh | sh`)
- **Python 3.12 via uv-managed interpreters** — Debian 13's system Python
  is 3.13, and the project pins 3.12 (`.python-version`), so the venv is
  built from uv's managed 3.12 rather than the distro interpreter.

## Repository checkout

- Path: **`/srv/bws4`**, branch `dev`, owned by the unprivileged operator
  user (`rcrowe`) so git/uv/npm never run as root. This path is the stable
  anchor every later phase's artifact references (Phase 3's Caddy serves
  `/srv/bws4/frontend/dist/`; Phase 4's deploy script operates here).
- The repo is public, cloned over HTTPS — no deploy key to manage.

## The environment contract — `/etc/bws4/bws4.env`

- **Location**: `/etc/bws4/bws4.env`, directory mode `0700`, file owned
  `root:root` mode `0600`.
- **Why outside the repository tree**: the tree at `/srv/bws4` must never
  be *able* to contain a secret, even by accident — a stray `git add`, a
  tarball of the checkout, an editor backup file. Keeping the file under
  `/etc/bws4` root-only means leaking it requires root, not a git mistake.
  `git status --porcelain` in `/srv/bws4` stays clean by construction.
- **Variable NAMES** (values live only in the file, carried over verbatim
  from the retired Render dashboard — no additions, removals or renames):
  - `DATABASE_URL` — Neon Postgres (pgvector-enabled), external, unchanged
  - `OPENROUTER_API_KEY`
  - `GROQ_API_KEY`
  - `EXA_API_KEY`
  - `OPENAI_API_KEY`
  - `CORS_ORIGIN` — `https://bwtemp.spec4.ai` during Phases 1–5 (the
    temporary validation origin); repointed to `https://bw.spec4.ai` at
    the Phase 6 cutover
  - `SENTRY_DSN` — optional; `configure_sentry` no-ops cleanly when unset
- **Cross-check resolution** (required by the phase because `.env.example`
  had not been sampled by the code review): `.env.example` also names
  `PORT`, `EMBEDDING_MODEL_NAME`, `SENTRY_ENVIRONMENT` and
  `VITE_API_BASE_URL`, and `backend/app/core/config.py` additionally reads
  `MODERATION_HASH_SALT`. Resolved in favour of what the code actually
  reads: `PORT` (defaults to 8000), `EMBEDDING_MODEL_NAME` (defaults to
  all-MiniLM-L6-v2), `SENTRY_ENVIRONMENT` (defaults to "development") and
  `MODERATION_HASH_SALT` (a process-stable salt is generated at boot; only
  cross-restart hash comparability is lost) are deliberately omitted so the
  contract stays verbatim; `VITE_API_BASE_URL` is a frontend build-time
  variable with no place in a runtime file.
- **`VITE_SENTRY_DSN` caveat — do not lose this**: it is consumed by Vite
  at **build** time (`npm run build`), not by the running server. Putting
  it only in a systemd `EnvironmentFile` does NOT reach the frontend
  build, and frontend error tracking silently stops. Phase 1 confirmed the
  bundle built without it contains no Sentry initialisation; Phase 4's
  deploy script is where the build-time environment is made explicit and
  permanent.

## Manual boot (Phase 1 only — systemd supervision arrives in Phase 2)

```sh
cd /srv/bws4 \
  && set -a && . /etc/bws4/bws4.env && set +a \
  && uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

- **Why `--workers 1` is mandatory, not incidental**: the loaded embedding
  model, the fitted PCA projection, the in-process peer message bus (the
  multi-agent collaboration app) and the ReAct duplicate-guard cache are
  all **per-process** state. A second worker would not crash — it would
  *silently* split that state: half the requests would see an unfitted
  projection, peer messages would vanish between processes, and duplicate
  queries would stop being detected. Never add workers; never suggest
  Gunicorn with multiple workers.
- **Why `--host 127.0.0.1`**: Uvicorn must never be directly reachable
  from the network. The public edge (TLS, one canonical origin) is Caddy's
  job from Phase 3; until then the service is loopback-only. Verified from
  an external machine: `curl http://<vps-ip>:8000/health` times out.
- Note for operators running this by hand: the secrets file is root-only,
  so the manual boot needs root to *source* the file; the server process
  itself should still run as the unprivileged user (Phase 1 used
  `runuser -p -u rcrowe` after sourcing).
- Alembic must run **from `backend/`** (`uv run alembic -c alembic.ini
  ...`): the ini's `script_location = app/db/migrations` is resolved
  relative to the working directory, not the ini file.

## Measured warm-up (the cost this migration moves off the visitor)

First boot on the VPS, from the structlog timestamps in the boot log:

- Process launch → `embeddings_projection_built`: **≈ 25.5 s**
  (launch 06:45:18 local → built 06:45:43.5), of which the projection
  build itself (`ensure_built`: model load + PCA fit over 24 presets,
  384-dim) reported `elapsed_ms: 11527`.
- On Render's free tier this cost was paid on a visitor's first request
  after every spin-down; on the always-on VPS it is paid once per deploy
  restart. Phase 2's supervision keeps it that way across crashes and
  reboots.
- The warm-up is deliberately **best-effort**: `ensure_built()` is wrapped
  in a bare `except Exception` in the lifespan so a broken projection logs
  (`embeddings_projection_warmup_failed`) and the gallery still boots.
  Because of that, a successful boot is NOT proof of warmth — always grep
  the boot log for `embeddings_projection_built` and for the absence of
  the failure record, exactly as this phase's verification did.
- `/health` is a liveness signal only, deliberately independent of the
  warm-up; it returns 200 (and reports DB connectivity) even if the
  projection failed to build.

## Phase 1 verification results (2026-08-17)

- Alembic `current` == `heads` at `0013_react_runs` against Neon (no-op
  upgrade, as expected — the store is external and survived the host move
  untouched).
- Boot log contains `embeddings_projection_built`; no swallowed warm-up
  exception.
- `curl -sS -i http://127.0.0.1:8000/health` → 200
  `{"status":"ok","db":"connected"}`.
- `ss -ltnp` shows the only listener on `127.0.0.1:8000`; external curl to
  port 8000 fails to connect.
- Starting with `DATABASE_URL` unset exits immediately with the
  pydantic-settings error naming the missing configuration.
- Quality gates on the VPS matched the local baseline — pytest 1815
  passed / 21 skipped / 5 deselected, ruff clean, mypy clean (202 files).
  Caveats recorded, not fixed: the suite deselects `live` tests, and both
  ruff and mypy exempt pre-v5/pre-v6 paths file by file, so green ≠
  everything checked.
- `npm ci && npm run build` emits the hashed bundle with per-example lazy
  chunks into **`/srv/bws4/frontend/dist/`** (the exact directory Phase
  3's Caddy will serve). One repair was required and committed: the
  checked-in `package-lock.json` was out of sync with `package.json`
  (missing optional `@emnapi/*` entries), which made `npm ci` fail on any
  host; fixed by a metadata-only lockfile regeneration with no dependency
  version changes.
