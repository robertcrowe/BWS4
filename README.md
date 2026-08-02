# Built with Spec4 (BWS4)

## Overview
<a href='https://spec4.ai' style='float:right'><img src='BWS4-white-100.png'></a>
Built with Spec4 (BWS4) is a living showcase of common AI application patterns, presented as a collection of small, self-contained example apps behind a single landing page. Each example demonstrates one pattern end-to-end: how it's built, what it depends on, and how it behaves, so that visitors unfamiliar with the underlying technique can understand it by seeing it work rather than by reading about it abstractly.

Eight examples ship today. The first four are listed in order of how much machinery each pattern needs — **embeddings** (turn text into a position and compare positions), **single-call** (one prompt in, one response out), **RAG** (retrieve first, then answer from what you retrieved), and **tool use** (let the model decide what to call). Four more are appended after them, each adding a way of composing calls rather than a new kind of call: **chained calls** (one call's output becomes the next call's input), **planning agent** (one call decomposes a goal into a plan you approve before any step runs, then executes the steps and composes an itinerary), **orchestrated subagents** (a coordinator picks two of four fixed specialists, briefs each differently, runs them at the same time, and merges their independent answers), and **multi-agent collaboration** (a buyer agent negotiates with two rival sellers that hold private constraints neither can see, across a staged trust boundary). Seeing them side by side is the point: each one exists partly to show what the cheaper tier below it cannot do.

The gallery is designed to grow. New example apps can be added over time without disrupting the availability of existing ones, thanks to per-example code-splitting on the frontend and a shared set of backend framework services (generation, embedding, web search, storage) that every example app draws on. Adding an app to the landing page, the header menu, and the router is a single entry in one file. Every example runs entirely within free, no-cost usage limits, making the whole project easy to fork, run locally, and deploy without a billing surprise.

## Key Features

- **Landing page & example app directory** — a consistent entry point listing every example app in the gallery, with a uniform look, feel, and navigation pattern across all of them.
- **Embeddings example app** — 24 curated texts across four categories, embedded by the shared model and projected into 2D so semantically similar texts land near each other. Visitors can drop in their own text and watch it place; the existing points never move, because the projection is fitted once and only ever applied afterwards.
- **Single-call example app** — the baseline pattern, in both modes. **Simple** returns plain prose; **Structured** attaches a JSON Schema to the same single request and validates the response against it server-side, showing the submitted request and the returned response side by side. When a response doesn't conform, that's reported with the raw output rather than dressed up as a success — which happens for real, because 2 of the 8 free models in the chain don't honour a schema directive.
- **RAG example app** — a full retrieval-augmented generation pipeline: a curated reference dataset is chunked, embedded, and indexed; user questions are answered by retrieving the most relevant passages and grounding a generated response in them. Every answer's citations are audited against the passages actually retrieved, so "grounded" is a checked claim rather than a hopeful label.
- **Tool-use example app** — a real function-calling loop (searching the live web via Exa): the model is handed a tool *schema* and decides for itself whether to call it, what query to write, and when it has enough to answer. The trace shown is what it actually did.
- **Chained-calls example app** — exactly two sequential model calls, where the second one's input is literally the first one's output: a "struggling writer" persona drafts a short story, then an independent "harsh critic" persona critiques that exact draft. Both blocks stay on screen, and the phrase the critic quoted is checked against the story it came from — so "the critic actually read it" is a measured claim, not a hopeful one. If the critic call fails, the story survives and only the second call is retried.
- **Planning-agent example app** — a planner call decomposes a trip-day goal into a visible plan of research and synthesis steps, and *nothing executes until you approve it*. The two-phase invocation is an API boundary rather than a flag, so the human-in-the-loop checkpoint cannot be defaulted away. A step that cannot be afforded is reported honestly and skipped, and the itinerary composes anyway with the gap stated.
- **Orchestrated-subagents example app** — a coordinator picks exactly two of four fixed specialists, writes each a distinct brief naming the angle it must leave to the other, and shows you that decision before anything runs. On your go-ahead both specialists run *at the same time* — one column can finish while the other is still working — and their answers are merged into one response with both sources kept on screen.
- **Multi-agent collaboration example app** — peer-to-peer rather than orchestrated: a buyer agent negotiates one procurement round against two rival seller agents holding private, mutually invisible constraints. Opacity is enforced **structurally** — each agent's turn is assembled only from the messages addressed to it, so a seller cannot learn the rival's price even when prompted to try, and the message log lets you verify there is no seller-to-seller traffic at all. Each run costs a fixed **8 model calls — 6 negotiation plus 2 post-award explanation calls** — and is bounded by the framework-standard shared hourly and daily allowance rather than a per-app session limit. The exchanges use the A2A protocol's data model and interaction pattern without its network transport, and the screen says so candidly: all three agents ship under one owner, so the trust boundary is staged for teaching.
- **Shared framework services** — common generation, representation, and storage capabilities reused across example apps, so each new pattern only needs to add what's unique to it. Every model call in the gallery, whichever app makes it, goes through one registry with one fallback chain, one set of provider credentials, and one shared bench of withdrawn models.
- **Free-tier guardrails** — per-UTC-hour usage caps on every metered capability, enforced *before* a provider is called, so an unauthenticated demo can't drain a shared quota. The one capability that spends no third-party quota (in-process embedding) is deliberately uncapped and still logged.
- **Route-based code-splitting** — each example app is lazy-loaded independently, keeping the initial page load light as the gallery grows.
- **Light/dark theming** — a visitor's theme preference is remembered locally across visits.
- **Built-in observability** — optional, zero-config error tracking and model-call observability that no-ops cleanly when not configured, so the project runs the same whether or not monitoring is wired up.

