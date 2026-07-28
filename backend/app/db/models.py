# Built with Spec4 AI - https://spec4.ai
"""SQLAlchemy models for RAG dataset embeddings and shared text representations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.services.embedding import EMBEDDING_DIMENSIONS


class DatasetEmbedding(Base):
    """A single reference-dataset passage and its embedding vector.

    Maps to the stack spec's `dataset_embeddings` collection (Dataset
    entity): one row per chunking-pipeline passage, read by the retriever via
    a pgvector cosine-distance query against `embedding`.
    """

    __tablename__ = "dataset_embeddings"
    __table_args__ = (
        Index(
            "ix_dataset_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    passage_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source_title: Mapped[str] = mapped_column(String(255))
    text_excerpt: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class TextRepresentation(Base):
    """A log entry recording one embedding computation (TextRepresentation).

    Maps to the stack spec's `text_representations` collection, shared across
    example apps' use of the embedding_pipeline service.
    """

    __tablename__ = "text_representations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(50))
    source_reference: Mapped[str] = mapped_column(String(255))
    model_name: Mapped[str] = mapped_column(String(255))
    dimensions: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class LanguageGenerationRequest(Base):
    """A logged text-generation call made through the shared generate_text interface.

    Maps to the stack spec's `language_generation_requests` collection
    (LanguageGenerationRequest entity): one row per successful shared-service
    generation call, tagged with the requesting app's name.
    """

    __tablename__ = "language_generation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_name: Mapped[str] = mapped_column(String(100))
    prompt_excerpt: Mapped[str] = mapped_column(Text)
    response_excerpt: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class StoredRecord(Base):
    """A key/value record written and read through the shared storage interface.

    Maps to the stack spec's `stored_records` collection (StoredRecord
    entity): a small amount of data kept available across uses, shared
    consistently across example apps rather than each managing its own.
    """

    __tablename__ = "stored_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    written_by: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UsageLimit(Base):
    """The current usage counter and cap for one shared-service capability.

    Maps to the stack spec's `usage_limits` collection (UsageLimit entity):
    one row per capability (generation, representation, storage), read and
    incremented on every shared-service invocation to gate access once the
    configured free-tier cap is reached.

    The cap is a **daily** budget, not a lifetime one: `window_start` records
    the UTC date the current counter belongs to, and reserve_capability()
    zeroes `used` when it sees a stale date. Without that column the counters
    only ever climbed, so a public deployment went permanently dark once the
    first N visitors had used it up -- while still telling them to "try again
    later".
    """

    __tablename__ = "usage_limits"
    __table_args__ = (Index("ix_usage_limits_capability", "capability", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capability: Mapped[str] = mapped_column(String(50))
    used: Mapped[int] = mapped_column(Integer, default=0)
    cap: Mapped[int] = mapped_column(Integer)
    #: The UTC date `used` is counting for. Compared against today on every
    #: reservation; an older date means the window has rolled over.
    window_start: Mapped[date] = mapped_column(
        Date, default=lambda: datetime.now(timezone.utc).date()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ServiceLogEntry(Base):
    """One cross-app record of a shared-service invocation (ServiceLogEntry).

    Maps to the stack spec's `service_log_entries` collection: written on
    every generation, representation, or storage call so the framework
    services console can show a live cross-app request log.
    """

    __tablename__ = "service_log_entries"
    __table_args__ = (Index("ix_service_log_entries_timestamp", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_name: Mapped[str] = mapped_column(String(100))
    capability: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SearchQuery(Base):
    """One tool_use_integration search request (SearchQuery).

    Maps to the stack spec's `search_queries` collection: persisted on every
    invocation of the search capability, regardless of whether the Exa call
    that follows succeeds.
    """

    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RagInteraction(Base):
    """One rag_example_app question/answer interaction (Answer + RetrievedPassage).

    Maps to the stack spec's `rag_interactions` collection: persisted after a
    successful (grounded or below-threshold) answer, for debugging/eval only
    -- no visitor identity is stored alongside the transient question text.
    """

    __tablename__ = "rag_interactions"
    __table_args__ = (Index("ix_rag_interactions_submitted_at", "submitted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    retrieved_passages: Mapped[list[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
