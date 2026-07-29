# Built with Spec4 AI - https://spec4.ai
"""Domain logic for the embeddings_example_app: the preset projection and the
in-process embedding_projection_cache it is served from.

Two decisions here are load-bearing:

* **The presets are embedded through the shared embedding service**
  (`services.embedding.embed_text`), the same entry point the RAG pipeline
  uses at index and query time. A second SentenceTransformer instantiated
  here would place this app's points in a different representation space
  from the RAG app's, which is the feature's "app ends up using a different
  embedding representation" failure mode, and it would load a second copy of
  the model into a free-tier dyno's memory.

  It calls `services.embedding` directly rather than the shared
  `services.shared.represent_text` wrapper only because this pass is
  startup-time work over a fixed corpus with no visitor input, so there is
  nothing to attribute in the cross-app request log. Either entry point
  would be correct on quota grounds: representation is unmetered, since the
  model is local and consumes nobody's free tier. See
  `services.shared.UNMETERED_CAPABILITIES`.

* **The PCA is fit exactly once and thereafter only `.transform()`-ed.** The
  fitted model is the fixed reference frame Phase 3 projects custom text
  into; re-fitting with a visitor's point included would move every preset
  and produce the feature's "layout shifts drastically" failure mode.

The cache is ephemeral derived state, never written to Postgres: it is
rebuilt from the bundled asset on demand, so a restarted process (or a test
importing this module fresh) reconstructs it identically without any
migration or seed step.
"""

from __future__ import annotations

import time

import numpy as np
import structlog
from sklearn.decomposition import PCA

from backend.app.core.config import get_settings
from backend.app.embeddings.presets import PRESET_TEXT_EXAMPLES, TextExample
from backend.app.embeddings.schemas import PresetPointOut
from backend.app.services.embedding import embed_text

logger = structlog.get_logger()

#: The projection's target dimensionality. Two, because the output is a plot.
PROJECTION_COMPONENTS = 2

#: Fixed so a given preset set always yields the same coordinates. PCA's
#: solver is deterministic for a full fit, but the seed also pins the
#: randomized solver scikit-learn may select as the preset set grows.
RANDOM_STATE = 0


class _ProjectionCache:
    """The in-process embedding_projection_cache.

    Holds the presets' raw embeddings, the PCA fitted over them, and the
    projected points. Attributes are populated together by `build()` and are
    all `None` until then, so a partially-built cache is not representable.
    """

    def __init__(self) -> None:
        self.examples: list[TextExample] | None = None
        self.embeddings: np.ndarray | None = None
        self.pca: PCA | None = None
        self.points: list[PresetPointOut] | None = None
        self.model_name: str | None = None
        self.fit_count: int = 0

    @property
    def is_built(self) -> bool:
        """Whether the cache holds a usable fitted projection."""
        return self.pca is not None

    def build(self) -> None:
        """Embed every preset, fit the PCA once, and store all three products.

        Idempotent by contract at the call sites (`ensure_built`), but not
        self-guarding: calling this directly always re-fits, which is what
        the fit-once test asserts never happens through the public API.
        """
        started = time.perf_counter()
        examples = list(PRESET_TEXT_EXAMPLES)

        # The shared embedding service, one text at a time -- the same call
        # the RAG pipeline makes, so both apps share a representation space.
        embeddings = np.array([embed_text(example.label) for example in examples])

        pca = PCA(n_components=PROJECTION_COMPONENTS, random_state=RANDOM_STATE)
        coordinates = pca.fit_transform(embeddings)

        self.examples = examples
        self.embeddings = embeddings
        self.pca = pca
        self.model_name = get_settings().embedding_model_name
        self.fit_count += 1
        self.points = [
            PresetPointOut(
                label=example.label,
                category=example.category,
                x=float(x),
                y=float(y),
            )
            for example, (x, y) in zip(examples, coordinates, strict=True)
        ]

        logger.info(
            "embeddings_projection_built",
            presets=len(examples),
            dimensions=int(embeddings.shape[1]),
            # How much of the original space survives the squeeze to 2D. Low
            # by nature; logged because it is the honest measure of how much
            # the plot can be trusted to reflect the real distances.
            explained_variance=round(float(pca.explained_variance_ratio_.sum()), 4),
            model=self.model_name,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )


_cache = _ProjectionCache()


def ensure_built() -> None:
    """Build the projection cache if this process has not built it yet.

    The single guard behind every reader, so the PCA is fit exactly once per
    process lifetime no matter which entry point runs first -- the startup
    event, a request that beat it, or a test.

    Rebuilding after a restart needs no coordination: the bundled presets are
    the only input, so a fresh process reconstructs identical coordinates.
    """
    if not _cache.is_built:
        _cache.build()


def get_preset_points() -> list[PresetPointOut]:
    """Return every preconfigured TextExample at its projected 2D coordinate.

    Google-style docstring per project convention.

    Returns:
        One PresetPointOut per curated example. Identical across calls within
        a process, since they are read from the cache rather than recomputed.
    """
    ensure_built()
    assert _cache.points is not None  # noqa: S101 - guaranteed by ensure_built
    return list(_cache.points)


def get_preset_embeddings() -> np.ndarray:
    """Return the presets' raw, unprojected embeddings.

    Phase 3 measures nearest neighbours against these rather than against the
    2D coordinates, since PCA compresses distances and would report
    misleading neighbours.

    Returns:
        An array of shape (n_presets, embedding_dimensions).
    """
    ensure_built()
    assert _cache.embeddings is not None  # noqa: S101 - guaranteed by ensure_built
    return _cache.embeddings


def get_projection() -> PCA:
    """Return the fitted PCA that defines the shared 2D reference frame.

    Callers must only ever `.transform()` with this. A `.fit()` or
    `.fit_transform()` would move every preset already on the plot.

    Returns:
        The PCA fitted once over the preset embeddings.
    """
    ensure_built()
    assert _cache.pca is not None  # noqa: S101 - guaranteed by ensure_built
    return _cache.pca


def get_preset_examples() -> list[TextExample]:
    """Return the curated examples in the same order as their embeddings.

    Returns:
        The TextExample list backing the cache, index-aligned with
        `get_preset_embeddings()` so a neighbour index maps back to its text.
    """
    ensure_built()
    assert _cache.examples is not None  # noqa: S101 - guaranteed by ensure_built
    return list(_cache.examples)


def get_embedding_model_name() -> str:
    """Return the embedding model backing the cached projection.

    Returns:
        The configured shared model name, e.g. "all-MiniLM-L6-v2". Read from
        the cache rather than Settings so it reports the model the cached
        vectors were actually produced by.
    """
    ensure_built()
    assert _cache.model_name is not None  # noqa: S101 - guaranteed by ensure_built
    return _cache.model_name


def fit_count() -> int:
    """Return how many times the PCA has been fit in this process.

    Test hook backing the fit-once guarantee.

    Returns:
        The number of completed `build()` calls.
    """
    return _cache.fit_count


def reset_cache() -> None:
    """Discard the cached projection. Test hook.

    Process-local state must not leak between tests, and a test that wants to
    observe a rebuild needs a way back to the unbuilt state.
    """
    global _cache
    _cache = _ProjectionCache()
