from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.database.models import AuditLog, EmailEvent, WorkflowRun, now
from career_agent.integrations.google import GoogleClient, IntegrationError


def category(subject, snippet):
    text = (subject + " " + snippet).casefold()
    if any(word in text for word in ["job offer", "offer letter", "offer of employment"]):
        return "OFFER_CANDIDATE"
    if "follow up" in text or "follow-up" in text:
        return "FOLLOWUP_CANDIDATE"
    if any(word in text for word in ["interview", "面接"]):
        return "INTERVIEW_CANDIDATE"
    if any(word in text for word in ["not moving forward", "unfortunately", "rejected"]):
        return "REJECTION_CANDIDATE"
    if any(word in text for word in ["assessment", "coding challenge", "take-home"]):
        return "ASSESSMENT_CANDIDATE"
    if any(word in text for word in ["application received", "thank you for applying"]):
        return "CONFIRMATION_CANDIDATE"
    return "UNCLASSIFIED"


def sync_email(engine, profile, *, client=None):
    owned = client is None
    client = client or GoogleClient()
    try:
        expected = profile.application_email or profile.email
        actual = client.profile().get("emailAddress", "")
        if not expected or actual.casefold() != expected.casefold():
            raise IntegrationError("gmail_account_does_not_match_candidate")
        messages = client.messages()
        added, skipped = 0, 0
        for row in messages:
            with Session(engine) as session:
                existing = session.scalar(
                    select(EmailEvent.id).where(EmailEvent.provider_message_id == row["id"])
                )
            if existing:
                skipped += 1
                continue
            message = client.message(row["id"])
            headers = {
                h["name"].casefold(): h["value"]
                for h in message.get("payload", {}).get("headers", [])
            }
            sender = parseaddr(headers.get("from", ""))[1]
            subject, snippet = headers.get("subject", ""), message.get("snippet", "")
            kind = category(subject, snippet)
            with Session(engine) as session, session.begin():
                session.add(
                    EmailEvent(
                        provider_message_id=row["id"],
                        category=kind,
                        payload={
                            "subject": subject,
                            "snippet": snippet,
                            "sender": sender,
                            "date_header": headers.get("date"),
                            "needs_review": True,
                            "authentication_results": headers.get("authentication-results", ""),
                            "candidate_id": profile.candidate_id,
                            "account_email": actual,
                        },
                    )
                )
                session.add(AuditLog(action="EMAIL_OBSERVED", details={"category": kind}))
            if kind in {
                "INTERVIEW_CANDIDATE",
                "ASSESSMENT_CANDIDATE",
                "OFFER_CANDIDATE",
                "FOLLOWUP_CANDIDATE",
            }:
                with Session(engine) as session, session.begin():
                    session.add(
                        AuditLog(
                            action="EMAIL_ALERT",
                            details={
                                "candidate_id": profile.candidate_id,
                                "message_id": row["id"],
                                "category": kind,
                            },
                        )
                    )
            added += 1
        with Session(engine) as session, session.begin():
            session.add(
                WorkflowRun(
                    kind="gmail_sync",
                    status="SUCCEEDED",
                    finished_at=now(),
                    summary={"added": added, "skipped": skipped},
                )
            )
        return {"added": added, "skipped": skipped, "sent_emails": 0}
    finally:
        if owned:
            client.close()
