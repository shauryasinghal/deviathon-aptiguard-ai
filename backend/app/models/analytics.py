"""Calibration runs, leak datasets, leak alerts and investigations."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow


class CalibrationRun(TimestampMixin, Base):
    __tablename__ = "calibration_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    method: Mapped[str] = mapped_column(String(60))
    data_source: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict] = mapped_column(JSON)
    n_responses: Mapped[int] = mapped_column(Integer)
    n_items: Mapped[int] = mapped_column(Integer)
    n_persons: Mapped[int] = mapped_column(Integer)
    rasch_fitted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class ItemCalibration(Base):
    __tablename__ = "item_calibrations"
    __table_args__ = (UniqueConstraint("run_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("calibration_runs.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    n_presented: Mapped[int] = mapped_column(Integer)
    n_valid: Mapped[int] = mapped_column(Integer)
    n_correct: Mapped[int] = mapped_column(Integer)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_ci_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_ci_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    missing_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    item_rest_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_rt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    rasch_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    rasch_se: Mapped[float | None] = mapped_column(Float, nullable=True)
    outfit_msq: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    diff_from_reference: Mapped[float | None] = mapped_column(Float, nullable=True)
    diff_ci_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    diff_ci_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    diff_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    recommended_action: Mapped[str] = mapped_column(String(300))
    warnings: Mapped[list] = mapped_column(JSON, default=list)


class LeakDataset(Base):
    __tablename__ = "leak_datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    source_type: Mapped[str] = mapped_column(String(40))  # synthetic_demo | authorized_export
    description: Mapped[str] = mapped_column(String(500), default="")
    file_name: Mapped[str] = mapped_column(String(200))
    file_sha256: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    n_records: Mapped[int] = mapped_column(Integer)
    n_rejected: Mapped[int] = mapped_column(Integer, default=0)
    n_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    column_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class LeakRecord(Base):
    __tablename__ = "leak_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("leak_datasets.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(120))
    channel_type: Mapped[str] = mapped_column(String(40))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LeakDetectionRun(TimestampMixin, Base):
    __tablename__ = "leak_detection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    params: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class LeakAlert(Base):
    __tablename__ = "leak_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("leak_detection_runs.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("variant_families.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(40))
    evidence_class: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), index=True)  # critical | high | medium | low
    score: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(200))
    explanation: Mapped[str] = mapped_column(Text)
    signals: Mapped[list] = mapped_column(JSON, default=list)
    baseline: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    recommended_action: Mapped[str] = mapped_column(String(300))
    first_detectable_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewer_decision: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("leak_alerts.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    events: Mapped[list["InvestigationEvent"]] = relationship(
        cascade="all, delete-orphan", order_by="InvestigationEvent.created_at", lazy="selectin"
    )


class InvestigationEvent(Base):
    __tablename__ = "investigation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_ = Text
