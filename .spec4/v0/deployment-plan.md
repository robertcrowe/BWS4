# Deployment Plan

## Coding Agent Guidance

Launch Claude Code from inside the project directory — the one containing `.spec4/`. All relative paths depend on this; if a session starts elsewhere, `cd` into the project root first or restart Claude Code there.

Spec4 has already written every planning artifact under `.spec4/v0/`:
- `.spec4/v0/vision.json` — project vision
- `.spec4/v0/stack.json` — technology stack spec
- `.spec4/v0/phases/phase1.md` … `phase7.md` — one file per phase (JSON frontmatter + prose body)

Reference phase files directly in chat using Claude Code's `@`-mention syntax (e.g. `@.spec4/v0/phases/phase1.md`), which pulls the file into context automatically. Work through phases **one at a time**: reference the phase file, have Claude Code implement it fully, then explicitly ask it to run the verification steps defined in that phase's frontmatter (tests, health checks, etc.) and show you the output before moving to the next phase — don't just trust the diff. Start a **fresh session per phase** once verified, to avoid context rot degrading quality on later phases.

Create a `CLAUDE.md` at the project root early on, summarizing stack choices, conventions, and the `.spec4/v0/` structure — Claude Code auto-loads this every session, saving you from re-explaining context each time you start fresh for a new phase.

**Known pitfall:** Claude Code will happily generate plausible-looking code that skips a phase's stated verification step if you don't ask for it explicitly — always demand and review the verification output.

## Target

### `web_client`

- **Type:** paas
- **Provider:** Render
- **Service:** Static Site (free tier, no spin-down, served via CDN)
- **Build:** Vite build producing a hashed static bundle with route-based lazy-loaded chunks per example app
- **Transport:** HTTPS only
- **CORS:** N/A (serves the browser origin; does not need to apply a CORS policy itself)

### `api`

- **Type:** paas
- **Provider:** Render
- **Service:** Web Service (free tier — spins down after ~15 min idle, cold-starts on next request, 750 free instance-hours/month)
- **Runtime:** Python 3.12, containerized (Docker build from repo)
- **Transport:** HTTPS only
- **CORS:** allow only the `web_client`'s own origin

## Containerization

- **Enabled:** Yes
- **Base image:** `python:3.12-slim` (currently `slim-bookworm`; confirmed current recommendation for FastAPI services)
- **Registry:** none needed — Render builds the image directly from the Dockerfile in the connected repo at deploy time

## CI/CD

