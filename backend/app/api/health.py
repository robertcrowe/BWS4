# Built with Spec4 AI - https://spec4.ai
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db_session

logger = structlog.get_logger()

router = APIRouter()


@router.get("/health")
async def health(
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Report liveness and database connectivity.

    Google-style docstring per project convention.

    Args:
        session: An async DB session injected per-request.

    Returns:
        A 200 JSON response when the DB is reachable, or 503 otherwise.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report any DB failure as 503
        logger.error("health_check_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": "disconnected", "detail": str(exc)},
        )

    logger.info("health_check_succeeded")
    return JSONResponse(status_code=200, content={"status": "ok", "db": "connected"})
