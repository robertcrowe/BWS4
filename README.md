# Built with Spec4 (BWS4)

## Overview

Built with Spec4 (BWS4) is a living showcase of common AI application patterns, presented as a collection of small, self-contained example apps behind a single landing page. Each example — starting with Retrieval-Augmented Generation (RAG) and tool-use via web search — demonstrates one pattern end-to-end: how it's built, what it depends on, and how it behaves, so that visitors unfamiliar with the underlying technique can understand it by seeing it work rather than by reading about it abstractly.

The gallery is designed to grow. New example apps can be added over time without disrupting the availability of existing ones, thanks to per-example code-splitting on the frontend and a shared set of backend framework services (generation, embedding, storage) that every example app draws on. Every example runs entirely within free, no-cost usage limits, making the whole project easy to fork, run locally, and deploy without a billing surprise.

## Key Features

- **Landing page & example app directory** — a consistent entry point listing every example app in the gallery, with a uniform look, feel, and navigation pattern across all of them.
- **RAG example app** — a full retrieval-augmented generation pipeline: a curated reference dataset is chunked, embedded, and indexed; user questions are answered by retrieving the most relevant passages and grounding a generated response in them.
- **Tool-use example app** — a live web-search integration (via Exa) demonstrating how an LLM can call out to an external tool mid-conversation to answer questions beyond its own knowledge.
- **Shared framework services** — common generation, representation, and storage capabilities reused across example apps, so each new pattern only needs to add what's unique to it.
- **Route-based code-splitting** — each example app is lazy-loaded independently, keeping the initial page load light as the gallery grows.
- **Light/dark theming** — a visitor's theme preference is remembered locally across visits.
- **Built-in observability** — optional, zero-config error tracking and model-call observability that no-ops cleanly when not configured, so the project runs the same whether or not monitoring is wired up.

## Technology Stack

**Frontend (`web_client`)**
- TypeScript
- React Router (client-side routing, per-example lazy-loaded chunks)
- Tailwind CSS (consistent styling across all example apps)
- Vite (build tool, producing a hashed static bundle)

**Backend (`api`)**
- Python 3.12
- FastAPI (REST API, with an auto-generated OpenAPI schema)
- SQLAlchemy (data access, including pgvector cosine-distance queries)
- sentence-transformers (`all-MiniLM-L6-v2`) for embeddings, run in-process
- LiteLLM, routing to OpenRouter and Groq — every example app calls models through one shared registry (`backend/app/services/model_registry.py`), which walks an ordered chain of free-tier models on failure and benches any slug a provider has withdrawn. The chains are per capability (tool calling vs. structured generation) because the two are verified separately; both rot as providers retire free slugs, so expect to refresh them
- Exa (web search API), exposed as a shared framework capability in `backend/app/services/web_search.py` and used today by the tool-use example app

**Data & storage**
- Neon — serverless Postgres with the `pgvector` extension, used both as the primary relational store and as the vector index for the RAG example
- Bundled static assets — read-only content shipped at build time
- Browser `localStorage` — theme preference only, not a source of truth

**Retrieval & indexing**
- A hand-rolled sentence-aligned chunking pipeline with overlapping windows (kept intentionally simple and transparent for teaching purposes)
- Each passage is embedded with its source title prepended, so a chunk that says "It launched in 1977" is still reachable by a question naming Voyager
- Embeddings written to and read from a `dataset_embeddings` table
- Retrieval via SQLAlchemy queries using pgvector's cosine-distance operator
- Generated answers are audited against the passages they cite, so a response is only reported as grounded when it actually cites one

**Observability**
- Sentry (frontend and backend error tracking, and performance spans around LLM calls)

## Prerequisites