- **Enabled:** Yes (build/test only — deploy is manually triggered, not automatic on push)
- **Platform:** GitHub Actions
- **Trigger branch:** `main`
- **Stages:** build → test (automatic on every push); deploy is a separate manual step (Render's dashboard "Manual Deploy" or a manually-dispatched `workflow_dispatch` job)

## Environment

**Required variables:**
- `DATABASE_URL` — Neon pooled connection string
- `CORS_ORIGIN` — the web_client's own origin
- `VITE_API_BASE_URL` — points the SPA at the API
- `EMBEDDING_MODEL_NAME` — optional, defaults to `sentence-transformers/all-MiniLM-L6-v2`
- `OPENROUTER_API_KEY` — required (OpenRouter via LiteLLM credentials)
- `GENERATION_DAILY_LIMIT` — free-tier usage cap
- `EMBEDDING_DAILY_LIMIT` — free-tier usage cap
- `EXA_API_KEY` — required (Exa search integration)
- `SENTRY_DSN` — optional, backend, must no-op if unset
- `VITE_SENTRY_DSN` — optional, frontend, must no-op if unset

`PORT` is set automatically by Render for web services and does not need to be configured manually.

**Secrets management:** Render's native environment variable manager (encrypted at rest, injected at runtime) for production; `.env` files (gitignored) for local development only.

## Monitoring

- **Error tracking:** Sentry (frontend + backend)
- **Metrics:** UptimeRobot or Better Stack (free tier) — periodic pings against the API, also helps mitigate free-tier cold-start spin-down during demos
- **Model observability:** Sentry performance spans/breadcrumbs around LiteLLM/OpenRouter calls, plus structured stdout logs (visible via Render's log viewer) for token usage and latency
- **Eval cadence:** pre-deploy only — run the offline eval suite before any deploy that changes the prompt, model choice, or retrieval logic (chunking/embedding pipeline); no scheduled/online evals
- **Feedback loop:** none beyond error tracking — this is a fixed teaching demo over a curated dataset, not a product iterating on user feedback
- **Safety/guardrails:** refusal/filter events emitted by the app's in-code safety logic are tagged distinctly in Sentry for operational visibility into frequency

## Deployment Steps

### 1. Create the Neon Postgres project and enable pgvector

Provision the durable store that doubles as the vector index for the RAG example app.

```shell
# Via Neon's dashboard: create a new project, note the pooled connection string.
# Then, connected via psql or Neon's SQL editor, enable pgvector:
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. Create the Render Web Service for the API

Connect your GitHub repo, select Docker as the environment, and set the root/Dockerfile path.

```shell
# Via Render dashboard (or Render CLI if installed):
render services create web \
  --name rag-gallery-api \
  --repo <your-github-repo-url> \
  --branch main \
  --env docker \
  --plan free \
  --region oregon
```

Then configure environment variables in the Render dashboard for this service:
`DATABASE_URL`, `CORS_ORIGIN`, `EMBEDDING_MODEL_NAME`, `OPENROUTER_API_KEY`, `GENERATION_DAILY_LIMIT`, `EMBEDDING_DAILY_LIMIT`, `EXA_API_KEY`, `SENTRY_DSN`.

### 3. Create the Render Static Site for the web client

```shell
render services create static \
  --name rag-gallery-web \
  --repo <your-github-repo-url> \
  --branch main \
  --build-command "npm run build" \
  --publish-path "dist"
```

Set `VITE_API_BASE_URL` (pointing to the API's Render URL) and `VITE_SENTRY_DSN` as build-time environment variables in the Render dashboard for this service.

### 4. Update CORS_ORIGIN on the API once the Static Site URL is known

```shell
# In Render dashboard, update the API service's CORS_ORIGIN env var
# to the Static Site's live URL (e.g. https://rag-gallery-web.onrender.com)
```

### 5. Wire up Sentry projects

```shell
# Create two Sentry projects (or one with separate DSNs): one for the FastAPI backend, one for the React frontend.
# Add the resulting DSNs as SENTRY_DSN and VITE_SENTRY_DSN respectively in each Render service's environment variables.
```

### 6. Set up uptime monitoring

```shell
# Via UptimeRobot or Better Stack dashboard:
# Add an HTTP(S) monitor targeting the API's health-check endpoint
# (e.g. https://rag-gallery-api.onrender.com/health), interval every 5 minutes.
```

### 7. First manual deploy

```shell
# Push to main triggers GitHub Actions build/test only.
# To deploy after CI passes, trigger manually via Render dashboard "Manual Deploy",
# or via Render CLI:
render deploys create --service rag-gallery-api
render deploys create --service rag-gallery-web
```

## Configuration Files

### `Dockerfile`

Builds the FastAPI backend on a slim Python 3.12 base image, installing dependencies (including torch/sentence-transformers) with no build cache to keep the image lean.

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

### `.github/workflows/ci.yml`

Runs build and test on every push to `main`. Deployment is intentionally **not** included here — it's triggered manually via Render's dashboard or CLI once CI passes.

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

### `.env.example` (local development only)

Documents the variables developers need locally; never committed with real values.

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

- **Roadmap (recorded, not built):** Playwright is deferred and not part of this deployment's CI/CD or infrastructure. Do not add browser-based E2E testing to the pipeline until it's promoted off the roadmap.
- **Cost:** This deployment is designed to run entirely on free tiers — Render Static Site (free, no spin-down), Render Web Service (free, 750 instance-hours/month, spins down after 15 min idle), Neon (free tier, persists indefinitely unlike Render's own free Postgres which expires after 30 days), Sentry (free tier), UptimeRobot/Better Stack (free tier), and OpenRouter's free-tier models with LiteLLM fallback routing.
- **Non-functional goals — what this deployment addresses and where:**
  - *Free/no-cost operation*: satisfied directly by the choice of Render free tiers + Neon free tier throughout this plan.
  - *Responsiveness (not sluggish)*: addressed via the Static Site's CDN (no spin-down) for the frontend, and via uptime pinging to reduce API cold-start frequency for the backend; the RAG feature's p95 2.5s latency budget informs the Sentry performance-span monitoring set up above, but actually meeting that budget is the coding agent's responsibility (efficient retrieval/generation code), not the deployment's.
  - *New example apps added without disrupting existing ones*: this is a frontend routing/code-splitting concern (React Router, Vite lazy chunks) — belongs to the coding agent, not this deployment plan.
  - *Consistent look/feel across example apps*: Tailwind CSS — a coding-agent concern.
  - *Teaching-clarity of the RAG pattern*: the chunking pipeline's simplicity is a coding-agent concern; this deployment's contribution is making failures legible (Sentry tagging of guardrail events and errors) rather than silent, so a confused visitor's dead-end doesn't look like an unexplained crash.
  - *Answer correctness, citation verifiability, refusal behavior, tone, coherence*: these belong entirely to the coding agent's implementation (prompts, retrieval quality, safety logic) — no hosting or infrastructure choice in this plan makes an answer correct or a citation verifiable.