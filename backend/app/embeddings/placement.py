# Built with Spec4 AI - https://spec4.ai
"""The custom_text_semantic_placement capability: put a visitor's text on the
presets' fixed 2D plot.

Three rules here are the capability specification, not preference:

* **transform-only, never fit.** The PCA cached in Phase 2 is the shared
  reference frame. `.fit()`/`.fit_transform()` here would recompute the basis
  from a set that includes the visitor's point, moving every preset already
  on screen -- the "plot layout shifts drastically each time custom text is
  added" failure mode. Only `.transform()` is called, and a regression test
  asserts preset coordinates are byte-identical after repeated placements.

* **Neighbours are measured in the original 384-dimension space**, before
  projection. The 2D coordinates exist to be looked at; they retain under a
  fifth of the variance, so two points can appear adjacent on the plot while
  being unrelated in the representation. Ranking on the projected distance
  would produce confident, wrong neighbours.

* **Nothing is persisted and the text is never logged.** No datastore write,
  no `service_log_entries` row, and structlog lines carry a length and a
  short content hash instead of the text itself -- enough to correlate a
  report with a request, useless for reading what somebody typed.

The embedding function is injected rather than imported at the call site, the
same pattern `tools/agent.py` uses for `execute_search`: it keeps this module
free of provider concerns and lets tests drive it without loading the model.
Its default is the shared `services.embedding.embed_text`, so the presets and
the visitor's text always land in the same representation space.

Note there is deliberately no usage-cap reservation. The embedding model runs
in-process, so placement spends local CPU and no third-party quota -- see
`services.shared.UNMETERED_CAPABILITIES`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import numpy as np
import structlog

from backend.app.embeddings.schemas import (
    NearestNeighborOut,
    PlacementResponse,
    PlotPoint,
)
from backend.app.embeddings.service import (
    get_embedding_model_name,
    get_preset_embeddings,
    get_preset_examples,
    get_projection,
)
from backend.app.services.embedding import embed_text

logger = structlog.get_logger()

#: Upper bound on submitted text. The model truncates at 256 word pieces, so
#: anything beyond roughly this length is silently ignored by the encoder
#: anyway -- rejecting it is honest, where accepting it would place a point
#: that does not represent what the visitor actually wrote.
MAX_CUSTOM_TEXT_CHARS = 500

#: How many presets to return as neighbours. Three is enough to show which
#: cluster the point fell into and whether it was a close call.
NEIGHBOR_COUNT = 3


class PlacementError(Exception):
    """Base class for placement failures, carrying a machine-readable code.

    The API layer maps `code` straight into the response body so the frontend
    can branch on it (retry vs. fix your input) without parsing prose.
    """

    code = "placement_failed"


class InvalidCustomTextError(PlacementError):
    """The submitted text is empty, whitespace-only, or too long."""

    code = "invalid_custom_text"


class EmbeddingUnavailableError(PlacementError):
    """The embedding model could not represent the text.

    The capability specification's escalation path: a non-blocking error the
    UI can offer to retry, since the output is a visualization rather than a
    decision with consequences.
    """

    code = "embedding_unavailable"


def normalize_custom_text(raw: str) -> str:
    """Validate and normalize submitted text before anything expensive runs.

    Google-style docstring per project convention.

    Args:
        raw: The text exactly as submitted.

    Returns:
        The text with surrounding whitespace stripped.

    Raises:
        InvalidCustomTextError: If the text is empty or whitespace-only, or
            longer than MAX_CUSTOM_TEXT_CHARS.
    """
    text = raw.strip()
    if not text:
        raise InvalidCustomTextError("Enter some text to place on the plot.")
    if len(text) > MAX_CUSTOM_TEXT_CHARS:
        raise InvalidCustomTextError(
            f"Text is too long: {len(text)} characters, "
            f"maximum is {MAX_CUSTOM_TEXT_CHARS}."
        )
    return text


def _redacted(text: str) -> str:
    """Return a short content hash standing in for the text in logs.

    Args:
        text: The visitor's text. Never returned, only digested.

    Returns:
        A 12-character SHA-256 prefix -- stable enough to correlate repeat
        submissions across log lines, useless for recovering the input.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _nearest_neighbors(vector: np.ndarray) -> list[NearestNeighborOut]:
    """Rank the presets closest to a vector in the original embedding space.

    Args:
        vector: The custom text's embedding, unprojected.

    Returns:
        The NEIGHBOR_COUNT nearest presets, closest first, by cosine
        distance. Cosine matches the metric the RAG retriever ranks with, so
        "near" means the same thing across both example apps. The vectors are
        L2-normalized, so this reduces to 1 - dot product.
    """
    presets = get_preset_embeddings()
    examples = get_preset_examples()

    distances = 1.0 - presets @ vector
    order = np.argsort(distances)[:NEIGHBOR_COUNT]

    return [
        NearestNeighborOut(text=examples[i].label, distance=float(distances[i])) for i in order
    ]


def place_custom_text(
    custom_text: str,
    *,
    embed: Callable[[str], list[float]] = embed_text,
) -> PlacementResponse:
    """Place a visitor's text on the presets' existing 2D plot.

    Google-style docstring per project convention.

    Args:
        custom_text: The visitor's word, phrase, or sentence. Held in memory
            for this call only -- never stored, never logged verbatim.
        embed: The embedding function, injected for testing. Defaults to the
            shared service the presets were embedded with; overriding it with
            a different model would place the point in a space the presets do
            not live in.

    Returns:
        The text's coordinate in the presets' fixed projection, plus its
        nearest presets measured in the unprojected space.

    Raises:
        InvalidCustomTextError: If the text fails validation.
        EmbeddingUnavailableError: If the embedding model errors out.
    """
    text = normalize_custom_text(custom_text)

    try:
        vector = np.array(embed(text))
    except Exception as exc:  # noqa: BLE001 - any model failure is one failure mode
        logger.error("embeddings_placement_failed", text_sha=_redacted(text), error=str(exc))
        raise EmbeddingUnavailableError(
            "The embedding model is temporarily unavailable. Please try again."
        ) from exc

    # transform(), never fit_transform() -- the presets must not move.
    projected = get_projection().transform(vector.reshape(1, -1))[0]
    neighbors = _nearest_neighbors(vector)

    logger.info(
        "embeddings_placement_completed",
        # The text itself is deliberately absent; a hash and a length are
        # enough to debug with and cannot be read back.
        text_sha=_redacted(text),
        text_chars=len(text),
        nearest=[n.text for n in neighbors],
        x=round(float(projected[0]), 4),
        y=round(float(projected[1]), 4),
    )

    return PlacementResponse(
        point=PlotPoint(x=float(projected[0]), y=float(projected[1])),
        text=text,
        nearest_neighbors=neighbors,
        embedding_model_version=get_embedding_model_name(),
    )
