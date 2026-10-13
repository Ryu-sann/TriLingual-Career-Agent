import argparse
import json
import os
from pathlib import Path

import yaml
from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from career_agent.core.config import Settings
from career_agent.core.security import configure_logging
from career_agent.database.connection import database_url, engine_for, migrate
from career_agent.database.models import AuditLog, WorkflowRun, now
from career_agent.database.repository import save_profile
from career_agent.discovery.http import DiscoveryError
from career_agent.discovery.site_search import brave_search, search_links
from career_agent.documents.tailoring import DocumentError
from career_agent.integrations.google import IntegrationError
from career_agent.models.candidate import CandidateProfile, Verification
from career_agent.models.job import Watchlist
from career_agent.workflows.job_pipeline import discover, ranked_jobs


def readiness(profile: CandidateProfile) -> dict:
    unresolved = []
    if not profile.identity_verified:
        unresolved.append("identity_not_verified")
    if profile.education.cip_verification != Verification.VERIFIED:
        unresolved.append("cip_not_verified")
    if not profile.work_authorization.answers_verified:
        unresolved.append("work_authorization_answers_not_verified")
    if profile.preferences.available_start_date is None:
        unresolved.append("start_date_not_confirmed")
    if not profile.verified_claims:
        unresolved.append("no_verified_claims")
    return {
        "phase": 1,
        "mode": "dry_run",
        "live_submission_enabled": False,
        "jobs_discovered": 0,
        "applications_submitted": 0,
        "verified_claim_count": len(profile.verified_claims),
        "unresolved": unresolved,
        "opt_status": profile.work_authorization.post_completion_opt.value,
        "stem_opt_status": profile.work_authorization.stem_opt_extension.value,
    }


def main(argv=None) -> int:
    os.umask(0o077)
    configure_logging()
    parser = argparse.ArgumentParser(
        description="Offline foundation and public job discovery; no submissions"
    )
    parser.add_argument(
        "command",
        choices=[
            "init-db",
            "validate-profile",
            "dry-run",
            "discover",
            "list-jobs",
            "site-search",
            "documents",
            "application",
            "sync-email",
            "calendar",
            "worker",
        ],
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--settings", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--profile", type=Path, default=Path("examples/candidate_profile.yaml"))
    parser.add_argument("--watchlist", type=Path, default=Path("config/company_watchlist.yaml"))
    parser.add_argument("--query", default="")
    parser.add_argument("--job-id")
    parser.add_argument("--resume-id")
    parser.add_argument("--event", type=Path)
    parser.add_argument("--write-calendar", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--form-spec", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--use-ai", action="store_true")
    parser.add_argument("--job-title", default="Applications Engineer")
    parser.add_argument("--automated-search", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--database-url", help="Prefer CAREER_DATABASE_URL for credentials")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    engine = None
    try:
        settings = Settings.load(root / args.settings)
        if args.command == "worker":
            from career_agent.operations.worker import run_worker, scheduled_discovery

            if args.once:
                summary = scheduled_discovery(root)
                print(json.dumps(summary))
                return (
                    0
                    if summary.get("status") == "SUCCEEDED"
                    else 3
                    if summary.get("status") == "PARTIAL"
                    else 2
                )
            else:
                run_worker(root)
            return 0
        if args.command == "site-search":
            watchlist = Watchlist.load(root / args.watchlist)
            search = brave_search if args.automated_search else search_links
            print(
                json.dumps({"searches": [search(b, args.job_title) for b in watchlist.companies]})
            )
            return 0
        if args.command == "validate-profile":
            profile = CandidateProfile.load(root / args.profile)
            print(json.dumps({"valid": True, **readiness(profile)}, sort_keys=True))
            return 0
        url = make_url(database_url(args.database_url))
        if url.get_backend_name() == "sqlite" and url.database not in {None, ":memory:"}:
            url = url.set(database=str(root / url.database))
        engine = engine_for(url)
        migrate(engine, root)
        if args.command == "init-db":
            print(json.dumps({"schema": "0001", "status": "initialized"}))
            return 0
        profile = CandidateProfile.load(root / args.profile)
        if args.command == "sync-email":
            from career_agent.workflows.email_pipeline import sync_email

            print(json.dumps(sync_email(engine, profile)))
            return 0
        if args.command == "calendar":
            from career_agent.workflows.calendar_pipeline import InterviewEvent, schedule_interview

            if args.event is None:
                raise ValueError("Verified event file required")
            event = InterviewEvent.model_validate(json.loads(args.event.read_text()))
            print(json.dumps(schedule_interview(engine, event, write=args.write_calendar)))
            return 0
        if args.command == "application":
            from career_agent.applications.policy import FormSpec, Review
            from career_agent.workflows.application_pipeline import apply

            if args.form_spec is None or args.review is None:
                raise ValueError("Form specification and verified review are required")
            spec = FormSpec.model_validate(json.loads(args.form_spec.read_text()))
            review = Review.model_validate(json.loads(args.review.read_text()))
            result = apply(
                engine,
                profile,
                args.job_id,
                args.resume_id,
                root,
                spec,
                review,
                settings,
                mode="live" if args.live else "dry_run",
            )
            print(json.dumps(result))
            return 0 if result["status"] in {"DRY_RUN", "SUBMITTED"} else 2
        if args.command == "documents":
            from career_agent.workflows.document_pipeline import prepare_documents

            print(
                json.dumps(
                    prepare_documents(engine, profile, args.job_id, root, use_ai=args.use_ai)
                )
            )
            return 0
        if args.command == "discover":
            summary = discover(engine, profile, settings, Watchlist.load(root / args.watchlist))
            print(json.dumps(summary, sort_keys=True))
            return (
                0
                if summary["status"] == "SUCCEEDED"
                else 3
                if summary["status"] == "PARTIAL"
                else 2
            )
        if args.command == "list-jobs":
            if not 1 <= args.limit <= 1000:
                raise ValueError("Limit must be 1–1000")
            rows = ranked_jobs(engine, profile, settings, query=args.query)
            print(
                json.dumps(
                    {"phase": 2, "total": len(rows), "jobs": rows[: args.limit]}, sort_keys=True
                )
            )
            return 0
        summary = readiness(profile)
        with Session(engine) as session, session.begin():
            save_profile(session, profile)
            run = WorkflowRun(
                kind="foundation_dry_run", status="SUCCEEDED", summary=summary, finished_at=now()
            )
            session.add(run)
            session.flush()
            session.add(AuditLog(run_id=run.id, action="DRY_RUN_COMPLETED", details=summary))
        print(json.dumps(summary, sort_keys=True))
        return 0
    except IntegrationError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except DocumentError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except DiscoveryError as exc:
        print(json.dumps({"error": exc.code}))
        return 2
    except ValidationError as exc:
        # Never emit the offending values or exception text (may include personal information).
        print(json.dumps({"error": "validation_failed", "issue_count": exc.error_count()}))
        return 2
    except (OSError, ValueError, SQLAlchemyError, yaml.YAMLError, CommandError):
        print(
            json.dumps(
                {
                    "error": "operation_failed",
                    "hint": "Check paths, YAML, database access and configuration.",
                }
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
