# Built with Spec4 AI - https://spec4.ai
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db_session
from backend.app.tools.schemas import (
    AgentStepOut,
    SearchRequest,
    SearchResponse,
    SearchResultOut,
)
from backend.app.tools.service import ToolServiceError, run_search

logger = structlog.get_logger()

router = APIRouter()


@router.post("/api/tools/search")
async def search_tool(
    payload: SearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Run the tool-use agent loop and return its answer, trace, and results.

    Google-style docstring per project convention.

    Args:
        payload: The visitor's question. The agent decides for itself whether
            and what to search -- this is not passed to the search API as-is.
        session: An async DB session injected per-request.

    Returns:
        A 200 JSON response with the agent's answer, the step trace, and the
        ranked results it saw, or 503 with a clear 'temporarily unavailable'
        message if a usage cap is reached, the Exa Search API call fails, or
        the free-model chain is exhausted.
    """
    try:
        run = await run_search(session, payload.search_query)
    except ToolServiceError as exc:
        logger.error("tool_search_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(exc)},
        )

    logger.info(
        "tool_search_succeeded",
        result_count=len(run.results),
        searches=len(run.queries),
        iterations=run.iterations,
        model=run.model,
    )

    response = SearchResponse(
        answer=run.answer,
        results=[
            SearchResultOut(title=r.title, summary=r.summary, source=r.source, rank=r.rank)
            for r in run.results
        ],
        steps=[
            AgentStepOut(kind=s.kind, label=s.label, detail=s.detail) for s in run.steps
        ],
        queries=run.queries,
        model=run.model,
        iterations=run.iterations,
    )
    return JSONResponse(status_code=200, content=response.model_dump())
