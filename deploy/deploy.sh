#!/usr/bin/env bash
# Built with Spec4 AI - https://spec4.ai
#
# deploy.sh — the entire BWS4 release procedure in one readable file.
#
# Run ON the VPS as the operator user (rcrowe), from an interactive
# terminal, because two steps below use sudo and need a password prompt:
#
#     ssh -t rcrowe@<vps> '/srv/bws4/deploy/deploy.sh'
#
# WHY a plain restart instead of a zero-downtime instance swap
# ------------------------------------------------------------
# A release here is: pull, rebuild, migrate, `systemctl restart bws4-api`.
# The restart re-pays the boot-time warm-up — loading the sentence-
# transformers embedding model and fitting the PCA projection over the 24
# curated presets (~30 s measured in Phase 2, ~32 s after a full reboot).
# That cost is deliberately borne BY THE DEPLOY, not by a visitor: the
# whole point of the VPS migration is that no visitor ever waits on a
# cold model again. A zero-downtime scheme (second warm instance plus a
# Caddy upstream flip) was considered and deliberately deferred: this
# showcase deploys infrequently, so ~30–40 s of planned interruption per
# release is cheaper than permanently operating twice the machinery. If
# that ever chafes, the two-instance flip is a purely additive change.
#
# Quality gates are NOT run here — deliberately
# ---------------------------------------------
# The stack records ruff, mypy, pytest and vitest as developer-run before
# push; no CI exists in the tree and adding one is out of this revision's
# scope. Before pushing what you are about to deploy you are expected to
# have run, locally:
#
#     uv run pytest
#     uv run ruff check .
#     uv run mypy backend
#     npm run test          # in frontend/
#
# This script does not enforce them. Known limitation of that pytest
# gate: pyproject sets addopts = "-m 'not live'", so the suite deselects
# every test that reaches real model providers or real Exa — a green run
# says nothing about live provider behaviour. Live behaviour is verified
# by observation on the running origin (Phase 5's job), not by this
# script and not by the suite.
#
# Secrets
# -------
# This script holds no secret values, only variable NAMES. Runtime
# configuration reaches the service solely through the systemd
# EnvironmentFile /etc/bws4/bws4.env (root:root 0600, outside the
# repository tree, never committed). The one step here that needs a
# runtime secret (Alembic needs DATABASE_URL) sources that file inside a
# root subshell scoped to that single step — see step 4.

set -euo pipefail

REPO=/srv/bws4
FRONTEND="$REPO/frontend"
BACKEND="$REPO/backend"
UV=/usr/local/bin/uv
UNIT=bws4-api
RUNTIME_ENV_FILE=/etc/bws4/bws4.env
BUILD_ENV_FILE=/etc/bws4/build.env
HEALTH_URL=http://127.0.0.1:8000/health
PRESETS_URL=http://127.0.0.1:8000/api/embeddings/presets
HEALTH_TIMEOUT_S=180   # warm boot is ~30 s; 180 s means something is wrong, not slow

