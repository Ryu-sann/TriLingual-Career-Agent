"""Associate and transition only explicitly confirmed email evidence; never guess success."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.database.models import Application, AuditLog, EmailEvent, SubmissionEvidence
from career_agent.integrations.google import IntegrationError

TRANSITIONS = {
    "CONFIRMATION_CANDIDATE": ({"SUBMITTING", "UNKNOWN_SUBMISSION"}, "SUBMITTED"),
    "INTERVIEW_CANDIDATE": ({"SUBMITTED", "UNKNOWN_SUBMISSION"}, "INTERVIEW"),
    "OFFER_CANDIDATE": ({"SUBMITTED", "INTERVIEW"}, "OFFER"),
    "REJECTION_CANDIDATE": ({"SUBMITTED", "INTERVIEW", "UNKNOWN_SUBMISSION"}, "REJECTED"),
}


def reconcile_email(engine, application_id, message_id, *, association_verified=False):
    if association_verified is not True:
        raise IntegrationError("email_association_not_verified")
    with Session(engine) as session, session.begin():
        application = session.get(Application, application_id)
        event = session.scalar(
            select(EmailEvent).where(EmailEvent.provider_message_id == message_id)
        )
        if (
            not application
            or not event
            or event.payload.get("candidate_id") != application.candidate_id
        ):
            raise IntegrationError("email_application_mismatch")
        if event.application_id and event.application_id != application_id:
            raise IntegrationError("email_already_associated")
        event.application_id = application_id
        previous = application.status
        allowed, next_status = TRANSITIONS.get(event.category, (set(), previous))
        if previous in allowed:
            application.status = next_status
            session.add(
                AuditLog(
                    application_id=application_id,
                    action="CONFIRMED_EMAIL_TRANSITION",
                    from_status=previous,
                    to_status=next_status,
                    details={"message_id": message_id},
                )
            )
            session.add(
                SubmissionEvidence(
                    application_id=application_id, kind="verified_email", reference=message_id
                )
            )
        event.payload = {**event.payload, "association_verified": True, "needs_review": False}
        return {"status": application.status, "message_id": message_id}
