# Built with Spec4 AI - https://spec4.ai
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.chained_calls import router as chained_calls_router
from backend.app.api.embeddings import router as embeddings_router
from backend.app.api.health import router as health_router
from backend.app.api.rag import router as rag_router
from backend.app.api.single_call import router as single_call_router
from backend.app.api.tools import router as tools_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.core.observability import configure_sentry
from backend.app.embeddings.service import ensure_built

configure_logging()

logger = structlog.get_logger()

settings = get_settings()

# No-ops cleanly when SENTRY_DSN is unset.
configure_sentry(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Warm the embeddings projection cache before the first request.

    Render's free tier spins the service down after ~15 minutes idle, so a
    demo click is often the first request against a cold process. Loading
    the sentence-transformers model, embedding 24 presets, and fitting the
    PCA lazily would put all of that on that visitor's request; doing it here
    moves the cost to boot, where nobody is waiting on it.

    Deliberately non-fatal. The projection serves one example app, while this
    process also serves /health, the RAG app, and the tool-use app -- a
    failure to warm up must not take those down with it. `get_preset_points()`
    rebuilds on demand, so the cost simply lands on the first request instead.
    """
    try:
        ensure_built()
    except Exception:  # noqa: BLE001 - warm-up is best-effort by design
        logger.exception("embeddings_projection_warmup_failed")
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