announce() { echo; echo "==> $*"; }
fail() { echo "DEPLOY FAILED: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

# Run as the operator user, never root: the venv at $REPO/.venv is owned by
# the operator (the unit starts uvicorn with `uv run --no-sync` and never
# writes the venv), and a root-run `uv sync` or npm build would litter the
# checkout with root-owned files that break every later unprivileged deploy.
[[ $EUID -ne 0 ]] || fail "run this as the operator user, not root (sudo is used inline where needed)"
OPERATOR=$(id -un)

cd "$REPO"

# A dirty working tree must surface as a clear abort BEFORE git pull, not as
# a merge conflict halfway through a deploy. Manual edits from earlier
# provisioning phases (or debugging sessions) are exactly the kind of thing
# this catches; the tree is expected to stay clean by construction.
if [[ -n "$(git status --porcelain)" ]]; then
    git status --short >&2
    fail "working tree at $REPO is not clean — commit, stash or discard the changes above first"
fi

# journalctl access for the warm-readiness gate: the operator should be in
# the systemd-journal (or adm) group — a one-time provisioning step in
# deploy/README.md. Fall back to sudo (whose credential is cached by the
# steps below) rather than silently reading an empty per-user journal.
if id -nG | grep -qwE 'systemd-journal|adm'; then
    JCTL=(journalctl)
else
    JCTL=(sudo journalctl)
fi

# ---------------------------------------------------------------------------
# Step 1/5 — git pull
# ---------------------------------------------------------------------------
announce "step 1/5: git pull (in $REPO)"
# --ff-only: if the VPS branch has somehow diverged from upstream, abort
# loudly instead of creating a merge commit on the server. Note the pull may
# update this script itself; the version already executing keeps running —
# any deploy.sh change takes effect on the NEXT run.
git pull --ff-only

# ---------------------------------------------------------------------------
# Step 2/5 — uv sync
# ---------------------------------------------------------------------------
announce "step 2/5: uv sync (locked)"
# UV_PYTHON_INSTALL_DIR: the interpreter lives under /opt/uv/python (moved
# out of /home in Phase 2 because the unit runs with ProtectHome=true).
# Without it uv would resolve/install a 3.12 under ~/.local and relink the
# venv into /home, where the hardened service cannot exec it.
# --locked: the deploy installs exactly uv.lock; it never resolves anew.
UV_PYTHON_INSTALL_DIR=/opt/uv/python "$UV" sync --locked

# ---------------------------------------------------------------------------
# Step 3/5 — frontend build
# ---------------------------------------------------------------------------
announce "step 3/5: npm ci && npm run build (in $FRONTEND)"

# BUILD-time environment — the single easiest thing to get wrong after
# migrating from a platform that showed all variables in one flat list:
# Vite substitutes VITE_-prefixed variables at BUILD time, so the systemd
# EnvironmentFile (which reaches only the running service) does NOT reach
# this step. Getting it wrong fails silently: the bundle simply ships
# without frontend error tracking. Build-time variables therefore come
# from /etc/bws4/build.env (sourced here if present) or, failing that,
# from the invoking shell's environment.
if [[ -r "$BUILD_ENV_FILE" ]]; then
    set -a
    # shellcheck source=/dev/null
    . "$BUILD_ENV_FILE"
    set +a
fi

# @sentry/react is never initialised when VITE_SENTRY_DSN is unset, so an
# unset value is a legitimate configuration (frontend error tracking off)
# and must not abort the deploy — announce it instead so the choice is
# visible in every deploy log.
if [[ -n "${VITE_SENTRY_DSN:-}" ]]; then
    echo "    VITE_SENTRY_DSN is set: frontend Sentry will be ENABLED in this bundle"
    export VITE_SENTRY_DSN
else
    echo "    VITE_SENTRY_DSN is unset: frontend Sentry will be DISABLED in this bundle"
fi

cd "$FRONTEND"
npm ci
# VITE_API_BASE_URL must be the EMPTY STRING, never unset: the api modules
# read `import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'`, and
# the empty string survives `??`, making every request a relative
# same-origin path (/api/..., /health). A bundle built with it UNSET bakes
# localhost:8000 into every chunk and breaks all API calls in visitors'
# browsers — Phase 1 shipped exactly that defect. Empty also keeps the
# bundle indifferent to the Phase 6 hostname change.
# `npm run build` is `tsc -b && vite build`: a type error aborts the deploy
# here, before Vite touches dist/ and before the service is restarted, so a
# broken push leaves the previous build serving untouched.
VITE_API_BASE_URL='' npm run build
cd "$REPO"

# ---------------------------------------------------------------------------
# Step 4/5 — database migrations
# ---------------------------------------------------------------------------
announce "step 4/5: alembic upgrade head (against the external Neon database)"
# Migrations run BEFORE the restart so the new process comes up against a
# schema that already matches the new code. `upgrade head` is idempotent: a
# deploy with no new migration is a no-op that reports the current head.
# There is deliberately no autogenerate, squash or downgrade logic here —
# the migration tree at backend/app/db/migrations/versions/ is authoritative.
#
# Privileges, carefully: DATABASE_URL lives in $RUNTIME_ENV_FILE, which is
# root:root 0600 outside the repository tree and never committed — so this
# step needs root to SOURCE the file, but must not RUN alembic as root
# (root-owned __pycache__/uv-cache droppings would break later unprivileged
# deploys). Root sources the env in a subshell, then drops straight back to
# the operator via runuser with the environment preserved (-p).
#
# CWD matters: alembic.ini's `script_location = app/db/migrations` resolves
# against the working directory, so alembic must run FROM backend/ with
# `-c alembic.ini` (running from the repo root with -c backend/alembic.ini
# fails). --no-sync: step 2 already synced the venv; don't re-resolve here.
sudo bash -c "set -a; . '$RUNTIME_ENV_FILE'; set +a; \
    cd '$BACKEND' && exec runuser -p -u '$OPERATOR' -- \
    env HOME='$HOME' UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    '$UV' run --no-sync alembic -c alembic.ini upgrade head"

# ---------------------------------------------------------------------------
# Step 5/5 — restart the service
# ---------------------------------------------------------------------------
announce "step 5/5: sudo systemctl restart $UNIT"
RESTART_EPOCH=$(date +%s)
sudo systemctl restart "$UNIT"

# ---------------------------------------------------------------------------
# Post-restart readiness gate — the deploy is not done until this passes.
#
# Three checks, in a deliberate order. /health alone is NOT enough: the
# lifespan warm-up is best-effort by design (ensure_built() is wrapped in a
# bare `except Exception` so a broken projection logs and the gallery still
# boots), and /health is deliberately independent of it. A naive health
# check would therefore report success over a healthy-LOOKING process
# serving a cold projection — the exact first-visit defect this migration
# exists to eliminate. We do not change the application's best-effort
# behaviour; we detect its failure from outside, here, and fail the deploy
# loudly instead.
# ---------------------------------------------------------------------------

# Gate A — liveness: poll /health until 200 or timeout. Uvicorn only starts
# accepting connections after the lifespan completes, so the first 200 also
# marks the end of the warm-up attempt (successful or swallowed) and the end
# of the visitor-facing downtime window.
announce "readiness gate A: polling $HEALTH_URL (timeout ${HEALTH_TIMEOUT_S}s)"
HEALTH_EPOCH=""
for (( waited=0; waited < HEALTH_TIMEOUT_S; waited+=2 )); do
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        HEALTH_EPOCH=$(date +%s)
        break
    fi
    sleep 2
done
[[ -n "$HEALTH_EPOCH" ]] || fail "service did not answer $HEALTH_URL within ${HEALTH_TIMEOUT_S}s after restart — check: journalctl -u $UNIT --since @$RESTART_EPOCH"
echo "    /health 200 after $(( HEALTH_EPOCH - RESTART_EPOCH ))s"

# Gate B — warmth, from the journal, scoped to THIS restart (--since the
# moment we issued it, so a record from the previous boot can never
# satisfy the check). Success record `embeddings_projection_built` must be
# present and failure record `embeddings_projection_warmup_failed` absent.
# This must run BEFORE gate C: the presets route builds the projection on
# demand if the warm-up failed, so probing it first would quietly warm a
# cold cache and mask the very failure this gate exists to catch.
announce "readiness gate B: warm-up record in the journal for this boot"
BUILT_RECORD=""
for _ in 1 2 3 4 5; do
    BUILT_RECORD=$("${JCTL[@]}" -u "$UNIT" --since "@$RESTART_EPOCH" -o cat --no-pager 2>/dev/null \
        | grep -F '"event": "embeddings_projection_built"' | tail -n 1 || true)
    [[ -n "$BUILT_RECORD" ]] && break
    sleep 1   # journald can lag a moment behind the process's stdout
done
FAILED_RECORD=$("${JCTL[@]}" -u "$UNIT" --since "@$RESTART_EPOCH" -o cat --no-pager 2>/dev/null \
    | grep -F '"event": "embeddings_projection_warmup_failed"' || true)
if [[ -z "$BUILT_RECORD" || -n "$FAILED_RECORD" ]]; then
    echo "WARNING: the embeddings example app is DEGRADED — the process is serving" >&2
    echo "WARNING: but this boot's projection warm-up did not succeed (the lifespan" >&2
    echo "WARNING: swallows the failure by design, so only this gate catches it)." >&2
    echo "WARNING: inspect: journalctl -u $UNIT --since @$RESTART_EPOCH" >&2
    fail "warm-up record missing or warm-up failure logged for this boot"
fi

# Gate C — corroborate from the outside: the projection route itself must
# answer. With gate B already passed this is expected to be milliseconds
# (warm baseline: single-digit ms); it proves the built cache is actually
# reachable through the running route, not just logged.
announce "readiness gate C: GET $PRESETS_URL"
PRESETS_TIME=$(curl -fsS -o /dev/null -w '%{time_total}' --max-time 30 "$PRESETS_URL") \
    || fail "the embeddings example app is DEGRADED: $PRESETS_URL did not return success"
echo "    presets responded in ${PRESETS_TIME}s"

# ---------------------------------------------------------------------------
# Success summary — record what this release actually cost.
# ---------------------------------------------------------------------------
BUILT_TS=$(sed -n 's/.*"timestamp": "\([^"]*\)".*/\1/p' <<<"$BUILT_RECORD")
BUILT_ELAPSED_MS=$(sed -n 's/.*"elapsed_ms": \([0-9.]*\).*/\1/p' <<<"$BUILT_RECORD")
BUILT_EPOCH=$(date -d "$BUILT_TS" +%s 2>/dev/null || echo "$HEALTH_EPOCH")

announce "deploy OK — $(git -C "$REPO" rev-parse --short HEAD) is live"
echo "    downtime window (restart -> /health 200):      $(( HEALTH_EPOCH - RESTART_EPOCH ))s"
echo "    warm-up (restart -> embeddings_projection_built): $(( BUILT_EPOCH - RESTART_EPOCH ))s"
echo "    projection build itself (elapsed_ms):           ${BUILT_ELAPSED_MS:-unknown}"
echo "    (baselines: ~29.6s fresh start, ~32.3s post-reboot — Phase 2)"
