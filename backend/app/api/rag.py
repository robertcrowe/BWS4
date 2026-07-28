# Built with Spec4 AI - https://spec4.ai
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import RagInteraction
from backend.app.db.session import get_db_session
from backend.app.rag.dataset_loader import load_dataset_documents
from backend.app.rag.schemas import (
    DatasetDocumentOut,
    RagAskRequest,
    RagAskResponse,
    RetrievedPassageOut,
)
from backend.app.rag.service import RagServiceError, answer_question

logger = structlog.get_logger()

router = APIRouter()


@router.get("/api/rag/dataset")
async def get_dataset() -> JSONResponse:
    """List the reference dataset's documents for the rag_dataset_browser surface.

    Google-style docstring per project convention.

    Returns:
        A 200 JSON response with every document's title and full text.
    """
    documents = [
        DatasetDocumentOut(title=doc.title, text=doc.text) for doc in load_dataset_documents()
    ]
    return JSONResponse(
        status_code=200,
        content={"documents": [doc.model_dump() for doc in documents]},
    )


@router.post("/api/rag/ask")
async def ask(
    payload: RagAskRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Answer a visitor's question via retrieval-augmented generation.

    Orchestrates retrieval, threshold-gated generation, and persistence of
    the interaction, returning the rag_example_app capability's structured
    answer + retrieved-passages response shape.

    Google-style docstring per project convention.

    Args:
        payload: The visitor's question.
        session: An async DB session injected per-request.

    Returns:
        A 200 JSON response with the answer and retrieved passages, or 503
        if the shared generation capability is unavailable.
    """
    try:
        result = await answer_question(session, payload.user_question)
    except RagServiceError as exc:
        logger.error("rag_ask_failed", error=str(exc))
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "detail": (
                    "This demonstration is temporarily unavailable — the "
                    "shared text-generation capability could not be reached. "
                    "Please try again later."
                ),
            },
        )

    session.add(
        RagInteraction(
            user_question=payload.user_question,
            answer=result.answer,
            retrieved_passages=[
                RetrievedPassageOut(**vars(p)).model_dump() for p in result.retrieved_passages
            ],
            status=result.status,
        )
    )
    await session.commit()

    logger.info(
        "rag_ask_succeeded",
        status=result.status,
        passage_count=len(result.retrieved_passages),
        cited_passages=result.cited_passages,
        unresolved_citations=result.unresolved_citations,
    )

    response = RagAskResponse(
        answer=result.answer,
        retrieved_passages=[
            RetrievedPassageOut(**vars(p)) for p in result.retrieved_passages
        ],
        status=result.status,
        cited_passages=result.cited_passages,
        unresolved_citations=result.unresolved_citations,
    )
    return JSONResponse(status_code=200, content=response.model_dump())
