# Built with Spec4 AI - https://spec4.ai
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session scoped to a single request.

    Google-style docstring per project convention.

    Yields:
        An active AsyncSession bound to the shared engine.
    """
    async with async_session_factory() as session:
        yield session
