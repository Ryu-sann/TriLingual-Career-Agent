import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.core.config import Settings
from career_agent.database.models import Application, EmailEvent, Job
from career_agent.integrations.google import IntegrationError
from career_agent.workflows.job_pipeline import discover
from career_agent.workflows.tracking import reconcile_email
from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client


def test_confirmed_email_reconciles_ambiguous_submission_without_resending(engine, profile):
    with mock_client() as client:
        discover(engine, profile, Settings(), WATCHLIST, client=client)
    with Session(engine) as s, s.begin():
        job = s.scalar(select(Job))
        app = Application(
            candidate_id=profile.candidate_id, job_id=job.id, status="UNKNOWN_SUBMISSION"
        )
        s.add(app)
        s.flush()
        app_id = app.id
        s.add(
            EmailEvent(
                provider_message_id="receipt",
                category="CONFIRMATION_CANDIDATE",
                payload={"candidate_id": profile.candidate_id},
            )
        )
    with pytest.raises(IntegrationError, match="not_verified"):
        reconcile_email(engine, app_id, "receipt")
    assert (
        reconcile_email(engine, app_id, "receipt", association_verified=True)["status"]
        == "SUBMITTED"
    )
    assert (
        reconcile_email(engine, app_id, "receipt", association_verified=True)["status"]
        == "SUBMITTED"
    )
