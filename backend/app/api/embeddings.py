# Built with Spec4 AI - https://spec4.ai
"""Thin FastAPI handlers for the embeddings_example_app, mirroring api/rag.py.

Neither route touches the database. The presets come from an in-process cache
and placement is pure computation over it, so there is no session dependency
here -- and, per the custom_text_semantic_placement capability's Privacy &
safety section, nothing a visitor types is written anywhere.
"""

from collections.abc import Callable

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.app.embeddings.placement import (
    EmbeddingUnavailableError,
    InvalidCustomTextError,
    place_custom_text,
)
from backend.app.embeddings.schemas import PlacementRequest, PresetsResponse
from backend.app.embeddings.service import get_preset_points
from backend.app.services.embedding import embed_text

logger = structlog.get_logger()

router = APIRouter()


def get_embedder() -> Callable[[str], list[float]]:
    """Provide the shared embedding function to the placement route.

    The project's dependency-injection convention (see `get_db_session`)
    exists so tests can substitute a dependency through
    `app.dependency_overrides`. Here that means a placement test can exercise
    the route -- validation, status codes, response shape -- without loading
    the sentence-transformers model.

    Returns:
        The shared `services.embedding.embed_text`, the same function that
        embedded the presets.
    """
    return embed_text


@router.get("/api/embeddings/presets")
async def get_presets() -> JSONResponse:
    """Return every preconfigured TextExample at its projected 2D coordinate.

    Reads the in-process projection cache, which the startup event has
    normally already built -- so this handler embeds nothing and fits
    nothing, and stays fast enough for live demonstration. If a request
    arrives before the warm-up finishes, `get_preset_points()` builds the
    cache on demand rather than failing.

    Google-style docstring per project convention.

    Returns:
        A 200 JSON response with one entry per curated example, each
        carrying its label, category, and (x, y) position.
    """
    points = get_preset_points()

    logger.info("embeddings_presets_served", count=len(points))

    response = PresetsResponse(presets=points)
    return JSONResponse(status_code=200, content=response.model_dump())


@router.post("/api/embeddings/place")
async def place(
    payload: PlacementRequest,
    embed: Callable[[str], list[float]] = Depends(get_embedder),
) -> JSONResponse:
    """Place a visitor's custom text on the presets' fixed 2D plot.

    Empty, whitespace-only, and over-long text never reach this handler:
    `PlacementRequest` validates through the same
    `placement.normalize_custom_text` and FastAPI answers 422 first. The
    explicit catch below covers direct/programmatic callers and keeps the
    two paths reporting the same `code`.

    Google-style docstring per project convention.

    Args:
        payload: The visitor's text. Not persisted or logged verbatim.
        embed: The shared embedding function, injected per-request.

    Returns:
        A 200 JSON response with the point, the echoed text, its nearest
        presets, and the embedding model version. On failure, a 422 or 503
        carrying a machine-readable `code` the frontend can branch on --
        `invalid_custom_text` to correct the input, `embedding_unavailable`
        to offer a retry.
    """
    try:
        placement = place_custom_text(payload.custom_text, embed=embed)
    except InvalidCustomTextError as exc:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "code": exc.code, "detail": str(exc)},
        )
    except EmbeddingUnavailableError as exc:
        # Already logged with a redacted hash inside placement.py; logging
        # the message again here would not add anything the operator needs.
        return JSONResponse(
            status_code=503,
            content={"status": "error", "code": exc.code, "detail": str(exc)},
        )

    return JSONResponse(status_code=200, content=placement.model_dump())
