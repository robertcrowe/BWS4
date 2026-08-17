[Built with Spec4 AI](https://spec4.ai)

# BWS4 self-hosted deployment — provisioning runbook and operations guide

This is the complete, final-form runbook for the BWS4 gallery's
self-hosted deployment: how to reproduce the entire installation from a
bare VPS (§ First-time provisioning), how to ship a release
(§ Releases — `deploy/deploy.sh`), and how to operate and roll back
(§ Operations). Measured results from the phased bring-up are preserved
at the end (§ Verification records) — they are the baselines the deploy
script's readiness gate budgets against.

**Topology.** One netcup VPS runs everything except the database: Caddy
terminates TLS at the edge, serves the Vite bundle from
`/srv/bws4/frontend/dist` with SPA history fallback, and reverse-proxies
`/api/*` (plus `/health`) to a single loopback Uvicorn process on
`127.0.0.1:8000` supervised by systemd. Postgres is external (Neon,
pgvector) and unchanged by the migration. Origin during validation:
`https://bwtemp.spec4.ai`; the canonical `https://bw.spec4.ai` cuts over
in Phase 6, until which Render keeps serving it and `render.yaml` stays
in the tree untouched.

**The one architectural rule.** The API runs with `--workers 1` — a
requirement, not a default. The loaded embedding model, the fitted PCA
projection, the in-process peer message bus and the ReAct duplicate-guard
cache are all per-process state; a second worker would not crash, it
would *silently* split that state. Never add workers, never front it with
a multi-worker Gunicorn.

---

# First-time provisioning (bare VPS → serving gallery)

Reproduces the phased bring-up (Phases 1–3, all completed 2026-08-17) as
one linear procedure. Every step assumes an unprivileged operator user
(`rcrowe` throughout) with sudo; nothing below runs services as root.

## 1. Host prerequisites

- **netcup VPS 500 G12** — 2 vCore, 4 GB DDR5 ECC RAM, 128 GB NVMe,
  Debian GNU/Linux 13 (trixie), KVM. The 4 GB of guaranteed RAM is why
  this host class was chosen: torch + sentence-transformers stay resident
  in one always-on process comfortably (measured ≈3.4 GB available before
  bring-up).
- Exactly what the stack requires and nothing more — no Docker, no
  Kubernetes, no process manager beyond the distro's systemd:
  - `git` (2.47.x) and **Node 20** (`nodejs`/`npm` from Debian 13
    packages — v20.20.2 at bring-up)
  - **uv** (0.12.x): `curl -LsSf https://astral.sh/uv/install.sh | sh`,
    then copy the binary to **`/usr/local/bin/uv`** (root-owned). It must
    live outside `/home` — see the hardening note in step 5.
  - **Python 3.12 via uv-managed interpreters**, installed to
    **`/opt/uv/python`** (outside `/home`, world-readable):

    ```sh
    sudo mkdir -p /opt/uv/python
    UV_PYTHON_INSTALL_DIR=/opt/uv/python uv python install 3.12
    ```

    Debian 13's system Python is 3.13; the project pins 3.12
    (`.python-version`), so the venv is always built from the uv-managed
    interpreter. (uv creates a `cpython-3.12-…` minor-version alias dir
    beside the full-version dir — globs over `/opt/uv/python` match twice;
    harmless.)
- Add the operator to the journal-reading group (the deploy script's
  readiness gate greps the unit's journal):

  ```sh
  sudo usermod -aG systemd-journal rcrowe   # re-login to take effect
  ```

## 2. Repository checkout

```sh
sudo mkdir -p /srv/bws4 && sudo chown rcrowe:rcrowe /srv/bws4
git clone https://github.com/<org>/BWS4.git /srv/bws4   # public repo, HTTPS, no deploy key
cd /srv/bws4 && git checkout dev
```

- **`/srv/bws4`**, owned by the operator so git/uv/npm never run as root.
  This path is the stable anchor everything references: Caddy serves
  `/srv/bws4/frontend/dist`, the unit's `WorkingDirectory` is
  `/srv/bws4`, and `deploy/deploy.sh` operates here.

## 3. The environment contract — `/etc/bws4/bws4.env`

```sh
sudo mkdir -p /etc/bws4 && sudo chmod 0700 /etc/bws4
sudo touch /etc/bws4/bws4.env && sudo chmod 0600 /etc/bws4/bws4.env
sudo "$EDITOR" /etc/bws4/bws4.env   # fill in VALUES; names below
```

- **Why outside the repository tree**: the tree at `/srv/bws4` must never
  be *able* to contain a secret, even by accident — a stray `git add`, a
  tarball of the checkout, an editor backup. Leaking `/etc/bws4/bws4.env`
  requires root, not a git mistake. `git status` in `/srv/bws4` stays
  clean by construction, and `deploy.sh` enforces that before every pull.
- **Variable NAMES** (values live only in the file — carried over
  verbatim from the retired Render dashboard, no additions or renames):
  - `DATABASE_URL` — Neon Postgres (pgvector-enabled), external
  - `OPENROUTER_API_KEY`
  - `GROQ_API_KEY`
  - `EXA_API_KEY`
  - `OPENAI_API_KEY`
  - `CORS_ORIGIN` — `https://bwtemp.spec4.ai` during validation
    (Phases 1–5); repointed to `https://bw.spec4.ai` at the Phase 6
    cutover. Any change to this file needs
    `sudo systemctl restart bws4-api` to take effect.
  - `SENTRY_DSN` — optional; `configure_sentry` no-ops cleanly when unset
- Deliberately omitted (cross-checked against `.env.example` and
  `backend/app/core/config.py`, resolved in favour of what the code
  reads): `PORT` (defaults 8000), `EMBEDDING_MODEL_NAME` (defaults
  all-MiniLM-L6-v2), `SENTRY_ENVIRONMENT` (defaults "development"),
  `MODERATION_HASH_SALT` (process-stable salt generated at boot; only
  cross-restart hash comparability is lost). `VITE_API_BASE_URL` and
  `VITE_SENTRY_DSN` are **build-time** variables with no place in a
  runtime file — next section.

## 4. The build-time environment — `/etc/bws4/build.env` (optional)

Vite substitutes `VITE_`-prefixed variables at **build** time
(`npm run build`), so the systemd `EnvironmentFile` — which reaches only
the running service — does NOT reach the frontend build. After migrating
from a platform that showed every variable in one flat dashboard list,
this is the single easiest thing to get wrong, and the failure is
silent: the bundle simply ships without frontend error tracking.

`deploy/deploy.sh` therefore sources **`/etc/bws4/build.env`** (if
present) into the build step's environment:

```sh
sudo sh -c 'printf "VITE_SENTRY_DSN=<your-frontend-dsn>\n" > /etc/bws4/build.env && chmod 0644 /etc/bws4/build.env'
```

- Mode 0644 is fine (unlike `bws4.env`): the DSN ships inside the public
  JS bundle anyway; it is configuration, not a secret.
- The file is optional. `@sentry/react` is never initialised when
  `VITE_SENTRY_DSN` is unset, so its absence is a legitimate
  configuration (frontend error tracking off) — the deploy announces the
  choice but never fails on it.
- `VITE_API_BASE_URL` is NOT in this file: the deploy script hardcodes it
  to the **empty string**, which is a structural requirement, not
  configuration (§ Releases explains why).

## 5. Python venv and the ProtectHome relocation

```sh
cd /srv/bws4
UV_PYTHON_INSTALL_DIR=/opt/uv/python uv sync --locked   # as the operator
```

The service unit runs with `ProtectHome=true`, which makes `/home`
invisible to the process. That is why the toolchain lives outside
`/home`: uv at `/usr/local/bin/uv`, CPython under `/opt/uv/python`, and
the venv's symlinks resolving there. The venv itself (`/srv/bws4/.venv`)
is owned by the operator; releases sync it as the operator, and the unit
starts with `uv run --no-sync` so the service never writes it.

## 6. Service user and systemd unit

```sh
sudo useradd --system --home-dir /var/lib/bws4 --create-home --shell /usr/sbin/nologin bws4
sudo cp /srv/bws4/deploy/bws4-api.service /etc/systemd/system/bws4-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now bws4-api
```

- The unit template `deploy/bws4-api.service` carries the WHY-comments
  for every decision: one worker, loopback bind (`--host 127.0.0.1`,
  Uvicorn must never be network-reachable — the edge is Caddy's job),
  `EnvironmentFile=/etc/bws4/bws4.env` (read by systemd as root before
  privileges drop, which is why the file stays root-only),
  `Restart=always` + `WantedBy=multi-user.target` (crash AND reboot
  survival), and hardening (`NoNewPrivileges`, `PrivateTmp`,
  `ProtectSystem=strict` with `ReadWritePaths=/var/lib/bws4` as the only
  writable path, `ProtectHome=true`).
- Runs as the dedicated system user **`bws4`** (nologin, home
  `/var/lib/bws4` — holds the HuggingFace model cache and
  `UV_CACHE_DIR`). It can read `/srv/bws4` but cannot write `.git`.
  Optionally pre-seed `/var/lib/bws4/.cache/huggingface` (chowned to
  `bws4`) so the first boot skips the model download; startup still makes
  one unauthenticated HF Hub request even with a seeded cache.
- Process shape: `uv run --no-sync` stays resident as a thin launcher, so
  `systemctl status` shows **two** PIDs — the `uv` MainPID and exactly
  one `uvicorn` child, the single application process the architecture
  mandates.
- The boot warm-up (embedding model load + PCA projection fit) runs in
  the FastAPI lifespan **before** Uvicorn accepts connections, and is
  deliberately best-effort: a broken projection logs
  `embeddings_projection_warmup_failed` and the gallery boots anyway.
  **Never infer warmth from `systemctl is-active`** — grep the current
  boot's journal for `embeddings_projection_built` and the *absence* of
  the failure record. The deploy script's readiness gate automates
  exactly this.

## 7. DNS — before Caddy is first started

Create these records **before** loading the Caddy site block: Let's
Encrypt validates over the public hostname, and reloading earlier burns
failed ACME attempts against LE rate limits.

- `bwtemp.spec4.ai` → A `159.195.17.63`, AAAA
  `2a0a:4cc0:101:148b:986f:c0ff:fe7e:fbcb` (temporary validation records,
  retired at Phase 6).
- **Cloudflare gotcha — do not lose this**: spec4.ai is on Cloudflare,
  and the records must be **DNS only** (grey cloud). Proxied records
  resolve to Cloudflare edge IPs, which breaks ACME issuance *and* would
  insert a second, buffering proxy in front of the four SSE example apps.
- `bw.spec4.ai` keeps resolving to Render untouched until Phase 6.

## 8. Caddy — TLS edge, static bundle, API proxy

```sh
# Official Caddy apt repo (dl.cloudsmith.io/public/caddy/stable), not
# Debian's archive — packaged systemd unit kept, no custom build/plugins.
sudo apt install caddy
sudo cp /srv/bws4/deploy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy      # reload, not restart: keeps serving
systemctl is-enabled caddy       # must be "enabled"
journalctl -u caddy --no-pager | grep -Ei 'certificate|acme|obtain'
```

The Caddyfile template carries its own WHY-comments; the short version:
one origin serves both SPA and API (cross-origin traffic disappears from
production; the `CORS_ORIGIN` contract is retained unchanged),
`flush_interval -1` is set explicitly on the `/api/*` proxy so the SSE
apps stream progressively (Caddy's content-type autodetection is too
fragile to trust), **no `encode` on the API block** (compression is a
second way to reintroduce buffering), and `/health` is proxied to the
backend (deliberate consequence: the SPA's client-side /health screen is
shadowed on this origin). A certificate-issuance failure is nearly always
DNS not yet resolving to the VPS or port 80 blocked — diagnose from
Caddy's journal, don't retry blindly.

## 9. Firewall

```sh
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp     # ACME HTTP challenge + HTTP→HTTPS redirect; never serves the app in plain HTTP
sudo ufw allow 443/tcp
sudo ufw allow 443/udp    # HTTP/3
sudo ufw enable
```

**Port 8000 is never opened.** It has no allow rule AND Uvicorn binds
loopback only — two independent reasons the API is unreachable except
through Caddy.

## 10. First deploy

With all of the above in place, every release — including the very first
frontend build — is the same single command (next section).

---

# Releases — `deploy/deploy.sh`

The entire release procedure is one version-controlled script,
`deploy/deploy.sh`, run **on the VPS** as the operator from an
interactive terminal (two steps use sudo and prompt once for a
password):

```sh
ssh -t rcrowe@<vps> '/srv/bws4/deploy/deploy.sh'
```

What it does, in order (each step announced to the terminal and journal;
`set -euo pipefail` means any failing step aborts the deploy *before*
the restart, leaving the previous build serving untouched):

1. Preflight: refuses to run as root; refuses a dirty working tree.
2. `git pull --ff-only` in `/srv/bws4`.
3. `uv sync --locked` (as the operator, `UV_PYTHON_INSTALL_DIR=/opt/uv/python`).
4. `npm ci && VITE_API_BASE_URL='' npm run build` in `frontend/`, with
   `VITE_SENTRY_DSN` sourced from `/etc/bws4/build.env` if present.
   `VITE_API_BASE_URL` **must be the empty string, never unset**: the api
   modules read `import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'`,
   and only the empty string (which survives `??`) yields relative
   same-origin paths. A bundle built with it unset bakes
   `localhost:8000` into every chunk — Phase 1 shipped exactly that
   defect. Check for regressions with `grep -rl localhost:8000 dist/assets/`.
5. `alembic upgrade head` from `backend/` against the external Neon
   database — idempotent; a deploy with no new migration reports the
   current head. Root sources `/etc/bws4/bws4.env` in a subshell for this
   one step and drops back to the operator to run it.
6. `sudo systemctl restart bws4-api`.
7. **Readiness gate — the deploy is not done until this passes**:
   - polls `http://127.0.0.1:8000/health` to a 200 (bounded, loud
     timeout);
   - requires this boot's `embeddings_projection_built` journal record
     and the absence of `embeddings_projection_warmup_failed` — because
     the warm-up is best-effort by design, `/health` is deliberately
     independent of it, and a naive health check would declare success
     over a cold projection;
   - calls `GET /api/embeddings/presets` through loopback and requires
     success. On any failure it names the embeddings example app as
     degraded and exits non-zero.
8. Prints the measured cost of the release: the downtime window
   (restart → first `/health` 200), the warm-up time
   (restart → projection built), and the projection build's own
   `elapsed_ms` — so every release records what it actually cost.

Re-running the script with no upstream change is safe and supported: it
completes as a no-op plus a restart.

**Quality gates are deliberately NOT in the script.** `uv run pytest`,
`uv run ruff check .`, `uv run mypy backend` and `npm run test` (in
`frontend/`) remain developer-run before push — no CI exists in the tree
and adding one is out of this revision's scope. Known caveat: pyproject
sets `addopts = "-m 'not live'"`, so a green pytest run says nothing
about live provider behaviour; that is verified by observation on the
running origin (Phase 5).

---

# Operations

## Logs

```sh
journalctl -u bws4-api -f     # follow the API (structlog JSON lines)
journalctl -u caddy -f        # follow the edge (ACME, TLS, access errors)
journalctl -u bws4-api -b --no-pager | grep -Ei 'projection|embedding'   # warmth check
```

## Restart and status

```sh
sudo systemctl restart bws4-api
systemctl status bws4-api          # expect 2 PIDs: uv launcher + one uvicorn
sudo systemctl reload caddy        # after Caddyfile changes (validate first)
```

After any manual restart, apply the same standard as the deploy script:
`is-active` is not warmth — check the journal for this boot's
`embeddings_projection_built`, or just re-run `deploy/deploy.sh`, whose
gate does it for you.

## Rollback

```sh
cd /srv/bws4
git checkout <previous-commit>   # detached HEAD is fine for an emergency
/srv/bws4/deploy/deploy.sh       # rebuilds, re-migrates (no-op), restarts, re-gates
```

(`git pull --ff-only` inside the script is a no-op on a detached HEAD or
pinned commit; return with `git checkout dev` and a normal deploy.)

**Migration boundary caveat**: the script deliberately contains no
downgrade path — the migration tree is forward-only and authoritative.
A rollback that crosses a migration boundary therefore needs manual
attention: old code may not run correctly against the newer schema.
Check whether the range being rolled back touches
`backend/app/db/migrations/versions/` before relying on a plain
checkout-and-redeploy.

## Accepted limitation: a release is a brief interruption

Stated plainly rather than buried: **a release interrupts service for
roughly the warm-up window (~30–40 s measured)** while the restarted
process reloads the embedding model and re-fits the PCA projection at
boot. The project-wide goal — updating content and example apps without
interrupting visitors — is met by deploying *rarely and quickly*, not by
hot-swapping: the cost is paid by the deploy, at a moment the operator
chooses, and never by a visitor's first interaction.

Zero-downtime deployment (a second warm instance plus a Caddy upstream
flip) was considered and deliberately deferred as unnecessary machinery
for an infrequently-deployed showcase. It remains a purely additive
change — nothing in this arrangement forecloses it — if the interruption
ever chafes.

---

# Verification records (phased bring-up, 2026-08-17)

Condensed from the phase-by-phase verification runs; these are the
baselines the deploy gate budgets against.

## Phase 1 — VPS baseline

- Alembic `current` == `heads` at `0013_react_runs` against Neon (no-op
  upgrade; the store is external and survived the host move untouched).
- Boot-to-warm ≈ **25.5 s** manual boot (projection build `elapsed_ms`
  11527); boot log contains `embeddings_projection_built`, no swallowed
  warm-up exception.
- `/health` → 200 `{"status":"ok","db":"connected"}`; only listener is
  `127.0.0.1:8000`; external curl to 8000 cannot connect; starting with
  `DATABASE_URL` unset exits immediately with the pydantic-settings
  error naming the missing variable.
- Quality gates on the VPS matched local: pytest 1815 passed / 21
  skipped / 5 deselected, ruff clean, mypy clean (202 files). Caveats
  recorded, not fixed: `live` tests deselected; ruff/mypy exempt
  pre-v5/pre-v6 paths file by file, so green ≠ everything checked.
- One real defect found and fixed: the checked-in
  `frontend/package-lock.json` was out of sync with `package.json`
  (missing optional `@emnapi/*` entries), failing `npm ci` on any host;
  repaired by a metadata-only lockfile regeneration.

## Phase 2 — systemd supervision

- Fresh `systemctl start` → `embeddings_projection_built` ≈ **29.6 s**
  (projection `elapsed_ms` 6238); **post-reboot ≈ 32.3 s** — the number a
  deploy restart budgets against, slightly above the manual baseline
  because boot competes for 2 vCores.
- Warmth verified by evidence, not unit state: journal success record
  plus two timed `/api/embeddings/presets` calls at 5.7 ms then 1.6 ms —
  no first-request model-load penalty.
- `kill -9` of the MainPID: auto-restart (`Restart=always`,
  `RestartSec=3`), re-warmed, `/health` 200. Full `sudo reboot`: unit
  came back enabled+active with no intervention, warmed, loopback-only.
- Honest caveats: `network-online.target` is declared but no
  wait-online service is enabled, so it is reached trivially (the
  warm-up's own journal failure record is the detector if a boot ever
  races networking); startup makes one unauthenticated HF Hub request
  even with the seeded cache; `sentry_enabled` reports
  `environment: development` because `SENTRY_ENVIRONMENT` is
  deliberately not in the env contract.

## Phase 3 — Caddy edge

- Caddy v2.11.4 (official repo, upgraded over Debian's preinstalled
  2.6.2). Let's Encrypt issued first-attempt (TLS-ALPN-01); expiry
  Nov 15 2026 with in-process renewal; `http://` → 308 → `https://`
  HTTP/2 200, h3 advertised.
- DNS records had to be switched from Cloudflare-proxied to **DNS only**
  (proxied resolved to Cloudflare IPs — broke ACME and would have added
  a second buffering proxy in front of SSE).
- SPA fallback serves deep links and unknown routes (by design the SPA
  owns unknown paths); `/api/collab/identity-cards` and `/health` answer
  through the edge.
- **Progressive streaming proven through the edge**: a collab run's
  events arrived spread across 171.7 s (first at 1.6 s, award at
  109.5 s), not as one burst; sse-starlette keep-alive pings held exact
  15 s intervals through a ~100 s idle stretch. ReAct runs streamed
  cycle envelopes progressively; both ended candidly
  `budget_exhausted`/`malformed_step` after cycle 1 — upstream free-model
  flakiness, flagged for Phase 5's comparison against Render, not edge
  buffering.
- Port 8000 externally unreachable (no ufw rule AND loopback bind);
  80/443 answer. Frontend bundle rebuilt with `VITE_API_BASE_URL=`
  (empty) after the Phase 1 bundle was found to bake in
  `localhost:8000`.

## Phase 4 — release delivery

_Results recorded after the first scripted deploys — see the deploy
script's printed summary for the measured downtime of each release._
