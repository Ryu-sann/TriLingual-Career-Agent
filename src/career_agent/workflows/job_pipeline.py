from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from career_agent.database.discovery_repository import reconcile_board
from career_agent.database.models import AuditLog, Job, JobEvaluation, WorkflowRun, now
from career_agent.database.repository import save_profile
from career_agent.discovery.adapters import PublicBoardAdapter
from career_agent.discovery.http import DiscoveryError, PublicJobClient
from career_agent.evaluation.ranking import evaluate
from career_agent.models.job import JobPosting


def discover(engine, profile, settings, watchlist, *, client=None):
    summary = {
        "phase": 2,
        "received": 0,
        "boards_succeeded": 0,
        "errors": [],
        "applications_submitted": 0,
        "live_submission_enabled": False,
    }
    with Session(engine) as session, session.begin():
        save_profile(session, profile)
        run = WorkflowRun(kind="public_job_discovery", status="RUNNING", summary=summary)
        session.add(run)
        session.flush()
        run_id = run.id
    own_client = client is None
    client = client or PublicJobClient(interval=settings.discovery.request_interval_seconds)
    adapter = PublicBoardAdapter(
        client, page_size=settings.discovery.page_size, max_pages=settings.discovery.max_pages
    )
    try:
        if not watchlist.companies:
            summary["errors"].append({"board": "watchlist", "code": "empty_watchlist"})
        for employer in watchlist.companies:
            try:
                postings = adapter.fetch(employer)
                with Session(engine) as session, session.begin():
                    counts = reconcile_board(session, employer, postings)
                    session.add(
                        AuditLog(
                            run_id=run_id,
                            action="BOARD_REFRESHED",
                            details={"board": employer.key, **counts},
                        )
                    )
                summary["received"] += len(postings)
                summary["boards_succeeded"] += 1
            except (DiscoveryError, SQLAlchemyError) as exc:
                code = exc.code if isinstance(exc, DiscoveryError) else "database_error"
                summary["errors"].append({"board": employer.key, "code": code})
        with Session(engine) as session, session.begin():
            records = list(session.scalars(select(Job)))
            evaluated = 0
            for record in records:
                raw = record.payload.get("posting")
                if not raw:
                    continue
                result = evaluate(JobPosting.model_validate(raw), profile, settings)
                session.add(
                    JobEvaluation(
                        job_id=record.id,
                        candidate_id=profile.candidate_id,
                        score=result.score,
                        opt_status=result.opt_status,
                        stem_opt_status=result.stem_opt_status,
                        evidence=result.model_dump(mode="json"),
                    )
                )
                evaluated += 1
            summary["jobs_evaluated"] = evaluated
            summary["status"] = (
                "PARTIAL"
                if summary["errors"] and summary["boards_succeeded"]
                else "FAILED"
                if summary["errors"]
                else "SUCCEEDED"
            )
            run = session.get(WorkflowRun, run_id)
            run.status, run.summary, run.finished_at = summary["status"], summary, now()
            session.add(AuditLog(run_id=run_id, action="DISCOVERY_COMPLETED", details=summary))
    except Exception:
        # Mark the durable run failed; no response bodies or candidate data in diagnostics.
        with Session(engine) as session, session.begin():
            run = session.get(WorkflowRun, run_id)
            run.status, run.finished_at = "FAILED", now()
            run.summary = {**summary, "status": "FAILED", "fatal_error": "processing_failed"}
        raise
    finally:
        if own_client:
            client.close()
    return summary


def ranked_jobs(engine, profile, settings, *, query="", moment=None):
    """Recompute time-sensitive readiness so cached evaluation never proves freshness."""
    moment = moment or datetime.now(UTC)
    rows = []
    with Session(engine) as session:
        for record in session.scalars(select(Job)):
            raw = record.payload.get("posting")
            if not raw:
                continue
            posting = JobPosting.model_validate(raw)
            if (
                query
                and query.casefold()
                not in (
                    posting.title + " " + posting.description + " " + posting.company_name
                ).casefold()
            ):
                continue
            result = evaluate(posting, profile, settings, moment=moment)
            if record.payload.get("possible_duplicate_ids"):
                result.warnings.append("possible_cross_board_duplicate_requires_review")
            rows.append(
                {
                    "id": record.id,
                    "company": posting.company_name,
                    "title": posting.title,
                    "location": posting.location,
                    "work_mode": posting.work_mode,
                    "source_url": posting.source_url,
                    "provider": posting.provider,
                    "last_seen": posting.fetched_at.isoformat(),
                    "description": posting.description,
                    "compensation": posting.compensation,
                    **result.model_dump(mode="json"),
                }
            )
    return sorted(rows, key=lambda row: (-row["score"], row["company"], row["title"]))
