# Built with Spec4 AI - https://spec4.ai
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.console import router as console_router
from backend.app.api.health import router as health_router
from backend.app.api.rag import router as rag_router
from backend.app.api.tools import router as tools_router
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.core.observability import configure_sentry

configure_logging()

settings = get_settings()

# No-ops cleanly when SENTRY_DSN is unset.
configure_sentry(settings)

app = FastAPI(title="BWS4 API")

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
app.include_router(console_router)