- Node.js 20+ and npm
- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- A [Neon](https://neon.tech) account and project (free tier) with the `pgvector` extension enabled
- An [OpenRouter](https://openrouter.ai) API key
- An [Exa](https://exa.ai) API key
- (Optional) A [Sentry](https://sentry.io) project and DSN, for error tracking

## Installation & Setup

The repository is a monorepo with a single `uv`-managed Python project at the root
(`backend/`) and a Vite/React app in `frontend/`. Configuration for **both** lives in
one `.env` file at the repo root.

1. **Clone the repository**

   ```shell
   git clone <this-repository-url>
   cd BWS4
   ```

2. **Set up the database**

   Create a Neon project, copy its **pooled** connection string, then enable `pgvector`:

   ```shell
   psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

3. **Configure the environment**

   ```shell
   cp .env.example .env
   # Fill in the values in .env (see Configuration below)
   ```

4. **Install dependencies and apply migrations**

   ```shell
   uv sync
   npm install --prefix frontend
   cd backend && uv run --project .. alembic upgrade head && cd ..
   ```

5. **Index the RAG reference dataset** (once, and after any dataset change)

   ```shell
   uv run python -m backend.app.rag.index_dataset
   ```

   > On a brand-new database, migration `0003` builds the pgvector HNSW index and should
   > run *after* this script has populated `dataset_embeddings` — stop at `0002`, index,
   > then `alembic upgrade head`. The script is idempotent, so re-running it later is safe.

## Running the Application

**Backend (from the repo root):**

```shell
uv run uvicorn backend.app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`, with its OpenAPI schema at `http://localhost:8000/docs`.

**Frontend:**

```shell
npm run dev --prefix frontend
```

The app will be available at `http://localhost:5173` (or the port Vite reports), and will talk to the backend at the URL configured in `VITE_API_BASE_URL`.

**Tests:**

```shell
uv run pytest backend/tests
npm run test --prefix frontend
```

### Using the app

- Open the landing page to see every available example app.
- Select **RAG** to ask questions against the curated reference dataset — the app retrieves relevant passages and generates an answer from them, showing every passage it retrieved and marking which ones the answer actually cited. Two different failure modes are worth trying: `What's the best pizza topping?` is rejected by the retriever before any model runs, while `Who was the first woman in space?` scores *above* the similarity threshold on the dataset's Gagarin passages and is caught only by the citation audit — a reminder that a good similarity score is not evidence the dataset contains the answer.
- Select **Tool-Use** to watch a real function-calling loop. The model is given a `web_search` tool schema and decides for itself whether to call it, writes its own search query, reads the results, and may search again before answering. The trace shown under each run is what the model actually did — including choosing *not* to search, which you can see by asking it something like `What is 17 times 24?`.
- Toggle light/dark mode from the header; your preference is remembered on your device.

## Configuration

All configuration is via environment variables, read from the repo-root `.env` file
(and from the process environment, which takes priority). Reference variable **names**
only — set actual values in your local `.env` (never commit it) or in your deployment
platform's secrets manager.

**Backend (`api`)**

| Variable | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | ✅ | Neon pooled Postgres connection string. Must be asyncpg-style: `postgresql+asyncpg://…?ssl=require` — *not* the `postgresql://…?sslmode=require` form Neon shows by default. |
| `CORS_ORIGIN` | ✅ | The deployed frontend's exact origin. The API allows this single origin and never `*`. |
| `OPENROUTER_API_KEY` | ✅ | Answer generation via LiteLLM → OpenRouter. Used by the RAG example app and as the tool-use agent's fallback provider. |
| `GROQ_API_KEY` | — | Optional second LLM provider for the tool-use agent. Groq's free tier is metered **per model** (1,000+ requests/day each) rather than as one account-wide pool, so it leads the chain when set. Unset → `groq/` entries are dropped and OpenRouter serves alone. |
| `EXA_API_KEY` | ✅ | Live web search, called by the tool-use agent when *it* decides to search. |
| `PORT` | — | Defaults to `8000`; supplied automatically by Render. Don't leave it blank in `.env` — an empty value fails `int` parsing at startup. |
| `EMBEDDING_MODEL_NAME` | — | Defaults to `sentence-transformers/all-MiniLM-L6-v2`. |
| `GENERATION_DAILY_LIMIT` | — | Daily cap on generation calls (free-tier guardrail, default 100). |
| `EMBEDDING_DAILY_LIMIT` | — | Daily cap on embedding calls (default 50). |
| `STORAGE_DAILY_LIMIT` | — | Daily cap on storage calls (default 300). |
| `SEARCH_DAILY_LIMIT` | — | Daily cap on Exa search calls (default 30). One tool-use request may run up to 3 searches, so 30 is a floor of ~10 agent runs per day. |

| `SENTRY_DSN` | — | Optional error tracking. **Unset → Sentry is never initialized** and the app runs normally. |
| `SENTRY_ENVIRONMENT` | — | Environment tag on Sentry events (default `development`). |
| `HF_HOME` | — | Where the sentence-transformers model is cached. Set on Render so the build-time download survives into the running service; unset locally, where it defaults to `~/.cache/huggingface`. |
| `HF_TOKEN` | — | Optional. Raises Hugging Face's anonymous download rate limit. The embedding model is public, so no token is needed to fetch it. |

All four caps are **per UTC day** and reset at 00:00 UTC — `usage_limits.window_start`
records the day each counter belongs to, and the counter rolls over on the first
reservation of a new day. No cron job or manual intervention is involved. There is
no in-app surface for these counters; query `usage_limits` and `service_log_entries`
directly when you need to see them.

The four required variables fail fast at startup with a descriptive error if missing.

**Frontend (`web_client`)**

| Variable | Required | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | ✅ | The backend API's base URL (defaults to `http://localhost:8000` in dev). |
| `VITE_SENTRY_DSN` | — | Optional error tracking, reporting to the same Sentry project as the backend. **Unset → Sentry is never initialized.** |

Vite inlines `VITE_*` variables at build time, so the frontend must be **rebuilt** after
changing either of them.

### Free-model troubleshooting

The tool-use agent walks an ordered model chain that spans **two providers** — Groq first,
OpenRouter behind it — so an outage or a quota wall at either still leaves working entries.
LiteLLM walks the chain on the real request; nothing is probed in the request path. (The RAG
example's answer generation is separate and still OpenRouter-only.)

Two failure modes worth telling apart:

- **`429 Rate limit exceeded: free-models-per-day`.** OpenRouter's free tier is an
  account-wide daily cap (50 requests on an unfunded account) shared with the RAG app, reset
  at midnight UTC — not a code problem and not specific to any model. Groq's limits are
  per-model instead, which is why it leads the chain. The agent surfaces an exhausted chain
  as *"the agent's language model is temporarily unavailable"*. Nothing is benched: a 429
  means busy, not gone.
- **`404 No endpoints found` / `unavailable for free`.** The slug has been withdrawn from the
  free tier. These rot regularly. The slug is benched for 30 minutes — across *every*
  example app, since a withdrawn model is withdrawn for all of them — and the request walks
  the rest of the chain. If the whole chain has rotted, re-run discovery and paste the
  result into `model_registry.TOOL_MODEL_CHAIN`:

  ```shell
  uv run python -m backend.app.services.discover_models
  ```

  That probes every free tool-capable slug in the live catalogue for whether it *actually*
  emits well-formed tool calls and consumes tool results — the catalogue's own `tools` flag
  only means the endpoint accepts a `tools` array. Note that a full discovery run costs
  roughly 30 requests against the same daily cap, so run it once, not in a loop.

  Discovery probes for *tool calling*. `model_registry.GENERATION_MODEL_CHAIN` — the chain
  behind the RAG example's answers — needs a different check: that the model returns
  schema-valid JSON and emits no citation markers when it declines to answer. A model that
  passes one probe can fail the other (`groq/openai/gpt-oss-20b` is excluded from the tool
  chain and shipped in the generation chain), so don't move slugs between the two chains
  without re-verifying.

## Deployment

This project is designed to run entirely on free hosting tiers. A [`render.yaml`](./render.yaml)
blueprint at the repo root defines both targets; you can either point Render at it
(**New → Blueprint**) or create the two services by hand with the settings below.

**`bws4-web` — the frontend, as a Render Static Site** (CDN-served, no spin-down)

| Setting | Value |
| --- | --- |
| Root directory | `frontend` |
| Build command | `npm ci && npm run build` |
| Publish directory | `dist` |
| Rewrite rule | `/*` → `/index.html` (client-side routing) |
| Env vars | `VITE_API_BASE_URL` (the API service's URL), optional `VITE_SENTRY_DSN` |

**`bws4-api` — the backend, as a Render free Web Service** (Python 3.12)

| Setting | Value |
| --- | --- |
| Root directory | `.` (repo root) |
| Runtime | Python 3.12 (`PYTHON_VERSION=3.12`) |
| Build command | `pip install uv && uv sync --frozen --no-dev`, followed by the embedding-model prefetch (see `render.yaml`) |
| Start command | `uv run uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |
| Env vars | `DATABASE_URL`, `CORS_ORIGIN`, `OPENROUTER_API_KEY`, `EXA_API_KEY`, `HF_HOME`, optional `SENTRY_DSN` / `SENTRY_ENVIRONMENT` / `HF_TOKEN` |

The API embeds text **in-process** with sentence-transformers rather than calling a hosted
embedding API, so the ~88 MB `all-MiniLM-L6-v2` model has to be on disk before the first
question can be answered. The build command downloads it into `HF_HOME`
(`/opt/render/project/src/.hf-cache`, inside the project directory) so it ships with the
build instead of being fetched on the first request. Both variables must be set, and
`HF_HOME` must point to the same path at build time and run time — otherwise the running
service silently re-downloads the model on every cold start.

**Deployment steps**

1. Create the Neon database, enable `pgvector`, and run the Alembic migrations against it (see the ordering note in step 5 of *Installation & Setup*).
2. Run `uv run python -m backend.app.rag.index_dataset` once so the RAG example has embeddings to retrieve.
3. Deploy `bws4-api` first, and note the URL Render assigns it.
4. Deploy `bws4-web` with `VITE_API_BASE_URL` set to that API URL.
5. Set the API's `CORS_ORIGIN` to the static site's exact origin (e.g. `https://bws4-web.onrender.com`) and redeploy the API. The blueprint wires this automatically via `fromService`.

> **Free-tier cold starts.** The `bws4-api` service spins down after roughly **15 minutes
> of inactivity**. The next request wakes it, which can take **30–60 seconds** — including
> time to load the (already-downloaded) sentence-transformers embedding model into memory.
> A slow first request after an idle period is expected behavior, not a broken
> deployment. If cold starts are much slower than that, check that `HF_HOME` matches
> between build and run time — a mismatch turns every cold start into a fresh 88 MB
> model download. An external
> uptime checker (UptimeRobot, Better Stack) pinging `/health` keeps the service warm
> during demos. The static frontend is CDN-served and never spins down.

Other deployment notes:

- **HTTPS only**: Render terminates TLS and issues certificates for both services; the static site redirects HTTP → HTTPS. Set `VITE_API_BASE_URL` and `CORS_ORIGIN` to `https://` URLs.
- **CORS**: the API allows exactly one origin — whatever `CORS_ORIGIN` is set to — rather than `*`. Requests from any other origin are rejected by the browser's preflight.
- **Database**: Neon's free tier, which — unlike many providers' free Postgres offerings — persists indefinitely rather than expiring after a fixed window.
- **Deploys are manual** (`autoDeploy: false`) rather than automatic on every push.
- **Error tracking**: Sentry, wired up via `SENTRY_DSN` / `VITE_SENTRY_DSN`. Both sides no-op cleanly when their DSN is unset, so local dev and forks need no Sentry account at all.

## Roadmap

- **Playwright** — end-to-end browser testing is planned but not yet part of this project's test suite or CI pipeline.
- Additional example apps demonstrating further AI patterns, added incrementally without affecting existing ones.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for how the project is
governed, how to set up a development environment, and the conventions a pull request is
expected to follow. All contributors agree to the
[Contributor License Agreement](CLA.md); for individuals this is handled automatically on
your first pull request.

## License

The code in this repository is licensed under the **Apache License 2.0** — see
[LICENSE](LICENSE).

The RAG reference dataset under `backend/app/rag/dataset/` is **not** covered by that
license. Those documents are adapted from Wikipedia and are licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); each file records its own
source and license. CC BY-SA is a share-alike license, so anything you redistribute that
incorporates that text carries the same obligation. Keep the attribution lines intact, and
add them to any document you contribute to the dataset.

[Built with Spec4 AI](https://spec4.ai)
