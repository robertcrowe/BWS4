# Built with Spec4 AI - https://spec4.ai
"""SQLAlchemy models for RAG dataset embeddings and shared text representations."""

from __future__ import annotations

from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
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

    Carries the design entity's three fields -- prompt, requestingApp, mode --
    as `prompt_excerpt`, `app_name`, and `mode`.
    """

    __tablename__ = "language_generation_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_name: Mapped[str] = mapped_column(String(100))
    prompt_excerpt: Mapped[str] = mapped_column(Text)
    response_excerpt: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(255))
    #: "plain" or "structured" -- whether a schema was demanded of the
    #: response. Recorded rather than inferred: the same app, the same model,
    #: and the same prompt length look identical in this table otherwise, so
    #: without it there is no way to tell a free-text call from a
    #: schema-constrained one when investigating why one of them is failing.
    mode: Mapped[str] = mapped_column(String(20))
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

    The cap is an **hourly** budget, not a lifetime one: `window_start` records
    the UTC hour the current counter belongs to, and reserve_capability()
    zeroes `used` when it sees a stale hour. Without that column the counters
    only ever climbed, so a public deployment went permanently dark once the
    first N visitors had used it up -- while still telling them to "try again
    later".

    The window was per-UTC-day until v5 (migration 0009). An hour recovers fast
    enough that a visitor who arrives just after the allowance filled is asked
    to wait minutes rather than most of a day, and it puts this gate on the same
    clock as the orchestrated-subagents app's own session counter. The cap
    *values* were re-based at the same time so the showcase's exposure over a
    whole day did not multiply by 24 -- see `core/config.Settings`.
    """

    __tablename__ = "usage_limits"
    __table_args__ = (Index("ix_usage_limits_capability", "capability", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    capability: Mapped[str] = mapped_column(String(50))
    used: Mapped[int] = mapped_column(Integer, default=0)
    cap: Mapped[int] = mapped_column(Integer)
    #: The UTC hour `used` is counting for. Compared against the current hour
    #: on every reservation; an older value means the window has rolled over.
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ServiceLogEntry(Base):
    """One cross-app record of a shared-service invocation (ServiceLogEntry).

    Maps to the stack spec's `service_log_entries` collection: written on
    every generation, representation, or storage call, giving one operator-
    facing audit trail across every app. Read via the database directly --
    the maintainer console that used to surface these was removed, since it
    was a public, unauthenticated page and demonstrated no Spec4 pattern.
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


class AllowanceHold(Base):
    """One reserve/redeem/refund record against the hourly usage gate.

    Maps to the stack spec's `allowance_holds` collection. `usage_limits`
    records what has been *spent*; this records what has been *promised*, which
    is the difference between "there is room for three calls" and "there is room
    for three calls that nobody else has already claimed".

    The orchestrated-subagents app holds its whole three-call budget before it
    shows a delegation decision, so the visitor is never given a plan the
    allowance can no longer execute -- the capability's named failure between
    the decision and the dispatch confirmation.

    `state` is constrained in the database as well as here. This table is the
    ledger the gate trusts, and a fourth state introduced by some future caller
    would be silently uncounted by every reader of the other three.
    """

    __tablename__ = "allowance_holds"
    __table_args__ = (
        Index("ix_allowance_holds_capability_window", "capability", "window_start"),
        CheckConstraint(
            "state IN ('reserved', 'redeemed', 'refunded')",
            name="ck_allowance_holds_state",
        ),
    )

    #: The run's own identifier. A natural primary key rather than a surrogate
    #: id, so a retried request cannot reserve the same budget twice.
    hold_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability: Mapped[str] = mapped_column(String(50))
    app_name: Mapped[str] = mapped_column(String(100))
    units: Mapped[int] = mapped_column(Integer)
    #: The usage window this hold is charged against. A hold does not outlive
    #: its window -- once the gate rolls over there is nothing left to redeem.
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(timezone.utc)
    )


class ModerationLogEntry(Base):
    """One safety-gate decision, recorded without the question that caused it.

    Maps to the stack spec's `moderation_log` collection.

    **There is no column for the question text, and that is the design.** The
    capability requires that raw visitor input is not retained, and a schema
    with nowhere to put it enforces that better than a rule every writer has to
    remember. `question_hash` is *salted*: an unsalted hash of a short question
    is effectively reversible, because the space of plausible questions is small
    enough to enumerate.

    `failed_closed` is the column an operator actually needs. A moderation
    service that cannot be reached must block rather than wave input through,
    and without this flag an outage and a clean run are indistinguishable in the
    log.
    """

    __tablename__ = "moderation_log"
    __table_args__ = (Index("ix_moderation_log_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Salted SHA-256, hex encoded. Never the question.
    question_hash: Mapped[str] = mapped_column(String(64))
    app_name: Mapped[str] = mapped_column(String(100))
    #: None when nothing was flagged; the flagged category otherwise.
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
