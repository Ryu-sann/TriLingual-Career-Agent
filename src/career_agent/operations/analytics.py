from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.database.models import (
    Application,
    AuditLog,
    EmailEvent,
    Job,
    ResumeVersion,
    WorkflowRun,
)


def overview(engine, candidate_id):
    with Session(engine) as session:
        apps = list(
            session.scalars(select(Application).where(Application.candidate_id == candidate_id))
        )
        modes = {
            a.application_id: a.details.get("mode", "unknown")
            for a in session.scalars(
                select(AuditLog).where(AuditLog.action == "SUBMISSION_RESERVED")
            )
        }
        statuses = Counter(a.status for a in apps if modes.get(a.id) == "live")
        return {
            "jobs": len(list(session.scalars(select(Job)))),
            "live_application_statuses": dict(statuses),
            "fixture_applications": sum(modes.get(a.id) == "fixture" for a in apps),
            "document_versions": len(
                list(
                    session.scalars(
                        select(ResumeVersion).where(ResumeVersion.candidate_id == candidate_id)
                    )
                )
            ),
            "email_events": len(
                [
                    e
                    for e in session.scalars(select(EmailEvent))
                    if e.payload.get("candidate_id") == candidate_id
                ]
            ),
            "workflow_statuses": dict(
                Counter(r.status for r in session.scalars(select(WorkflowRun)))
            ),
        }
