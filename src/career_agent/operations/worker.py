import fcntl
import json
import os
import time
from pathlib import Path

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from career_agent.applications.approved_rules import from_rule
from career_agent.applications.policy import digest
from career_agent.core.config import Settings, StrictModel, load_yaml
from career_agent.database.connection import database_url, engine_for, migrate
from career_agent.database.models import (
    Application,
    AuditLog,
    EmailEvent,
    Job,
    ResumeVersion,
    WorkflowRun,
    now,
)
from career_agent.discovery.site_search import brave_search
from career_agent.documents.tailoring import DocumentError
from career_agent.integrations.google import IntegrationError
from career_agent.models.candidate import CandidateProfile
from career_agent.models.job import JobPosting, Watchlist
from career_agent.workflows.application_pipeline import apply
from career_agent.workflows.calendar_pipeline import InterviewEvent, schedule_interview
from career_agent.workflows.document_pipeline import prepare_documents
from career_agent.workflows.email_pipeline import sync_email
from career_agent.workflows.job_pipeline import discover, ranked_jobs


class Operations(StrictModel):
    discovery_hours: list[int] = [9, 21]
    site_search_enabled: bool = False
    site_search_titles: list[str] = ["Applications Engineer", "Test Engineer", "Data Analyst"]
    email_sync_enabled: bool = False
    email_poll_minutes: int = 15
    documents_enabled: bool = True
    max_documents_per_cycle: int = 25
    use_ai: bool = False
    calendar_write_enabled: bool = False
    daily_summary_enabled: bool = True

    @classmethod
    def load(cls, root):
        value = cls.model_validate(load_yaml(root / "config/operations.yaml"), strict=True)
        if not value.discovery_hours or any(h not in range(24) for h in value.discovery_hours):
            raise ValueError("Invalid discovery hours")
        if not 1 <= value.max_documents_per_cycle <= 100:
            raise ValueError("Document limit must be 1–100")
        if value.email_poll_minutes < 5:
            raise ValueError("Email poll interval must be at least 5 minutes")
        return value


def runtime(root):
    root = Path(root).resolve()
    settings = Settings.load(root / "config/settings.yaml")
    path = root / "data/profile/candidate_profile.yaml"
    profile = CandidateProfile.load(
        path if path.exists() else root / "examples/candidate_profile.yaml"
    )
    url = make_url(database_url())
    if url.get_backend_name() == "sqlite" and url.database not in {None, ":memory:"}:
        url = url.set(database=str(root / url.database))
    engine = engine_for(url)
    migrate(engine, root)
    return root, engine, settings, profile


def discovery_cycle(root):
    root, engine, settings, profile = runtime(root)
    ops = Operations.load(root)
    try:
        summary = discover(
            engine, profile, settings, Watchlist.load(root / "config/company_watchlist.yaml")
        )
        summary.update(documents_generated=0, applications_attempted=0, held=0)
        if ops.site_search_enabled:
            leads = []
            try:
                for employer in Watchlist.load(root / "config/company_watchlist.yaml").companies:
                    for title in ops.site_search_titles[:3]:
                        leads.append(brave_search(employer, title))
                        time.sleep(0.6)
                (root / "data/search_leads.json").write_text(json.dumps(leads))
                (root / "data/search_leads.json").chmod(0o600)
                summary["site_search_leads"] = sum(len(s["results"]) for s in leads)
            except IntegrationError:
                summary["site_search_error"] = "search_configuration_or_request_failed"
            except Exception:
                summary["site_search_error"] = "search_configuration_or_request_failed"
        if summary["status"] != "SUCCEEDED" or not ops.documents_enabled:
            return summary
        if not profile.identity_verified or not profile.verified_claims:
            summary["documents_blocked"] = "candidate_verification_missing"
            return summary
        policy = load_yaml(root / "config/application_policy.yaml")
        for row in ranked_jobs(engine, profile, settings):
            if (
                row["decision"] == "REJECTED"
                or row["score"] < settings.matching.minimum_review_score
            ):
                continue
            with Session(engine) as session:
                if session.scalar(
                    select(Application.id).where(
                        Application.job_id == row["id"],
                        Application.candidate_id == profile.candidate_id,
                    )
                ):
                    continue  # Includes SUBMITTING/UNKNOWN; never retry an ambiguous submission.
                posting = JobPosting.model_validate(session.get(Job, row["id"]).payload["posting"])
            if summary["documents_generated"] >= ops.max_documents_per_cycle:
                summary["document_limit_reached"] = True
                break
            cached = None
            with Session(engine) as session:
                previous = session.scalar(
                    select(ResumeVersion)
                    .where(
                        ResumeVersion.job_id == row["id"],
                        ResumeVersion.candidate_id == profile.candidate_id,
                    )
                    .order_by(ResumeVersion.version.desc())
                )
                if previous:
                    manifest_path = root / previous.document_path / "manifest.json"
                    if manifest_path.is_file():
                        stored = json.loads(manifest_path.read_text())
                        if stored.get("profile_hash") == digest(
                            profile.model_dump(mode="json")
                        ) and stored.get("job_content_hash") == digest(
                            posting.model_dump(
                                mode="json", exclude={"fetched_at", "published_at", "updated_at"}
                            )
                        ):
                            cached = {
                                "resume_id": previous.id,
                                "document_path": previous.document_path,
                            }
            try:
                document = cached or prepare_documents(
                    engine, profile, row["id"], root, use_ai=ops.use_ai
                )
                summary["documents_generated"] += int(cached is None)
            except DocumentError:
                summary["held"] += 1
                continue
            rules = [
                r
                for r in policy.get("employer_rules", [])
                if r["company_domain"] == posting.company_domain
            ]
            if not rules or row["score"] < settings.matching.minimum_auto_apply_score:
                summary["held"] += 1
                continue
            manifest = json.loads((root / document["document_path"] / "manifest.json").read_text())
            spec, review = from_rule(profile, posting, manifest, rules[0])
            result = apply(
                engine,
                profile,
                row["id"],
                document["resume_id"],
                root,
                spec,
                review,
                settings,
                mode="live" if settings.automation.enabled else "dry_run",
            )
            summary["applications_attempted"] += int(result.get("application_id") is not None)
            summary["held"] += int(result["status"] == "HOLD")
        return summary
    finally:
        engine.dispose()


