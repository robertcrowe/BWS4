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

# Phase 2: Process supervision — systemd, warm-at-boot, restart survival

Phase 2 (2026-08-17) put the single-worker Uvicorn under systemd so the
always-on warm guarantee is structural rather than incidental: the service
restarts itself after a crash, starts itself after a reboot, and rebuilds
the embedding model + PCA projection warm at every boot. The service is
still loopback-only; Caddy/TLS (Phase 3) and the cutover (Phase 6) come
later, and Render continues to serve visitors at `bw.spec4.ai` untouched.

## The unit

- Template in the repo: **`deploy/bws4-api.service`** (no secret values —
  it names only the `EnvironmentFile` path). Installed copy:
  `/etc/systemd/system/bws4-api.service`. The unit file itself carries the
  WHY-comments for every decision (one worker, loopback bind, root-owned
  EnvironmentFile outside the tree, best-effort warm-up, hardening).
- `EnvironmentFile=/etc/bws4/bws4.env` is read **by systemd as root**
  before privileges drop to the service user, which is why the file stays
  `root:root 0600` and was NOT loosened for Phase 2. Verified: the service
  user cannot read it directly.
- Runs as dedicated system user **`bws4`** (nologin, home
  `/var/lib/bws4`). It can read `/srv/bws4` but cannot write `.git`
  (verified both ways).
- Hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` with
  `ReadWritePaths=/var/lib/bws4` as the *only* writable path (logs go to
  journald, the DB is external, the venv is read-only to the service),
  `ProtectHome=true`, `ProtectKernelTunables=true`.

## Why the toolchain moved out of /home

`ProtectHome=true` makes `/home` invisible to the process — and after
Phase 1 the entire runtime lived there (uv at `~rcrowe/.local/bin/uv`, the
venv's interpreter symlinked into `~rcrowe/.local/share/uv/python/…`).
Under the hardened unit the service literally could not exec its own
interpreter. Relocation, done once at Phase 2 install:

- uv binary → **`/usr/local/bin/uv`** (root-owned copy).
- CPython 3.12 → **`/opt/uv/python/`** via
  `UV_PYTHON_INSTALL_DIR=/opt/uv/python uv python install 3.12`
  (world-readable; note uv also creates a `cpython-3.12-…` minor-version
  alias dir next to the full-version dir).
- `/srv/bws4/.venv` rebuilt (as `rcrowe`, who still owns it) against that
  interpreter with `UV_PYTHON_INSTALL_DIR=/opt/uv/python uv sync --locked`,
  so its symlinks resolve outside `/home`. Releases (Phase 4) sync the
  venv as `rcrowe`; the unit runs `uv run --no-sync` and never writes it.
- The HuggingFace model cache was pre-seeded into
  `/var/lib/bws4/.cache/huggingface` (and chowned to `bws4`) so the first
  supervised boot did not re-download the model. `HOME=/var/lib/bws4`
  comes from the `bws4` passwd entry; `UV_CACHE_DIR=/var/lib/bws4/uv-cache`
  keeps uv inside the writable path.

## Process shape

`ExecStart` invokes `uv run --no-sync uvicorn …`. uv stays resident as a
thin launcher, so `systemctl status` shows **two** PIDs: the `uv` MainPID
and exactly **one** `python`/`uvicorn` child — the single application
process the architecture mandates. There is no process manager and there
are no workers. `systemctl stop` SIGTERMs the whole cgroup (default
control-group kill mode), so Uvicorn still shuts down gracefully.

## Operator commands

```sh
sudo systemctl start|stop|restart bws4-api   # lifecycle
systemctl status bws4-api                    # state + process tree
journalctl -u bws4-api -f                    # follow logs (structlog JSON)
journalctl -u bws4-api -b --no-pager \
  | grep -Ei 'projection|embedding'          # warmth check (see below)
```

**Never infer warmth from `is-active`.** The lifespan warm-up is
deliberately best-effort (bare `except Exception` in
`backend/app/main.py`), so a unit blocked from its model cache — the
classic `ProtectSystem=strict` failure — still reports active while
serving cold. Always grep the current boot's journal for
`embeddings_projection_built` and for the *absence* of
`embeddings_projection_warmup_failed`.

## Measured warm-up under supervision (2026-08-17)

- Fresh `systemctl start`, quiet host: unit start →
  `embeddings_projection_built` **≈ 29.6 s** (projection build itself
  `elapsed_ms` 6238).
- **Post-reboot: ≈ 32.3 s** — the figure a deploy or unplanned reboot
  costs, slightly above the ~25.5 s Phase 1 manual-boot baseline because
  the warm-up competes with everything else starting on 2 vCores. Phase
  4's deploy-restart posture budgets against this number.
- Warmth verified by evidence, not unit state: journal shows the success
  record with no swallowed exception, and two consecutive timed calls to
  `/api/embeddings/presets` returned in 5.7 ms then 1.6 ms after reboot —
  no first-request model-load penalty.

## Crash and reboot survival (both individually verified)

- `kill -9` of the MainPID: systemd restarted the service automatically
  (`Restart=always`, `RestartSec=3` so a flapping unit produces readable,
  spaced journal entries), the new process completed its warm-up, and
  `/health` returned 200.
- `sudo reboot`: with no manual intervention the unit came back
  active+enabled (`WantedBy=multi-user.target` — the property
  `Restart=always` alone does not give you), warmed up, answered
  `/health` 200, and the listener was still bound to `127.0.0.1:8000`
  only (external connect to port 8000 times out).

## Honest caveats

- `network-online.target` is declared (`After=`/`Wants=`) because the
  warm-up reaches Neon and the HF Hub, but on this host neither
  `systemd-networkd-wait-online` nor `NetworkManager-wait-online` is
  enabled, so the target is reached trivially. In practice networking is
  up well before `multi-user.target`; if a future boot races it, the
  warm-up's failure record in the journal is the detector.
- Startup makes one unauthenticated HF Hub request (model verification)
  even with the seeded cache; harmless, but it is why the unit wants real
  network at boot.
- The `sentry_enabled` record reports `environment: development` because
  `SENTRY_ENVIRONMENT` is deliberately not in the env contract (see the
  Phase 1 cross-check note above).
