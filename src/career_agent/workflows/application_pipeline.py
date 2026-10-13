import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career_agent.applications.browser import FormHold, execute_form
from career_agent.applications.policy import digest, policy_reasons
from career_agent.core.config import Settings, load_yaml
from career_agent.database.models import (
    Application,
    ApplicationAnswer,
    AuditLog,
    CandidateProfileRecord,
    Job,
    JobEvaluation,
    ResumeVersion,
    SubmissionEvidence,
    WorkflowRun,
    now,
)
from career_agent.models.candidate import CandidateProfile
from career_agent.models.job import JobPosting


def reserve(
    engine, profile, job_id, resume_id, settings, *, answers=None, mode="live", evidence_path=None
):
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.begin()
        try:
            with Session(conn) as session:
                session.scalar(
                    select(CandidateProfileRecord)
                    .where(CandidateProfileRecord.id == profile.candidate_id)
                    .with_for_update()
                )
                if session.scalar(
                    select(Application.id).where(
                        Application.candidate_id == profile.candidate_id,
                        Application.job_id == job_id,
                    )
                ):
                    raise FormHold("duplicate_or_ambiguous_application")
                midnight = datetime.now(ZoneInfo(settings.project.timezone)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                window = [
                    Application.created_at >= midnight.astimezone(UTC),
                    Application.created_at < (midnight + timedelta(days=1)).astimezone(UTC),
                    Application.candidate_id == profile.candidate_id,
                ]
                count = session.scalar(select(func.count()).select_from(Application).where(*window))
                company_id = session.get(Job, job_id).company_id
                same_company = session.scalar(
                    select(func.count())
                    .select_from(Application)
                    .join(Job, Application.job_id == Job.id)
                    .where(*window, Job.company_id == company_id)
                )
                if count >= settings.automation.daily_application_limit:
                    raise FormHold("daily_limit")
                if same_company >= settings.automation.max_per_company_per_day:
                    raise FormHold("company_daily_limit")
                record = Application(
                    candidate_id=profile.candidate_id,
                    job_id=job_id,
                    resume_version_id=resume_id,
                    status="SUBMITTING",
                )
                session.add(record)
                session.flush()
                session.add(
                    AuditLog(
                        application_id=record.id,
                        action="SUBMISSION_RESERVED",
                        from_status="READY_TO_SUBMIT",
                        to_status="SUBMITTING",
                        details={"mode": mode, "prefill_evidence": str(evidence_path or "")},
                    )
                )
                for answer in answers or []:
                    session.add(
                        ApplicationAnswer(
                            application_id=record.id,
                            question=answer["question"],
                            answer=answer["answer"],
                            verification=answer["verification"],
                            evidence={
                                "claim_ids": answer["claim_ids"],
                                "profile_hash": digest(profile.model_dump(mode="json")),
                            },
                        )
                    )
                record_id = record.id
                session.flush()
            conn.commit()
            return record_id
        except Exception:
            conn.rollback()
            raise


def apply(
    engine, profile, job_id, resume_id, root: Path, spec, review, settings, *, mode="dry_run"
):
    if mode not in {"dry_run", "fixture", "live"}:
        raise ValueError("Unknown execution mode")
    if mode != "fixture" and (root / "data/emergency_stop.flag").exists():
        return {"status": "HOLD", "reasons": ["emergency_stop"]}
    with Session(engine) as session:
        record, document = session.get(Job, job_id), session.get(ResumeVersion, resume_id)
        if (
            not record
            or not document
            or document.job_id != job_id
            or document.candidate_id != profile.candidate_id
        ):
            return {"status": "HOLD", "reasons": ["job_or_document_mismatch"]}
        posting = JobPosting.model_validate(record.payload["posting"])
        output = (root / document.document_path).resolve()
        if not output.is_relative_to(root.resolve()) or not output.is_dir():
            return {"status": "HOLD", "reasons": ["invalid_document_path"]}
        manifest = json.loads((output / "manifest.json").read_text())
        if digest(manifest) != document.content_sha256:
            return {"status": "HOLD", "reasons": ["document_manifest_changed"]}
        if manifest.get("profile_hash") != digest(profile.model_dump(mode="json")):
            return {"status": "HOLD", "reasons": ["document_profile_changed"]}
        if manifest.get("job_content_hash") != digest(
            posting.model_dump(mode="json", exclude={"fetched_at", "published_at", "updated_at"})
        ):
            return {"status": "HOLD", "reasons": ["document_job_changed"]}
        for name, expected in manifest["files"].items():
            path = (output / name).resolve()
            if (
                not path.is_relative_to(output)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                return {"status": "HOLD", "reasons": ["document_changed"]}
        evaluation = session.scalar(
            select(JobEvaluation)
            .where(
                JobEvaluation.job_id == job_id, JobEvaluation.candidate_id == profile.candidate_id
            )
            .order_by(JobEvaluation.created_at.desc())
        )
        reasons = policy_reasons(
            profile,
            posting,
            manifest,
            spec,
            review,
            settings,
            evaluation.score if evaluation else 0,
            mode,
        )
        if mode != "fixture":
            policy = load_yaml(root / "config/application_policy.yaml")
            permitted = spec.url in policy.get("authorized_routes", []) or any(
                posting.company_domain == rule.get("company_domain")
                and spec.url.startswith(rule.get("source_url_prefix", "INVALID"))
                for rule in policy.get("employer_rules", [])
            )
            if not permitted:
                reasons.append("route_not_in_trusted_policy")
    if reasons:
        return {"status": "HOLD", "reasons": reasons}
    evidence = root / "data/evidence" / uuid4().hex
    application_id = None

    def before_submit(answers, screenshot):
        nonlocal application_id
        if mode != "fixture":
            fresh = Settings.load(root / "config/settings.yaml")
            if (root / "data/emergency_stop.flag").exists() or (
                mode == "live"
                and (
                    fresh.automation.kill_switch
                    or not fresh.automation.enabled
                    or fresh.automation.dry_run
                )
            ):
                raise FormHold("emergency_or_live_switch_stopped")
            private = root / "data/profile/candidate_profile.yaml"
            if (
                private.is_file()
                and digest(CandidateProfile.load(private).model_dump(mode="json"))
                != review.profile_hash
            ):
                raise FormHold("candidate_changed_during_preparation")
            if evaluation.score < fresh.matching.minimum_auto_apply_score:
                raise FormHold("score_threshold_changed")
        else:
            fresh = settings
        application_id = reserve(
            engine,
            profile,
            job_id,
            resume_id,
            fresh,
            answers=answers,
            mode=mode,
            evidence_path=screenshot.relative_to(root),
        )

    try:
        result = execute_form(
            profile, spec, output / "resume.pdf", evidence, mode=mode, before_submit=before_submit
        )
    except FormHold as exc:
        result = {"status": "HOLD", "reasons": [str(exc)]}
    with Session(engine) as session, session.begin():
        run = WorkflowRun(
            kind="application_" + mode,
            status=result["status"],
            finished_at=now(),
            summary={"status": result["status"], "mode": mode},
        )
        session.add(run)
        session.flush()
        if application_id:
            application = session.get(Application, application_id)
            application.status = result["status"]
            if result["status"] == "SUBMITTED":
                application.submitted_at = now()
            if result.get("evidence"):
                path = Path(result["evidence"])
                session.add(
                    SubmissionEvidence(
                        application_id=application_id,
                        kind="fixture_confirmation"
                        if mode == "fixture"
                        else "browser_confirmation",
                        reference=str(path.relative_to(root)),
                        content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            session.add(
                AuditLog(
                    application_id=application_id,
                    run_id=run.id,
                    action="SUBMISSION_RESULT",
                    from_status="SUBMITTING",
                    to_status=result["status"],
                    details={"mode": mode},
                )
            )
        else:
            session.add(
                AuditLog(run_id=run.id, action="APPLICATION_PREPARATION", details={"mode": mode})
            )
    return {**result, "application_id": application_id, "mode": mode}
