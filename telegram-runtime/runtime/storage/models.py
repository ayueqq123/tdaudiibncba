"""Runtime-owned persistence models (§6.2, §6.3).

PostgreSQL-typed schema (BIGINT platform ids, timestamptz times, UUID pks) that
also runs on sqlite for tests — `uuid_str`/`utcnow` helpers abstract the two.
Control-plane entities (tenant/project/membership) live in the platform repo;
runtime tables carry tenant_id/project_id as denormalized scope columns whose
consistency is enforced at write time, not by ORM filters (§6.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Always-UTC timestamp: values come back tz-aware even on sqlite
    (whose DateTime drops tzinfo), so in-Python comparisons stay consistent
    with Postgres timestamptz reads."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SourceMessage(Base):
    __tablename__ = "source_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(String(36))
    project_id: Mapped[str] = mapped_column(String(36))
    source_scope: Mapped[str] = mapped_column(String(200))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    latest_revision: Mapped[int] = mapped_column(Integer, default=1)
    grouped_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tombstone: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow,
                                               onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "source_scope",
                         "source_chat_id", "source_message_id",
                         name="uq_source_message_identity"),
    )


class EventInbox(Base):
    __tablename__ = "event_inbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    event_id: Mapped[str] = mapped_column(String(200))
    source_scope: Mapped[str] = mapped_column(String(200))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[str] = mapped_column(String(36))
    payload_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ingest_seq: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    __table_args__ = (
        UniqueConstraint("source_scope", "source_chat_id", "source_message_id",
                         "kind", "revision", name="uq_event_inbox_dedup"),
        Index("ix_event_inbox_unprocessed", "processed", "ingest_seq"),
    )


class DeliveryJob(Base):
    __tablename__ = "delivery_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(String(36))
    project_id: Mapped[str] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))
    route_id: Mapped[str] = mapped_column(String(64))
    rule_id: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[str] = mapped_column(String(36))
    source_scope: Mapped[str] = mapped_column(String(200))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    revision: Mapped[int] = mapped_column(Integer)
    target_chat_id: Mapped[int] = mapped_column(BigInteger)
    target_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mode: Mapped[str] = mapped_column(String(10))
    payload_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requires_approval: Mapped[bool] = mapped_column(default=False)
    reply_to_target_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    grouped_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True)
    flood_wait_until: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True)
    last_error_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow,
                                               onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_delivery_job_idem"),
        Index("ix_delivery_job_claim", "account_id", "status", "next_attempt_at"),
    )


class DeliveryAttempt(Base):
    """Append-only attempt log — never updated (§6.4 boundary 3/4)."""

    __tablename__ = "delivery_attempt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("delivery_job.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    worker_generation: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    result_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    request_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no", name="uq_attempt_no"),
    )


class MessageMap(Base):
    """§6.3: source->target mapping; never hard-deleted on delivery failure."""

    __tablename__ = "message_map"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(String(36))
    project_id: Mapped[str] = mapped_column(String(36))
    rule_id: Mapped[str] = mapped_column(String(64))
    route_id: Mapped[str] = mapped_column(String(64))
    rule_version_at_create: Mapped[int] = mapped_column(Integer)
    source_scope: Mapped[str] = mapped_column(String(200))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    source_album_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_member_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sender_account_id: Mapped[str] = mapped_column(String(36))
    target_chat_id: Mapped[int] = mapped_column(BigInteger)
    target_topic_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_message_id: Mapped[int] = mapped_column(BigInteger)
    output_part_index: Mapped[int] = mapped_column(Integer, default=0)
    last_applied_revision: Mapped[int] = mapped_column(Integer, default=1)
    delivery_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="delivered")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow,
                                               onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "route_id", "source_scope",
                         "source_chat_id", "source_message_id", "output_part_index",
                         name="uq_message_map_route_output"),
        Index("ix_message_map_target_lookup", "tenant_id", "project_id",
              "sender_account_id", "target_chat_id", "target_message_id"),
    )


class AlbumGroupRow(Base):
    __tablename__ = "album_group"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    source_scope: Mapped[str] = mapped_column(String(200))
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    grouped_id: Mapped[int] = mapped_column(BigInteger)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="aggregating")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    __table_args__ = (
        UniqueConstraint("source_scope", "source_chat_id", "grouped_id",
                         name="uq_album_group"),
    )


class AlbumItemRow(Base):
    __tablename__ = "album_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    album_group_id: Mapped[str] = mapped_column(String(36), ForeignKey("album_group.id"))
    member_index: Mapped[int] = mapped_column(Integer)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    target_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("album_group_id", "member_index", name="uq_album_item_idx"),
        UniqueConstraint("album_group_id", "source_message_id", name="uq_album_item_msg"),
    )


class AccountLease(Base):
    """§5.3: per-account ownership. generation increments on every takeover;
    DB time is authoritative, Redis is never the lease of record."""

    __tablename__ = "account_lease"

    account_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    lease_until: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow,
                                               onupdate=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tenant_id: Mapped[str] = mapped_column(String(36))
    project_id: Mapped[str] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(200))
    package_hash: Mapped[str] = mapped_column(String(128))
    source_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
