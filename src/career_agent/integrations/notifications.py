"""Private dashboard notifications; no outbound email or chat messages."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from career_agent.database.models import AuditLog
from career_agent.operations.analytics import overview


def daily_summary(engine, candidate_id, timezone):
    metrics = overview(engine, candidate_id)
    with Session(engine) as session, session.begin():
        session.add(
            AuditLog(
                action="DAILY_SUMMARY",
                details={
                    "candidate_id": candidate_id,
                    "local_date": datetime.now(ZoneInfo(timezone)).date().isoformat(),
                    "metrics": metrics,
                },
            )
        )
    return {"status": "SUCCEEDED", "metrics": metrics}
