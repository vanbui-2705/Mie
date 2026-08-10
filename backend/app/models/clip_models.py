"""Flow Studio clip models.

Separate module file (Goodman-style): own process/queue at runtime, but shares
the SAME SQLAlchemy Base, migration chain, and PostgreSQL as the Face module.
Do not merge these into sqlmodels.py.
"""
from __future__ import annotations

import uuid
from dataclasses import field
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, MappedAsDataclass, mapped_column, relationship

from app.models.sqlmodels import Base


class ClipSourceType(str, PyEnum):
    UPLOAD = "upload"
    LINK = "link"
    # Gen video: `source_ref` holds the prompt instead of a path or a URL. Six
    # characters like the others, so the existing VARCHAR(6) column still fits.
    PROMPT = "prompt"


class ClipJobStatus(str, PyEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    SCORING = "scoring"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"
    # The browser session went away while the job was still running: the
    # retention sweeper marks it and the runner stops between phases.
    CANCELLED = "cancelled"


class ClipStatus(str, PyEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    READY = "ready"
    ERROR = "error"
    # Kept for compatibility with records created by the earlier file-only
    # retention policy. The current sweeper removes expired rows completely.
    PURGED = "purged"


class ClipEditSource(str, PyEnum):
    AUTO = "auto"
    OPENCUT = "opencut"


class ClipJob(MappedAsDataclass, Base):
    __tablename__ = "clip_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    source_type: Mapped[ClipSourceType] = mapped_column(
        Enum(ClipSourceType, name="clip_source_type", native_enum=False), nullable=False,
    )
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default_factory=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    status: Mapped[ClipJobStatus] = mapped_column(
        Enum(ClipJobStatus, name="clip_job_status", native_enum=False),
        nullable=False, default=ClipJobStatus.QUEUED,
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default_factory=dict)
    source_sha256: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), init=False,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    # Last sign of life from a browser tab showing this job. The retention
    # sweeper deletes files and database rows older than the grace window.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), init=False,
    )
    purged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )

    clips: Mapped[list["Clip"]] = relationship(
        "Clip", back_populates="job",
        cascade="all, delete-orphan", order_by="Clip.rank",
        default_factory=list,
    )

    __table_args__ = (
        Index("idx_clip_jobs_user_created_at", user_id, created_at.desc()),
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clip_jobs.id", ondelete="CASCADE"), nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    hook_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    clipspec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[ClipStatus] = mapped_column(
        Enum(ClipStatus, name="clip_status", native_enum=False),
        nullable=False, default=ClipStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    job: Mapped["ClipJob"] = relationship("ClipJob", back_populates="clips")

    __table_args__ = (
        Index("idx_clips_job_rank", job_id, rank),
    )


class ClipEdit(Base):
    __tablename__ = "clip_edits"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    clip_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    clipspec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[ClipEditSource] = mapped_column(
        Enum(ClipEditSource, name="clip_edit_source", native_enum=False),
        nullable=False, default=ClipEditSource.AUTO,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_clip_edits_clip_version", clip_id, version),
    )


class ClipAnalysis(Base):
    """Cached transcript for one audio track, for one user.

    The transcript depends only on the audio and the ASR/prefilter settings —
    not on top_n, the length band, the editing instructions, the voice or the
    LLM backend. Re-running the same source with different instructions used to
    pay the full ASR bill again, and that is the most common thing a user does.

    Scoped per user on purpose: two accounts uploading byte-identical files do
    not share a transcript.
    """

    __tablename__ = "clip_analysis"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
