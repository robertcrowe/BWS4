# Built with Spec4 AI - https://spec4.ai
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.chained_calls import router as chained_calls_router
from backend.app.api.collab import router as collab_router
from backend.app.api.embeddings import router as embeddings_router
from backend.app.api.health import router as health_router
from backend.app.api.orchestrated import router as orchestrated_router
from backend.app.api.planning import router as planning_router
from backend.app.api.rag import router as rag_router
from backend.app.api.react import router as react_router
from backend.app.api.router import router as router_router
from backend.app.api.single_call import router as single_call_router
from backend.app.api.tools import router as tools_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.core.observability import configure_sentry
from backend.app.embeddings.service import ensure_built
from backend.app.router.state import warm_route_descriptions

configure_logging()

logger = structlog.get_logger()

settings = get_settings()

# No-ops cleanly when SENTRY_DSN is unset.
configure_sentry(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Warm per-process state once at boot, before the first request.

    The API runs as one always-on Uvicorn process on the netcup VPS (500 G12),
    supervised by systemd behind Caddy. It is never spun down for idleness, so
    this function runs once per process start -- a release restart or a host
    reboot -- and what it builds stays warm for the process lifetime. Loading
    the sentence-transformers model, embedding the 24 presets and fitting the
    2D PCA projection here, rather than lazily, means no visitor's first
    request pays that ~30 s cost; it is paid at boot, where nobody is waiting
    on it. The release script's readiness gate waits for this to finish.

    The embeddings warm-up is best-effort: a failure is logged and the API
    still starts. The projection serves one example app, while this process
    also serves /health and every other app -- a failure to warm up must not
    take those down with it. `get_preset_points()` rebuilds on demand, so the
    cost simply lands on the first request instead.

    The Router's route-description warm-up is best-effort in the same way: a
    failure is logged and the API still starts. The Router then reports
    itself temporarily unavailable, with a retry endpoint, while every other
    app keeps working.

    Missing credentials are different, and fatal. Settings are loaded at
    import (`get_settings()` above), not here, so a missing GROQ_API_KEY or
    OPENAI_API_KEY (or any other required variable) stops the process before
    this function runs; nothing in it can swallow that failure.

    Args:
        _app: The FastAPI application. Unused; the warmed state lives in
            module-level caches, not on the app object.

    Yields:
        None, once warm-up has been attempted; the API serves requests until
        shutdown resumes the generator.
    """
    try:
        ensure_built()
    except Exception:  # noqa: BLE001 - warm-up is best-effort by design
        logger.exception("embeddings_projection_warmup_failed")
    # Until v10 this await sat outside any try/except, unlike the embeddings
    # warm-up above. It only worked because the function swallowed its own
    # errors. It now raises on failure (so `POST /api/router/retry` can report
    # one), and the best-effort handling lives here, around this call only.
    try:
        await warm_route_descriptions()
    except Exception:  # noqa: BLE001 - warm-up is best-effort by design
        logger.exception("router_warmup_failed")
    yield


app = FastAPI(title="BWS4 API", lifespan=lifespan)

# Exposure policy (stack deployment digest): the api accepts cross-origin
# requests from exactly one origin — the deployed web_client's — never "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(rag_router)
app.include_router(tools_router)
app.include_router(embeddings_router)
app.include_router(single_call_router)
app.include_router(chained_calls_router)
app.include_router(planning_router)
app.include_router(orchestrated_router)
app.include_router(collab_router)
app.include_router(react_router)
app.include_router(router_router)
