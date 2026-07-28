# Built with Spec4 AI - https://spec4.ai
"""framework_services_console API: usage-limit/log status, and a request
tester that exercises the shared generation, representation, and storage
capabilities directly."""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import ServiceLogEntry, UsageLimit
from backend.app.db.session import get_db_session
from backend.app.services import shared
from backend.app.services.generation import GenerationServiceError
from backend.app.services.shared import utc_today

logger = structlog.get_logger()

router = APIRouter()

#: The requesting app name recorded on every console-initiated shared-service
#: call, per the ServiceLogEntry domain fields.
CONSOLE_APP_NAME = "Framework Console"

_CONSOLE_TEST_RECORD_KEY = "console_manual_test"

RECENT_LOG_ENTRIES_LIMIT = 20


class ConsoleTestRequest(BaseModel):
    """Request body for POST /api/console/test-request."""

    request_type: Literal["generation", "representation", "storage"]
    request_payload: str = Field(min_length=1)


@router.get("/api/console/status")
async def get_status(session: AsyncSession = Depends(get_db_session)) -> JSONResponse:
    """Report current usage limits and the most recent cross-app request log.

    Google-style docstring per project convention.

    Args:
        session: An async DB session injected per-request.

    Returns:
        A 200 JSON response with every capability's usage_limits row and
        the most recent service_log_entries rows, newest first.
    """
    usage_result = await session.execute(select(UsageLimit).order_by(UsageLimit.capability))
    usage_rows = usage_result.scalars().all()

    log_result = await session.execute(
        select(ServiceLogEntry)
        .order_by(ServiceLogEntry.timestamp.desc())
        .limit(RECENT_LOG_ENTRIES_LIMIT)
    )
    log_rows = log_result.scalars().all()

    return JSONResponse(
        status_code=200,
        content={
            "usage_limits": [
                {
                    "capability": row.capability,
                    # A window_start strictly before today means the row hasn't
                    # been touched yet today and will reset on the next
                    # reservation, so report today's real figure (0) rather
                    # than yesterday's leftover. A missing window reports the
                    # stored count, matching reserve_capability's fail-closed
                    # handling of the same case.
                    "used": (
                        0
                        if row.window_start is not None and row.window_start < utc_today()
                        else row.used
                    ),
                    "cap": row.cap,
                    "window_start": row.window_start.isoformat() if row.window_start else None,
                }
                for row in usage_rows
            ],
            "log_entries": [
                {
                    "app_name": row.app_name,
                    "capability": row.capability,
                    "summary": row.summary,
                    "timestamp": row.timestamp.isoformat(),
                }
                for row in log_rows
            ],
        },
    )


@router.post("/api/console/test-request")
async def test_request(
    payload: ConsoleTestRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Exercise generate_text, represent_text, or set_record directly.

    Lets a maintainer manually test the shared interface's three
    capabilities and see the same clear-failure behavior every example app
    sees once a capability's usage cap is exhausted.

    Google-style docstring per project convention.

    Args:
        payload: The capability to invoke and the content to send it.
        session: An async DB session injected per-request.

    Returns:
        A 200 JSON response with the capability's result, or 503 with a
        clear message if that capability's usage cap has been reached.
    """
    try:
        if payload.request_type == "generation":
            text = await shared.generate_text(
                session,
                system_prompt=(
                    "You are a helpful assistant demonstrating BWS4's shared "
                    "text-generation capability."
                ),
                user_prompt=payload.request_payload,
                app_name=CONSOLE_APP_NAME,
            )
            result: dict[str, object] = {"generated_text": text}
        elif payload.request_type == "representation":
            vector = await shared.represent_text(
                session, text=payload.request_payload, app_name=CONSOLE_APP_NAME
            )
            result = {"dimensions": len(vector), "vector_preview": vector[:6]}
        else:
            record = await shared.set_record(
                session,
                key=_CONSOLE_TEST_RECORD_KEY,
                value=payload.request_payload,
                app_name=CONSOLE_APP_NAME,
            )
            result = {"key": record.key, "value": record.value, "written_by": record.written_by}
    except shared.ServiceUnavailableError as exc:
        logger.error("console_test_request_unavailable", capability=exc.capability)
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(exc)},
        )
    except GenerationServiceError as exc:
        logger.error("console_test_request_generation_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": (
                    "The shared text-generation capability could not be reached. "
                    "Please try again later."
                ),
            },
        )

    logger.info("console_test_request_succeeded", request_type=payload.request_type)
    return JSONResponse(status_code=200, content={"status": "ok", "result": result})
