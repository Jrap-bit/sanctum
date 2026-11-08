"""Account records. Clinical data will get separate models and access checks."""
from datetime import date
from datetime import datetime
from datetime import timezone
from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import LargeBinary
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from uuid import uuid4

from ..core.database import Base


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    credentials_ready: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    password_reset_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CredentialToken(Base):
    """Only the hash is stored; each account has at most one current credential link."""
    __tablename__ = "credential_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('activation', 'reset')", name="credential_token_purpose"),)
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (CheckConstraint("status IN ('active', 'archived', 'deleting')", name="patient_status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    primary_practitioner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __mapper_args__ = {"version_id_col": version}


class PatientAccess(Base):
    __tablename__ = "patient_access"
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class PatientEvent(Base):
    __tablename__ = "patient_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(100))  # Fixed system labels; never clinical text.
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    version: Mapped[int] = mapped_column(Integer)


class FollowUp(Base):
    __tablename__ = "follow_ups"
    __table_args__ = (CheckConstraint("state IN ('open', 'completed', 'cancelled')", name="follow_up_state"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(16), default="open")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClinicalNote(Base):
    """A draft or immutable finalized note. Amendments are new linked rows."""
    __tablename__ = "clinical_notes"
    __table_args__ = (
        CheckConstraint("state IN ('draft', 'finalized')", name="clinical_note_state"),
        CheckConstraint("version >= 1", name="clinical_note_version"),
        CheckConstraint("(state = 'draft' AND finalized_at IS NULL) OR (state = 'finalized' AND finalized_at IS NOT NULL)", name="clinical_note_finalized_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("clinical_notes.id"), nullable=True, unique=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Version is explicitly incremented so an amendment starts after its parent's version.
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class StoredDocument(Base):
    __tablename__ = "stored_documents"
    __table_args__ = (UniqueConstraint("patient_id", "digest", name="document_patient_digest"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    digest: Mapped[str] = mapped_column(String(64))
    metadata_payload: Mapped[bytes] = mapped_column(LargeBinary)
    object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_type: Mapped[str] = mapped_column(String(32))
    review_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    page_count: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"
    __table_args__ = (CheckConstraint("state IN ('queued', 'running', 'completed', 'failed', 'cancelled')", name="extraction_state"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("stored_documents.id"), unique=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    completed_pages: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExtractedPage(Base):
    __tablename__ = "extracted_pages"
    document_id: Mapped[str] = mapped_column(ForeignKey("stored_documents.id"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    payload: Mapped[bytes] = mapped_column(LargeBinary)


class DocumentImport(Base):
    __tablename__ = "document_imports"
    document_id: Mapped[str] = mapped_column(ForeignKey("stored_documents.id"), primary_key=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary)


class AISummary(Base):
    __tablename__ = "ai_summaries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SummaryJob(Base):
    __tablename__ = "summary_jobs"
    __table_args__ = (UniqueConstraint("requested_by", "request_key", name="summary_request_key"),
        CheckConstraint("state IN ('queued','running','completed','failed','cancelled')",name="summary_job_state"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(String(240), nullable=True)
    summary_id: Mapped[str | None] = mapped_column(ForeignKey("ai_summaries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IndicatorRun(Base):
    __tablename__ = 'indicator_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    input_digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    reviews: Mapped[bytes] = mapped_column(LargeBinary)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ConfirmedRating(Base):
    __tablename__='confirmed_ratings'
    __table_args__=(CheckConstraint("state IN ('confirmed','withdrawn')",name='rating_state'),)
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'),index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    withdrawal: Mapped[bytes | None] = mapped_column(LargeBinary,nullable=True)
    state: Mapped[str] = mapped_column(String(16),default='confirmed')
    version: Mapped[int] = mapped_column(Integer,default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class ConfirmedConcern(Base):
    __tablename__='confirmed_concerns'
    __table_args__=(CheckConstraint("state IN ('confirmed','withdrawn')",name='concern_state'),)
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'),index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    withdrawal: Mapped[bytes | None] = mapped_column(LargeBinary,nullable=True)
    state: Mapped[str] = mapped_column(String(16),default='confirmed')
    version: Mapped[int] = mapped_column(Integer,default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class ConfirmedMedication(Base):
    __tablename__='confirmed_medications'
    __table_args__=(CheckConstraint("state IN ('confirmed','withdrawn')",name='medication_state'),)
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'),index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    withdrawal: Mapped[bytes | None] = mapped_column(LargeBinary,nullable=True)
    state: Mapped[str] = mapped_column(String(16),default='confirmed')
    version: Mapped[int] = mapped_column(Integer,default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class RuleHead(Base):
    __tablename__='rule_heads'
    id: Mapped[str] = mapped_column(String(40),primary_key=True)
    current_version: Mapped[int] = mapped_column(Integer)


class RuleRevision(Base):
    __tablename__='rule_revisions'
    rule_id: Mapped[str] = mapped_column(ForeignKey('rule_heads.id'),primary_key=True)
    version: Mapped[int] = mapped_column(Integer,primary_key=True)
    parameters: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(1000))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)


class ClinicalGrant(Base):
    __tablename__='clinical_grants'
    __table_args__=(CheckConstraint("state IN ('pending','approved','denied','revoked','cancelled')",name='clinical_grant_state'),CheckConstraint("capability IN ('clinical:read','clinical:write')",name='clinical_grant_capability'))
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'),index=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey('users.id'),index=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    approver_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    capability: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer,default=1)
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)


class Report(Base):
    """A previewed manifest of exact source versions; export recomputes eligibility against it."""
    __tablename__ = "reports"
    __table_args__ = (CheckConstraint("state IN ('previewed', 'exported')", name="report_state"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(16), default="previewed")
    content_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeletionRecord(Base):
    """Nonclinical marker that stops a restore reintroducing a deleted patient."""
    __tablename__ = "deletion_registry"
    __table_args__ = (CheckConstraint("state IN ('deleting', 'completed')", name="deletion_state"),)
    opaque_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(16), default="deleting")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackupRecord(Base):
    __tablename__ = "backups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    path: Mapped[str] = mapped_column(String(500))
    digest: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
