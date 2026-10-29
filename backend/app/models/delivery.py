"""Slots, assembled forms, attempts, responses and exposure events."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow


class Slot(TimestampMixin, Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("drive", "sequence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    drive: Mapped[str] = mapped_column(String(80), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # completed | scheduled | live
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class AssemblyRun(TimestampMixin, Base):
    __tablename__ = "assembly_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    drive: Mapped[str] = mapped_column(String(80))
    seed: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))  # succeeded | failed
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    overlap: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class TestForm(TimestampMixin, Base):
    __tablename__ = "test_forms"
    __test__ = False  # not a pytest test class
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    assembly_run_id: Mapped[int | None] = mapped_column(ForeignKey("assembly_runs.id"), nullable=True, index=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # historical | draft | published | locked
    duration_minutes: Mapped[int] = mapped_column(Integer, default=40)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

    slot: Mapped[Slot] = relationship(lazy="joined")
    items: Mapped[list["FormItem"]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="FormItem.position", lazy="selectin"
    )


class FormItem(Base):
    __tablename__ = "form_items"
    __table_args__ = (UniqueConstraint("form_id", "question_id"), UniqueConstraint("form_id", "position"))
    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("test_forms.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"))
    position: Mapped[int] = mapped_column(Integer)

    form: Mapped[TestForm] = relationship(back_populates="items")


class CandidateAssignment(Base):
    """Which candidate may take which form. Enforced server-side for listing, opening and starting attempts."""

    __tablename__ = "candidate_assignments"
    __table_args__ = (UniqueConstraint("candidate_id", "form_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("test_forms.id", ondelete="CASCADE"), index=True)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("candidate_id", "form_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("test_forms.id"), index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress | submitted | expired
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    section_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Staff-only integrity record: items withdrawn (quarantined/retired/leak-confirmed) while this attempt was live or
    # after it was scored, with an alternative score excluding them. The official score is never changed silently.
    review_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    selected_key: Mapped[str | None] = mapped_column(String(2), nullable=True)  # NULL => omitted
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExposureEvent(Base):
    """One row per (form, item) administration; candidate_count accumulates as attempts start."""

    __tablename__ = "exposure_events"
    __table_args__ = (UniqueConstraint("form_id", "question_id", "event_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("slots.id"), index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("test_forms.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(20), default="administered")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