def email_cycle(root):
    root, engine, _, profile = runtime(root)
    try:
        if not Operations.load(root).email_sync_enabled:
            return {"status": "DISABLED"}
        return sync_email(engine, profile)
    finally:
        engine.dispose()


def calendar_cycle(root):
    root, engine, _, _ = runtime(root)
    try:
        if not Operations.load(root).calendar_write_enabled:
            return {"status": "DISABLED"}
        with Session(engine) as session:
            proposals = [
                e.payload["calendar_proposal"]
                for e in session.scalars(select(EmailEvent))
                if e.payload.get("calendar_proposal") and not e.payload.get("calendar_event_id")
            ]
        written = 0
        for proposal in proposals:
            result = schedule_interview(engine, InterviewEvent.model_validate(proposal), write=True)
            written += int(result["status"] == "RECORDED")
        return {"recorded": written}
    finally:
        engine.dispose()


def summary_cycle(root):
    from career_agent.integrations.notifications import daily_summary

    root, engine, settings, profile = runtime(root)
    try:
        if not Operations.load(root).daily_summary_enabled:
            return {"status": "DISABLED"}
        return daily_summary(engine, profile.candidate_id, settings.project.timezone)
    finally:
        engine.dispose()


def scheduled_summary(root):
    return safe_cycle(summary_cycle, root)


def scheduled_calendar(root):
    return safe_cycle(calendar_cycle, root)


def safe_cycle(task, root):
    try:
        result = task(root)
        status = result.get("status", "SUCCEEDED")
    except Exception:
        result, status = {"error": "scheduled_operation_failed"}, "FAILED"
    _, engine, _, _ = runtime(root)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                WorkflowRun(
                    kind="scheduled_" + task.__name__,
                    status=status,
                    summary=result,
                    finished_at=now(),
                )
            )
            session.add(
                AuditLog(
                    action="SCHEDULED_CYCLE", details={"task": task.__name__, "status": status}
                )
            )
    finally:
        engine.dispose()
    return result


def scheduled_discovery(root):
    return safe_cycle(discovery_cycle, root)


def scheduled_email(root):
    return safe_cycle(email_cycle, root)


def configure_scheduler(root):
    root = Path(root).resolve()
    settings = Settings.load(root / "config/settings.yaml")
    operations = Operations.load(root)
    (root / "data").mkdir(mode=0o700, exist_ok=True)
    scheduler = BlockingScheduler(
        timezone=settings.project.timezone,
        jobstores={
            "default": SQLAlchemyJobStore(url="sqlite:///" + str(root / "data/scheduler.db"))
        },
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    scheduler.add_job(
        scheduled_discovery,
        "cron",
        hour=",".join(map(str, operations.discovery_hours)),
        args=[str(root)],
        id="discovery",
        replace_existing=True,
    )
    if operations.email_sync_enabled:
        scheduler.add_job(
            scheduled_email,
            "interval",
            minutes=operations.email_poll_minutes,
            args=[str(root)],
            id="email",
            replace_existing=True,
        )
    if operations.calendar_write_enabled:
        scheduler.add_job(
            scheduled_calendar,
            "interval",
            minutes=operations.email_poll_minutes,
            args=[str(root)],
            id="calendar",
            replace_existing=True,
        )
    if operations.daily_summary_enabled:
        scheduler.add_job(
            scheduled_summary,
            "cron",
            hour=22,
            args=[str(root)],
            id="summary",
            replace_existing=True,
        )
    return scheduler


def run_worker(root):
    root = Path(root).resolve()
    os.umask(0o077)
    (root / "data").mkdir(exist_ok=True)
    with (root / "data/worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("worker_already_running") from exc
        scheduler = configure_scheduler(root)
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            if scheduler.running:
                scheduler.shutdown(wait=True)
