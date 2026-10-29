"""Question bank: sections, variant families, questions, options, validation, generation and review."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow

QUESTION_STATUSES = ("draft", "pending_review", "approved", "rejected", "quarantined", "retired", "archived")
LEAK_STATUSES = ("none", "suspected", "confirmed", "cleared")
GENERATION_METHODS = ("human_authored", "template", "llm", "imported")
DIFFICULTY_BANDS = ("easy", "medium", "hard")


class Section(Base):
    __tablename__ = "sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # QUANT | LOGICAL | VERBAL
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")


class VariantFamily(TimestampMixin, Base):
    """All surface variants of one underlying concept. The source item is the reference for calibration."""

    __tablename__ = "variant_families"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), index=True)
    concept: Mapped[str] = mapped_column(String(200))
    skill: Mapped[str] = mapped_column(String(80))
    template_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id", use_alter=True, name="fk_family_source_question"), nullable=True
    )

    section: Mapped[Section] = relationship(lazy="joined")


class GenerationRun(TimestampMixin, Base):
    __tablename__ = "generation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    method: Mapped[str] = mapped_column(String(30))  # template | llm
    provider: Mapped[str] = mapped_column(String(40), default="deterministic-template")
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    target_difficulty: Mapped[str] = mapped_column(String(10))
    n_requested: Mapped[int] = mapped_column(Integer)
    n_generated: Mapped[int] = mapped_column(Integer, default=0)
    n_rejected: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "status in ('draft','pending_review','approved','rejected','quarantined','retired','archived')",
            name="status_valid",
        ),
        CheckConstraint("leak_status in ('none','suspected','confirmed','cleared')", name="leak_status_valid"),
        CheckConstraint("difficulty_target in ('easy','medium','hard')", name="difficulty_valid"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), index=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("variant_families.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True, index=True)
    is_source: Mapped[bool] = mapped_column(Boolean, default=False)
    skill: Mapped[str] = mapped_column(String(80))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    stem: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    difficulty_target: Mapped[str] = mapped_column(String(10), default="medium")
    difficulty_target_b: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending_review", index=True)
    status_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    leak_status: Mapped[str] = mapped_column(String(12), default="none", index=True)
    generation_method: Mapped[str] = mapped_column(String(20), default="human_authored")
    generation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_runs.id", use_alter=True, name="fk_question_generation_run"), nullable=True
    )
    template_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(12), default="not_run")
    review_requirement: Mapped[str | None] = mapped_column(String(300), nullable=True)
    normalized_hash: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data_source: Mapped[str] = mapped_column(String(60), default="synthetic_demo")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    section: Mapped[Section] = relationship(lazy="joined")
    family: Mapped[VariantFamily] = relationship(foreign_keys=[family_id], lazy="joined")
    options: Mapped[list["AnswerOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="AnswerOption.position", lazy="selectin"
    )


class AnswerOption(Base):
    __tablename__ = "answer_options"
    __table_args__ = (UniqueConstraint("question_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(2))
    text: Mapped[str] = mapped_column(String(500))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str | None] = mapped_column(String(300), nullable=True)

    question: Mapped[Question] = relationship(back_populates="options")


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    check: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10))  # pass | warn | fail
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | warning | critical
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewDecision(TimestampMixin, Base):
    __tablename__ = "review_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))  # approve | reject | request_regeneration
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    question_version: Mapped[int] = mapped_column(Integer)


class QuestionRevision(TimestampMixin, Base):
    """Append-only history. `version` is the content version at the time of the event (several events, e.g. an
    approval, can refer to the same content version)."""

    __tablename__ = "question_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(30))  # created | edited | status_change
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
