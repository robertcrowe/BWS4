# Built with Spec4 AI - https://spec4.ai
import os

# Local test defaults so Settings() validates without a real Neon connection.
# The DB itself is stubbed out per-test via a dependency override.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("CORS_ORIGIN", "http://localhost:5173")
os.environ.setdefault("PORT", "8000")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("EXA_API_KEY", "test-exa-key")

# Force-disable Sentry for the whole suite. Importing backend.app.main runs
# configure_sentry() at import time, and Settings reads the repo-root .env
# regardless of cwd -- so without this, a developer with a real SENTRY_DSN in
# .env ships test errors to the live Sentry project (and pays a network flush
# on every run). Assigned, not setdefault: an exported DSN must not win either.
os.environ["SENTRY_DSN"] = ""
