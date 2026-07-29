# Built with Spec4 AI - https://spec4.ai
"""Pydantic request/response models for the embeddings_example_app endpoints.

The presets models are live as of Phase 2. The placement models below are the
shape Phase 3 will populate, written here with the field names its capability
specification fixes so that phase fills in behaviour rather than
renegotiating the contract.

Phase 1's `EmbeddingsHealthResponse` is gone: the temporary reachability probe
it served was replaced by GET /api/embeddings/presets, which proves the same
thing while returning real data.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class PresetPointOut(BaseModel):
    """One preconfigured TextExample at its projected 2D coordinate.

    `x`/`y` come from the PCA fitted once over the whole preset set, so they
    are only meaningful relative to each other -- the axes carry no unit and
    no independent meaning.
    """

    label: str
    category: str
    x: float
    y: float


class PresetsResponse(BaseModel):
    """Response body for GET /api/embeddings/presets."""

    presets: list[PresetPointOut] = []


class PlacementRequest(BaseModel):
    """Request body for POST /api/embeddings/place.

    The capability's Inputs list two items, `custom_text` and
    `preset_projection_model`. Only the first is a *request* field: the
    projection model is the server-side reference frame, fit once at startup
    and read from the cache ("preset examples are embedded and projected once
    at build/deploy time, not per-request"). The phase's own verification
    confirms the wire shape -- it posts `{"custom_text": "kitten"}` alone.

    Validation is delegated to `placement.normalize_custom_text` rather than
    reimplemented as Field constraints, so the HTTP boundary and any direct
    caller enforce one identical rule. Raising inside the validator is what
    turns a whitespace-only body into FastAPI's 422 automatically.
    """

    custom_text: str

    @field_validator("custom_text")
    @classmethod
    def _reject_blank_or_overlong(cls, value: str) -> str:
        """Apply the placement module's validation at the HTTP boundary.

        Args:
            value: The submitted text.

        Returns:
            The stripped text.

        Raises:
            ValueError: If the text is blank or too long. FastAPI renders
                this as a 422 with the message attached.
        """
        from backend.app.embeddings.placement import (
            InvalidCustomTextError,
            normalize_custom_text,
        )

        try:
            return normalize_custom_text(value)
        except InvalidCustomTextError as exc:
            raise ValueError(str(exc)) from exc


class PlotPoint(BaseModel):
    """An (x, y) coordinate in the shared 2D projection."""

    x: float
    y: float


class NearestNeighborOut(BaseModel):
    """One preset near the submitted custom text.

    Phase 3 computes `distance` in the original embedding space rather than
    the 2D projection, since PCA compresses distances.
    """

    text: str
    distance: float


class PlacementResponse(BaseModel):
    """Response body for POST /api/embeddings/place (Phase 3).

    Field names are fixed by the custom_text_semantic_placement capability's
    Outputs schema note -- Phase 3 must not add, drop, or rename them.
    """

    point: PlotPoint
    text: str
    nearest_neighbors: list[NearestNeighborOut] = []
    embedding_model_version: str
