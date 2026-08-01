# Deployment Plan

## Coding Agent Guidance

Launch Claude Code from inside the project directory — the one containing `.spec4/`. All relative paths depend on this; if a session starts elsewhere, `cd` into the project root first or restart Claude Code there.

Spec4 has written this revision's planning artifacts under a new version directory, `.spec4/v1/`, alongside the original `.spec4/v0/`:
- `.spec4/v1/vision.json` — updated project vision
- `.spec4/v1/stack.json` — updated technology stack spec
- `.spec4/v1/phases/phase1.md` … `phase5.md` — Embeddings App phases: skeleton wiring → preset embedding/2D projection service → custom text placement backend → UI (preset plot, explanation, navigation) → custom text submission (frontend)

Reference phase files directly in chat using Claude Code's `@`-mention syntax (e.g. `@.spec4/v1/phases/phase1.md`), which imports the file into context automatically. This is the same syntax used in the original build — only the version path has changed. Work through phases **one at a time**: reference the phase file, have Claude Code implement it fully, then explicitly ask it to run the verification steps defined in that phase's frontmatter and show you the output before moving to the next phase. Start a **fresh session per phase** once verified, to avoid context rot.

Update your existing project-root `CLAUDE.md` to point at the active phase set for this round — add a line such as `Active phases: .spec4/v1/phases/` so Claude Code doesn't default to stale `v0` assumptions when it auto-loads `CLAUDE.md` each session.

**Known pitfall:** Claude Code will happily generate plausible-looking code that skips a phase's stated verification step if you don't ask for it explicitly. This matters especially for Phase 2/3 here, since they touch the in-memory PCA/embedding cache — code that "looks done" without validating the projection is actually stable is an easy trap.

## Target

### `web_client`

- **Type:** paas
- **Provider:** Render
- **Service:** Static Site (free tier, no spin-down, served via CDN)
- **Build:** Vite build producing a hashed static bundle with route-based lazy-loaded chunks per example app — this revision adds one new lazy-loaded chunk for the Embeddings example app; no change to hosting
- **Transport:** HTTPS only
- **CORS:** N/A (serves the browser origin; does not need to apply a CORS policy itself)

### `api`

- **Type:** paas
- **Provider:** Render
- **Service:** Web Service (free tier — spins down after ~15 min idle, cold-starts on next request, 750 free instance-hours/month)
- **Runtime:** Python 3.12, containerized (Docker build from repo) — this revision adds a new router for embeddings endpoints (preset projection, custom text placement) to the existing service; no new service
- **Transport:** HTTPS only
- **CORS:** allow only the `web_client`'s own origin (unchanged)

## Containerization

- **Enabled:** Yes (unchanged from baseline)
- **Base image:** `python:3.12-slim`
- **Registry:** none needed — Render builds the image directly from the Dockerfile in the connected repo at deploy time

## CI/CD

- **Enabled:** Yes (unchanged from baseline)
- **Platform:** GitHub Actions
- **Trigger branch:** `main`
- **Stages:** build → test (automatic on every push); deploy remains a manual step (Render dashboard "Manual Deploy" or `workflow_dispatch`)

## Environment

**Required variables:** unchanged — this revision adds none.
- `DATABASE_URL` — Neon pooled connection string
- `CORS_ORIGIN` — the web_client's own origin
- `VITE_API_BASE_URL` — points the SPA at the API
- `EMBEDDING_MODEL_NAME` — optional, defaults to `sentence-transformers/all-MiniLM-L6-v2`; the new embeddings app reuses this same shared model rather than introducing a second one
- `OPENROUTER_API_KEY` — required (unused by the embeddings feature itself, still required for RAG)
- `GENERATION_DAILY_LIMIT` — free-tier usage cap
- `EMBEDDING_DAILY_LIMIT` — free-tier usage cap
- `EXA_API_KEY` — required (unused by the embeddings feature itself, still required for tool-use)
- `SENTRY_DSN` — optional, backend, must no-op if unset
- `VITE_SENTRY_DSN` — optional, frontend, must no-op if unset

`PORT` remains set automatically by Render for web services.

**Secrets management:** unchanged — Render's native environment variable manager (encrypted at rest, injected at runtime) for production; `.env` files (gitignored) for local development only.

