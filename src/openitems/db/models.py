from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Engagement(Base):
    __tablename__ = "engagement"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_inbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    homepage_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    buckets: Mapped[list[Bucket]] = relationship(
        back_populates="engagement", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="engagement", cascade="all, delete-orphan"
    )


class Bucket(Base):
    __tablename__ = "bucket"
    __table_args__ = (UniqueConstraint("engagement_id", "name", name="uq_bucket_engagement_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    engagement_id: Mapped[str] = mapped_column(
        ForeignKey("engagement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_done_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    engagement: Mapped[Engagement] = relationship(back_populates="buckets")
    tasks: Mapped[list[Task]] = relationship(back_populates="bucket")


class Task(Base):
    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    engagement_id: Mapped[str] = mapped_column(
        ForeignKey("engagement.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bucket_id: Mapped[str | None] = mapped_column(
        ForeignKey("bucket.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="Medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="Not Started", nullable=False)
    assigned_to: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    labels: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    external_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    focus_week: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    engagement: Mapped[Engagement] = relationship(back_populates="tasks")
    bucket: Mapped[Bucket | None] = relationship(back_populates="tasks")
    checklist_items: Mapped[list[ChecklistItem]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.sort_order",
    )
    notes: Mapped[list[TaskNote]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskNote.created_at",
    )


class ChecklistItem(Base):
    __tablename__ = "checklist_item"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped[Task] = relationship(back_populates="checklist_items")


class TaskNote(Base):
    __tablename__ = "task_note"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="update", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )

    task: Mapped[Task] = relationship(back_populates="notes")


class AuditEntry(Base):
    __tablename__ = "audit_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
