# BWS4 — Agent Context

## Hard invariants

- **Secrets never enter the repository.** Runtime configuration lives in
  `/etc/bws4/bws4.env` on the VPS — root-owned, chmod 0600, outside the
  repository tree. Never create a `.env` file inside this repo. Committed
  files reference environment variable NAMES only, never values.
- **The API runs with `--workers 1`.** This is a requirement, not a default.
  The loaded embedding model, the fitted PCA projection, the in-process peer
  message bus and the ReAct duplicate-guard cache are all per-process state.
  Never add workers, never suggest Gunicorn with multiple workers.
- **Postgres is external.** Neon + pgvector, unchanged by the VPS migration.
  Never propose installing Postgres on the host.

## Deployment shape

- Host: netcup VPS 500 G12, Debian 13 (trixie), 2 vCore / 4 GB / 128 GB NVMe
- Repo on host: `/srv/bws4`; frontend build output: `/srv/bws4/frontend/dist`
- Caddy serves `dist/` with SPA history fallback, reverse-proxies `/api/*`
  to `127.0.0.1:8000` with `flush_interval -1`
- systemd unit: `bws4-api`; release script: `deploy/deploy.sh`
- Canonical origin: `https://bw.spec4.ai` (staging: `https://bwtemp.spec4.ai`)

## Environment contract (names only)

Required: `DATABASE_URL`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`,
`EXA_API_KEY`, `OPENAI_API_KEY`, `CORS_ORIGIN`
Optional: `SENTRY_DSN` (runtime), `VITE_SENTRY_DSN` (build-time only —
the systemd EnvironmentFile does NOT reach `npm run build`)

## Quality gates (developer-run, no CI)

`ruff`, `mypy`, `pytest`, `vitest` — run before push.
