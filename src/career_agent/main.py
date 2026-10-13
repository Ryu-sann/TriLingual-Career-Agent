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
from career_agent.models.candidate import CandidateProfile, Verification


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
    parser = argparse.ArgumentParser(description="Phase 1: offline foundation only")
    parser.add_argument("command", choices=["init-db", "validate-profile", "dry-run"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--settings", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--profile", type=Path, default=Path("examples/candidate_profile.yaml"))
    parser.add_argument("--database-url", help="Prefer CAREER_DATABASE_URL for credentials")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    engine = None
    try:
        Settings.load(root / args.settings)
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