## Technology Stack

**Frontend (`web_client`)**
- TypeScript
- React Router (client-side routing, per-example lazy-loaded chunks)
- TanStack Query (server state, loading/error states, and no automatic retries on calls that spend quota)
- Tailwind CSS (consistent styling across all example apps, with a class-based light/dark strategy)
- Plotly (`plotly-basic` build only — the scatter plot for the embeddings example, ~1 MB rather than the full ~4.7 MB bundle, and confined to that route's lazy chunk)
- Vite (build tool, producing a hashed static bundle)

**Backend (`api`)**
- Python 3.12
- FastAPI (REST API, with an auto-generated OpenAPI schema)
- SQLAlchemy (data access, including pgvector cosine-distance queries)
- sentence-transformers (`all-MiniLM-L6-v2`) for embeddings, run in-process
- LiteLLM, routing to OpenRouter and Groq — every example app calls models through one shared registry (`backend/app/services/model_registry.py`), which walks an ordered chain of free-tier models on failure and benches any slug a provider has withdrawn. The chains are per capability (tool calling vs. text generation) because the two are verified separately; both rot as providers retire free slugs, so expect to refresh them
- PydanticAI, routing to Groq and OpenRouter — the second model lane (`backend/app/services/agent_runtime.py`), used where an app wants the framework to bind and validate typed output rather than parsing JSON out of prose. It reads its slugs from that *same* registry and passes through the same usage-limit gate, so the two lanes cannot disagree about which models exist or spend budget the other doesn't see. Providers are pluggable: most expose an OpenAI-shaped endpoint, so adding one is a base URL and a credential entry rather than a new SDK
- scikit-learn (PCA), used only to project embeddings to 2D for the embeddings example's plot — fitted once at startup over the curated preset set and never re-fitted
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

**Tests, lint, and typecheck:**

```shell
uv run pytest backend/tests          # no database or provider required
uv run ruff check backend            # Python lint
uv run ruff format --check backend   # Python formatting
uv run mypy backend/app              # Python typecheck (strict on v5 code)
npm run test --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend      # `tsc -b` runs here, so this is also the typecheck
```

Ruff and mypy arrived with the orchestrated-subagents revision, against a backend
that had never had either. Both are **scoped on purpose**: the gate covers code
written from that revision onward, and the paths that predate it are listed one
per line in `pyproject.toml`. Running Ruff across the whole backend reports 366
findings and would reformat 57 files, which would bury a feature diff in
whitespace. Removing a path from those lists is a deliberate cleanup, not
something to do by accident.

The backend suite needs neither a live Postgres nor a live model provider: `conftest.py` supplies
fake-but-valid config so `Settings` validates, DB-touching routes are exercised through an
in-memory fake session, and provider calls are stubbed at their point of use.

### Using the app

- Open the landing page to see every available example app.
- Select **Embeddings** to see the same 24 curated texts arranged by meaning alone, then add your own word or phrase. Notice that whole sentences land beside single words (`joy` sits near `grief` — opposite sentiments, both about feeling), that the axes are deliberately unlabelled because only ~19% of the original detail survives the squeeze to 2D, and that nothing already on the plot moves when your text is added.
- Select **Single-Call** for the baseline: one prompt, one response, nothing in between. Start with a preset chip (each labelled by intent — summarize, classify, extract) and note that the full prompt appears in the box, so you can see exactly what will be sent before spending a call. Then flip the toggle to **Structured** and run the same preset again: the request now carries a JSON Schema, and you get the submitted request and the schema-checked response side by side. If the model returns something that doesn't match, the screen says so and shows you the raw output — worth seeing, because it's the honest half of the pattern.
- Select **RAG** to ask questions against the curated reference dataset — the app retrieves relevant passages and generates an answer from them, showing every passage it retrieved and marking which ones the answer actually cited. Two different failure modes are worth trying: `What's the best pizza topping?` is rejected by the retriever before any model runs, while `Who was the first woman in space?` scores *above* the similarity threshold on the dataset's Gagarin passages and is caught only by the citation audit — a reminder that a good similarity score is not evidence the dataset contains the answer.
- Select **Tool-Use** to watch a real function-calling loop. The model is given a `web_search` tool schema and decides for itself whether to call it, writes its own search query, reads the results, and may search again before answering. The trace shown under each run is what the model actually did — including choosing *not* to search, which you can see by asking it something like `What is 17 times 24?`.
- Select **Chained-Calls** and give it a story idea. Both calls are described before you submit, so you know what each one is for. The draft comes back labelled *Step 1 · Struggling Writer* and the critique *Step 2 · Harsh Critic*, with the exact phrase the critic pulled out of the story quoted above its verdict — that phrase is checked server-side against the story text, so you can tell a critique that read the draft from one that didn't. The progress indicator deliberately does *not* animate a hand-off between the two calls: they run in one round trip, so the browser learns they both finished at the same moment.
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
| `OPENROUTER_API_KEY` | ✅ | Text generation via OpenRouter, reached by both model lanes — LiteLLM for the RAG, tool-use, and single-call apps, PydanticAI for the chained-calls app. Serves as the deep fallback in both model chains. |
| `GROQ_API_KEY` | — | Optional second LLM provider, used by **both** model chains (tool calling and text generation) and by **both** lanes (LiteLLM and PydanticAI). Groq's free tier is metered **per model** (1,000+ requests/day each) rather than as one account-wide pool, so it leads both chains when set. Unset → `groq/` entries are dropped everywhere and OpenRouter serves alone. |
| `EXA_API_KEY` | ✅ | Live web search, called by the tool-use agent when *it* decides to search. |
| `OPENAI_API_KEY` | — | The OpenAI moderation endpoint, used as the safety gate on **all free-text input across every example app**. Free of charge and separate from the free-model pool, so it costs a run nothing. **Unset → the gate fails closed and every free-text submission is refused** with `moderation_unavailable`. Each app's curated examples still work: they are verified server-side by byte-match and skip the gate by design, so an unconfigured deployment stays demonstrable. |
| `MODERATION_HASH_SALT` | — | Salt for the question hashes written to `moderation_log` and to the orchestrated run summary. (The multi-agent collaboration app hashes nothing: its inputs are a scenario enum and a numeric vector, so there is no free text to protect.) Unset → a process-stable salt is generated and a warning is logged, so hashes stop comparing across restarts. Raw question text is never stored either way. |
| `PORT` | — | Defaults to `8000`; supplied automatically by Render. Don't leave it blank in `.env` — an empty value fails `int` parsing at startup. |
| `EMBEDDING_MODEL_NAME` | — | Defaults to `sentence-transformers/all-MiniLM-L6-v2`. |
| `GENERATION_HOURLY_LIMIT` | — | Cap on generation calls **per UTC hour** (free-tier guardrail, default 50). Shared by every app that generates text — they draw on one counter, because they draw on one provider quota. Most reservations are made up front, so a run that can't be finished is never started: a chained-calls submission reserves **2** units, an orchestrated run reserves **12** (four logical calls, each allowed two framework re-prompts), and a multi-agent collaboration run reserves **12** (six negotiation calls, two post-award explanations, and four held back for the repairs the sequencer makes). At the default 50 that is roughly 4 orchestrated or collaboration runs per hour across the whole showcase; raise this if you want more, and lower it first on a tighter provider account. |
| *(no embedding cap)* | — | Embedding is deliberately **uncapped** — the model runs in-process, so it spends local CPU and no third-party quota. It is still logged to `service_log_entries`. |
| `STORAGE_HOURLY_LIMIT` | — | Cap on storage calls per UTC hour (default 75). |
| `SEARCH_HOURLY_LIMIT` | — | Cap on Exa search calls per UTC hour (default 15). One tool-use request may run up to 3 searches and a planning run up to 4, so this is still the tightest of the caps — lower it first on a smaller Exa plan. |
| `PLANNING_HOURLY_LIMIT` | — | Cap on planning-agent runs per UTC hour (default 3). Not a duplicate of the generation cap: planning charges *as it goes* rather than reserving, and a degrading run may spend up to 18 generation units (a typical one costs 6), so this bounds that app's share of a pool every app draws on. |

| `SENTRY_DSN` | — | Optional error tracking. **Unset → Sentry is never initialized** and the app runs normally. |
| `SENTRY_ENVIRONMENT` | — | Environment tag on Sentry events (default `development`). |
| `HF_HOME` | — | Where the sentence-transformers model is cached. Set on Render so the build-time download survives into the running service; unset locally, where it defaults to `~/.cache/huggingface`. |
| `HF_TOKEN` | — | Optional. Raises Hugging Face's anonymous download rate limit. The embedding model is public, so no token is needed to fetch it. |

All four caps are **per UTC hour** and reset at the top of the hour —
`usage_limits.window_start` is a timestamp truncated to the hour, and the counter
rolls over on the first reservation of a new one. No cron job or manual intervention
is involved. An hourly window necessarily raises the theoretical daily ceiling; what
it buys is recovery in minutes instead of most of a day, and the defaults were
re-based when the window changed so the saturated-every-hour worst case still lands
inside the free tiers. There is no in-app surface for these counters; query
`usage_limits` and `service_log_entries` directly when you need to see them.

The four required variables fail fast at startup with a descriptive error if missing.

**Frontend (`web_client`)**

| Variable | Required | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | ✅ | The backend API's base URL (defaults to `http://localhost:8000` in dev). |
| `VITE_SENTRY_DSN` | — | Optional error tracking, reporting to the same Sentry project as the backend. **Unset → Sentry is never initialized.** |

Vite inlines `VITE_*` variables at build time, so the frontend must be **rebuilt** after
changing either of them.

### Free-model troubleshooting

Every model call walks an ordered chain that spans **two providers** — Groq first, OpenRouter
behind it — so an outage or a quota wall at either still leaves working entries. LiteLLM walks
the chain on the real request; nothing is probed in the request path.

There are **two chains**, and which one you're looking at matters. `TOOL_MODEL_CHAIN` serves the
tool-use agent; `GENERATION_MODEL_CHAIN` serves RAG's answers and the single-call app's plain and
structured modes. They're separate because the two capabilities are verified separately (see the
note at the end of this section), but they share everything else: credentials, and one bench of
withdrawn slugs, since a model a provider has retired is retired for every app at once.

