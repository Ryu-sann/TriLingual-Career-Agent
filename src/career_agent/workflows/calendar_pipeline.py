import hashlib
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.core.config import StrictModel
from career_agent.database.models import AuditLog, EmailEvent
from career_agent.integrations.google import GoogleClient, IntegrationError


class InterviewEvent(StrictModel):
    source_message_id: str
    summary: str = Field(min_length=1, max_length=200)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str = "America/New_York"
    time_verified: bool = Field(default=False, strict=True)
    evidence: str = ""
    type: Literal["interview", "assessment"] = "interview"

    @model_validator(mode="after")
    def valid_time(self):
        ZoneInfo(self.timezone)
        if self.end <= self.start:
            raise ValueError("Event end must follow start")
        return self


def schedule_interview(engine, event, *, write=False, client=None):
    event_id = "ca" + hashlib.sha256(event.source_message_id.encode()).hexdigest()
    body = {
        "id": event_id,
        "summary": event.summary,
        "start": {"dateTime": event.start.isoformat(), "timeZone": event.timezone},
        "end": {"dateTime": event.end.isoformat(), "timeZone": event.timezone},
        "extendedProperties": {"private": {"career_source_message": event.source_message_id}},
    }
    if not write:
        return {"status": "PREVIEW", "event": body}
    if not event.time_verified or not event.evidence:
        raise IntegrationError("interview_time_not_verified")
    with Session(engine) as session:
        source = session.scalar(
            select(EmailEvent).where(EmailEvent.provider_message_id == event.source_message_id)
        )
        if source is None:
            raise IntegrationError("source_email_not_found")
        if source.payload.get("calendar_event_id"):
            return {"status": "ALREADY_RECORDED", "event_id": source.payload["calendar_event_id"]}
    expected_account = source.payload.get("account_email")
    owned = client is None
    client = client or GoogleClient()
    try:
        if (
            not expected_account
            or client.profile().get("emailAddress", "").casefold() != expected_account.casefold()
        ):
            raise IntegrationError("calendar_account_does_not_match_source_email")
        existing = client.calendar_event(event_id)
        if existing is None:
            try:
                existing = client.create_calendar_event(body)
            except IntegrationError as exc:
                if str(exc) != "calendar_conflict":
                    raise
                existing = client.calendar_event(event_id)
        if existing:
            try:
                for field in ["start", "end"]:
                    actual_time = datetime.fromisoformat(
                        existing[field]["dateTime"].replace("Z", "+00:00")
                    )
                    expected_time = datetime.fromisoformat(body[field]["dateTime"])
                    if actual_time != expected_time:
                        raise IntegrationError("calendar_existing_event_mismatch")
            except (KeyError, ValueError) as exc:
                raise IntegrationError("calendar_existing_event_mismatch") from exc
        if not existing or existing.get("id") != event_id:
            raise IntegrationError("calendar_result_unconfirmed")
        with Session(engine) as session, session.begin():
            source = session.scalar(
                select(EmailEvent).where(EmailEvent.provider_message_id == event.source_message_id)
            )
            source.payload = {
                **source.payload,
                "calendar_event_id": event_id,
                "calendar_proposal": event.model_dump(mode="json"),
            }
            session.add(
                AuditLog(action="INTERVIEW_CALENDAR_RECORDED", details={"event_id": event_id})
            )
        return {"status": "RECORDED", "event_id": event_id}
    finally:
        if owned:
            client.close()