## Monitoring

- **Error tracking:** Sentry (frontend + backend) — unchanged
- **Metrics:** UptimeRobot or Better Stack (free tier) — unchanged
- **Model observability:** existing Sentry performance-span instrumentation, previously wrapping LiteLLM/OpenRouter calls, is **extended in this revision** to also wrap the new embeddings endpoints (preset embedding/2D projection, custom text semantic placement), so their latency shows up in the same dashboard used for RAG's p95 tracking. Note: unlike RAG, the embeddings tier is local in-process compute (sentence-transformers + PCA), not a metered external API call, so there is no token-usage/cost dimension to capture here — only latency and error rate.
- **Eval cadence:** unchanged — pre-deploy offline eval suite runs only for changes to the RAG prompt, model choice, or retrieval logic. Not extended to the embeddings model or PCA/projection logic (developer's explicit choice this round) — noted as a known gap rather than an oversight, since the embeddings pipeline shares the same underlying model as RAG and future model changes would touch both.
- **Feedback loop:** none — unchanged; this remains a fixed teaching demo, not a product iterating on user feedback. Not applicable to the embeddings feature.
- **Safety/guardrails:** unchanged, RAG-scoped only. The Embeddings example app has no generation, no LLM call, and no refusal surface — it is a deterministic embed-then-project transform — so no guardrail logic applies here. Recorded as unclaimed for this feature rather than invented.

## Deployment Steps

No new infrastructure needs to be provisioned for this revision — the existing Render services, Neon database, and Sentry projects already cover the new surface. The only actions are code deploy and monitoring configuration.

### 1. Verify existing environment variables remain set

Confirm no drift before deploying the new router/routes — no new variables are being added.

```shell
# Via Render dashboard, or Render CLI:
render env list --service rag-gallery-api
```

Expected to already include: `DATABASE_URL`, `CORS_ORIGIN`, `EMBEDDING_MODEL_NAME`, `OPENROUTER_API_KEY`, `GENERATION_DAILY_LIMIT`, `EMBEDDING_DAILY_LIMIT`, `EXA_API_KEY`, `SENTRY_DSN`.

### 2. Confirm bundled preconfigured embedding assets are included in the build

The `embedding_projection_cache` is rebuilt at process startup/first request from `bundled_assets`' preconfigured text examples — these are static, read-only content shipped at build time, not runtime-fetched. Ensure the asset files are committed to the repo and included in the Docker build context (no separate provisioning step).

```shell
# Sanity check locally before pushing:
docker build -t rag-gallery-api-check .
docker run --rm rag-gallery-api-check python -c "from app.embeddings import preset_cache; preset_cache.build(); print('OK')"
```

### 3. Deploy the updated API and web client

Standard manual deploy, unchanged process from baseline — push triggers CI (build/test only), then deploy manually once CI passes.

```shell
git push origin main
# After GitHub Actions CI passes:
render deploys create --service rag-gallery-api
render deploys create --service rag-gallery-web
```

### 4. Extend Sentry performance instrumentation to the new endpoints

Wrap the new embeddings endpoints (preset projection, custom text placement) with the same Sentry performance-span pattern already used for LiteLLM/OpenRouter calls, so their latency appears in the existing Sentry performance dashboard. This is an application-code change (in the FastAPI router), verified post-deploy by exercising the endpoints and checking spans appear.

```shell
# After deploy, exercise both new endpoints to confirm spans are captured:
curl -s https://rag-gallery-api.onrender.com/embeddings/presets | jq .
curl -s -X POST https://rag-gallery-api.onrender.com/embeddings/custom \
  -H "Content-Type: application/json" \
  -d '{"text": "sample sentence for placement check"}' | jq .
# Then check the Sentry Performance dashboard for the new transaction names.
```

### 5. Manually verify cold-start latency behavior against the budget

Since the cache builds lazily on first request, confirm the accepted trade-off in practice: trigger a cold start (let the service idle 15+ min) and time the first request against the 600ms p95 budget for `custom_text_semantic_placement`. This isn't a gate — it's a documented, accepted characteristic — but it's worth confirming once that subsequent (warm) requests do land inside budget.

```shell
# After ~15 min of no traffic to rag-gallery-api:
time curl -s -X POST https://rag-gallery-api.onrender.com/embeddings/custom \
  -H "Content-Type: application/json" \
  -d '{"text": "cold start timing check"}' > /dev/null
# Then immediately repeat to confirm warm-path latency:
time curl -s -X POST https://rag-gallery-api.onrender.com/embeddings/custom \
  -H "Content-Type: application/json" \
  -d '{"text": "warm path timing check"}' > /dev/null
```

## Configuration Files

No new or modified configuration files are required for this revision. The existing `Dockerfile`, `.github/workflows/ci.yml`, and `.env.example` from the baseline deployment remain accurate as-is:

### `Dockerfile` (unchanged)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies needed for building some Python packages (e.g. torch deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `.github/workflows/ci.yml` (unchanged)

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install backend dependencies
        run: |
          cd api
          pip install --no-cache-dir -r requirements.txt

      - name: Run backend tests
        run: |
          cd api
          pytest

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: web/package-lock.json

      - name: Install frontend dependencies
        run: |
          cd web
          npm ci

      - name: Run frontend tests
        run: |
          cd web
          npm test -- --run

      - name: Build frontend
        run: |
          cd web
          npm run build
```

### `.env.example` (unchanged, local development only)

```shell
DATABASE_URL=postgresql+asyncpg://user:pass@host/db?sslmode=require
CORS_ORIGIN=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
OPENROUTER_API_KEY=
GENERATION_DAILY_LIMIT=100
EMBEDDING_DAILY_LIMIT=500
EXA_API_KEY=
SENTRY_DSN=
VITE_SENTRY_DSN=
```

## Notes

- **Roadmap (recorded, not built):** Playwright remains deferred and out of scope for this revision's CI/CD or infrastructure.
- **Cost:** No change to the free-tier cost posture. The Embeddings example app adds no new paid resources — it reuses the existing Render Static Site, Render free Web Service, and Neon free-tier Postgres. The `embedding_projection_cache` is in-process memory, not a new datastore.
- **Scope discipline for this revision:** Per the developer's explicit choices, this round does **not** extend the pre-deploy eval trigger to embedding/PCA logic changes, and does not build a feedback loop or safety/guardrail logic for the embeddings feature — these are recorded here so they aren't silently dropped, but they are not being provisioned or built in this deployment.
- **Non-functional goals — what this deployment addresses and where (this revision):**
  - *"Interactions within example apps feel responsive enough for live demonstration"* (claimed by preconfigured_example_embeddings, scikit-learn): this deployment's contribution is the lazy-build decision for `embedding_projection_cache` and the Sentry performance-span extension that makes the p95 600ms budget for custom text placement observable — but actually meeting that budget on the warm path is the coding agent's responsibility (efficient PCA transform code), and the cold-start exception is an explicitly accepted trade-off rather than something infrastructure fixes.
  - *"The platform operates using only free-tier language, embedding, and search resources"*: no stack component claims this as an infrastructure feature, and this revision doesn't change that posture — it remains addressed by the unchanged choice of Render/Neon free tiers plus OpenRouter's free-tier models, carried forward from baseline.
  - *"All example apps present a consistent, unified look and navigation experience"* and *"New example apps can be added without disrupting existing ones"*: both are frontend routing/design-system concerns (React Router, Vite lazy chunks, shared component library) — belong entirely to the coding agent, not this deployment plan. Adding this app via a new lazy-loaded chunk is structurally supportive of the second goal, but the actual non-disruption guarantee is a code-quality outcome, not an infrastructure one.
  - *"The system degrades gracefully and communicates clearly when a free-tier usage limit is reached"*: no stack component claims this; it remains unclaimed by infrastructure and is the coding agent's responsibility to implement (e.g. handling `GENERATION_DAILY_LIMIT`/`EMBEDDING_DAILY_LIMIT` exhaustion in application logic).
  - As with the baseline, none of these goals are satisfied by hosting or infrastructure choices where the goal is fundamentally a code-quality outcome (correctness, consistency, graceful degradation logic) — this plan is explicit about the difference rather than claiming credit it hasn't earned.