Two failure modes worth telling apart:

- **`429 Rate limit exceeded: free-models-per-day`.** OpenRouter's free-model allowance is
  an account-wide cap shared by every example app, reset at midnight UTC — not a code problem
  and not specific to any model. It is **50 requests/day on an unfunded account and 1,000/day
  once $10 of credits has been purchased**, and separately **20 requests/minute** either way,
  so a burst can 429 long before the day's budget is spent. Check which situation you are in
  without spending anything: `curl -H "Authorization: Bearer $OPENROUTER_API_KEY"
  https://openrouter.ai/api/v1/key` reports `is_free_tier`, and `/api/v1/credits` reports the
  balance. Groq's limits are per-model instead, which is why it leads the chain. The agent surfaces an exhausted chain
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
  behind RAG's answers and the single-call app — needs a different check: that the model returns
  schema-valid JSON and emits no citation markers when it declines to answer. A model that
  passes one probe can fail the other (`groq/openai/gpt-oss-20b` is excluded from the tool
  chain and shipped in the generation chain), so don't move slugs between the two chains
  without re-verifying.

- **Structured mode returns "Schema mismatch detected".** Not a bug, and not necessarily worth
  fixing. Support for provider-native constrained decoding is uneven across the free tier: of
  the eight models in the generation chain, five return conforming JSON under a strict
  `json_schema` directive, one rejects the parameter outright (its 400 trips the fallback, so
  the request still succeeds), and one accepts the directive and returns a different shape
  anyway. That's why the response is validated server-side after the model answers, and why a
  mismatch is shown with its raw output instead of being retried — the single-call app exists
  partly to make this behaviour visible. If *every* structured call is mismatching, suspect the
  chain has rotted rather than the schema.

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

- **Playwright** — end-to-end browser testing is planned but not yet part of this project's test suite or CI pipeline. Worth knowing that this is currently the widest gap in coverage: the app is verified by component tests and by calls against the live API, but no browser has been driven against it. Six screens are affected — embeddings, single call, chained calls, planning, orchestrated subagents and multi-agent collaboration.
- **A rate limit.** The hourly caps bound the hour, not the burst, and two costs are exposed to that. In-process embedding spends local CPU rather than third-party quota, so it is deliberately uncapped — but on a free dyno the burst is the real cost. And OpenRouter enforces **20 requests/minute** on free models regardless of the daily allowance, so a burst can 429 with the daily budget barely touched. A rate limit is the right instrument for both; nothing has been built.
- **An authenticated operator view of `usage_limits` / `service_log_entries`.** Both tables are written on every call and there is currently no in-app reader; an earlier public one was removed for spending real quota and echoing visitors' text. Any replacement needs authentication that fails closed and must not echo visitor input.
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
