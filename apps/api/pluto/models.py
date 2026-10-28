import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')"),
        CheckConstraint("email = lower(email)"),
    )


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Recovery(Record, Base):
    __tablename__ = "recoveries"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Institution(Record, Base):
    __tablename__ = "institutions"
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("status IN ('active','suspended')"),)


class Tenant:
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institutions.id"), index=True)


class Membership(Record, Tenant, Base):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        UniqueConstraint("institution_id", "user_id"),
        CheckConstraint("role IN ('owner','administrator','analyst','viewer')"),
    )


class Invitation(Record, Tenant, Base):
    __tablename__ = "invitations"
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("role IN ('owner','administrator','analyst','viewer')"),)


class InstitutionSettings(Record, Tenant, Base):
    __tablename__ = "institution_settings"
    description: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("institution_id"),)


class DataSource(Record, Tenant, Base):
    __tablename__ = "data_sources"
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text, default="")
    reference: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(30), default="not_configured")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (
        UniqueConstraint("institution_id", "id"),
        CheckConstraint(
            "category IN ('google_drive','database','api','file_storage','local_file')"
        ),
        CheckConstraint("status = 'not_configured'"),
    )


class Dataset(Record, Tenant, Base):
    __tablename__ = "datasets"
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    source_category: Mapped[str] = mapped_column(String(30))
    file_type: Mapped[str] = mapped_column(String(80), default="")
    classification: Mapped[str] = mapped_column(String(30), default="internal")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    record_count: Mapped[int | None] = mapped_column(BigInteger)
    storage_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_reference: Mapped[str] = mapped_column(String(500), default="")
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        UniqueConstraint("institution_id", "id", name="uq_dataset_tenant_id"),
        ForeignKeyConstraint(
            ["institution_id", "source_id"], ["data_sources.institution_id", "data_sources.id"]
        ),
        CheckConstraint("record_count >= 0"),
        CheckConstraint("storage_bytes >= 0"),
        CheckConstraint("classification IN ('public','internal','confidential','restricted')"),
        CheckConstraint("status IN ('draft','registered','archived')"),
        CheckConstraint(
            "source_category IN ('google_drive','database','api','file_storage','local_file')"
        ),
        Index("ix_dataset_tenant_status", "institution_id", "status"),
    )


class PlatformAdmin(Record, Base):
    __tablename__ = "platform_admins"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)


class Audit(Record, Base):
    __tablename__ = "audit_events"
    institution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("institutions.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(120))
    request_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = (Index("ix_audit_tenant_created", "institution_id", "created_at"),)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(default=1)


class IngestFile(Record, Tenant, Base):
    __tablename__ = "ingest_files"
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger)
    received: Mapped[int] = mapped_column(BigInteger, default=0)
    checksum: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="uploading")
    error: Mapped[str] = mapped_column(String(200), default="")
    __table_args__ = (
        UniqueConstraint("institution_id", "id", name="uq_file_tenant_id"),
        ForeignKeyConstraint(
            ["institution_id", "dataset_id"], ["datasets.institution_id", "datasets.id"]
        ),
        CheckConstraint("size > 0 AND received >= 0 AND received <= size"),
        CheckConstraint(
            "state IN ('uploading','queued','processing','ready','failed','cancelled')"
        ),
    )


class IngestJob(Record, Tenant, Base):
    __tablename__ = "ingest_jobs"
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["institution_id", "file_id"],
            ["ingest_files.institution_id", "ingest_files.id"],
            ondelete="CASCADE",
        ),
    )


class ContentChunk(Record, Tenant, Base):
    __tablename__ = "content_chunks"
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    position: Mapped[int] = mapped_column()
    reference: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("file_id", "position"),
        ForeignKeyConstraint(
            ["institution_id", "file_id"],
            ["ingest_files.institution_id", "ingest_files.id"],
            ondelete="CASCADE",
        ),
        Index("ix_chunks_fts", text("to_tsvector('english', content)"), postgresql_using="gin"),
    )
