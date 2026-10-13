from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CandidateProfileRecord(Record, Base):
    __tablename__ = "candidate_profiles"
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CandidateClaim(Record, Base):
    __tablename__ = "candidate_claims"
    __table_args__ = (UniqueConstraint("candidate_id", "claim_id"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"))
    claim_id: Mapped[str] = mapped_column(String(128))
    verification: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)


class Company(Record, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(256))
    canonical_domain: Mapped[str] = mapped_column(String(256), unique=True)
    everify_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Record, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("company_id", "external_job_id"),)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    external_job_id: Mapped[str] = mapped_column(String(256))
    title: Mapped[str] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class JobEvaluation(Record, Base):
    __tablename__ = "job_evaluations"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"))
    score: Mapped[int] = mapped_column(Integer)
    opt_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    stem_opt_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class ResumeVersion(Record, Base):
    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id", "version"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    version: Mapped[int] = mapped_column(Integer)
    document_path: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)


class Application(Record, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id"),)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    resume_version_id: Mapped[str | None] = mapped_column(ForeignKey("resume_versions.id"))
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationAnswer(Record, Base):
    __tablename__ = "application_answers"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    verification: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class SubmissionEvidence(Record, Base):
    __tablename__ = "submission_evidence"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    kind: Mapped[str] = mapped_column(String(64))
    reference: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class EmailEvent(Record, Base):
    __tablename__ = "email_events"
    provider_message_id: Mapped[str] = mapped_column(String(256), unique=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"))
    category: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class WorkflowRun(Record, Base):
    __tablename__ = "workflow_runs"
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Record, Base):
    __tablename__ = "audit_logs"
    run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"))
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"))
    action: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
