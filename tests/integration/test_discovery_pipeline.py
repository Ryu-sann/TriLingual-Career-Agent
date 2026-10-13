from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career_agent.core.config import Settings
from career_agent.database.models import Application, Job, JobEvaluation, WorkflowRun
from career_agent.discovery.http import PublicJobClient
from career_agent.models.job import Watchlist
from career_agent.workflows.job_pipeline import discover, ranked_jobs
from tests.helpers import board, fixture

WATCHLIST = Watchlist(companies=[board(p) for p in ["greenhouse", "lever", "ashby"]])
ROOT = Path(__file__).resolve().parents[2]


def mock_client(overrides=None):
    overrides = overrides or {}

    def handler(request):
        assert request.method == "GET" and not request.content
        provider = (
            "greenhouse"
            if "greenhouse" in request.url.host
            else "lever"
            if "lever" in request.url.host
            else "ashby"
        )
        value = overrides.get(provider, fixture(provider))
        return (
            httpx.Response(value, text="sensitive response content")
            if isinstance(value, int)
            else httpx.Response(200, json=value)
        )

    return PublicJobClient(transport=httpx.MockTransport(handler), sleeper=lambda _: None)


def test_three_boards_repeat_without_duplicate_jobs(engine, profile):
    for _ in range(2):
        with mock_client() as client:
            summary = discover(engine, profile, Settings(), WATCHLIST, client=client)
        assert summary["status"] == "SUCCEEDED"
        assert summary["received"] == summary["jobs_evaluated"] == 3
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 3
        assert session.scalar(select(func.count()).select_from(JobEvaluation)) == 6
        assert session.scalar(select(func.count()).select_from(Application)) == 0
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 2
    rows = ranked_jobs(engine, profile, Settings())
    assert len(rows) == 3
    assert all(row["source_url"].startswith("https://") for row in rows)
    assert rows[0]["score"] >= rows[-1]["score"]
    assert all(row["opt_status"] == row["stem_opt_status"] == "UNKNOWN" for row in rows)
    assert len(ranked_jobs(engine, profile, Settings(), query="Photonics")) == 1


def test_failed_boards_do_not_close_jobs_and_partial_is_reported(engine, profile):
    with mock_client() as client:
        discover(engine, profile, Settings(), WATCHLIST, client=client)
    with mock_client({"greenhouse": {"jobs": []}, "lever": 403, "ashby": 503}) as client:
        summary = discover(engine, profile, Settings(), WATCHLIST, client=client)
    assert summary["status"] == "PARTIAL"
    assert summary["boards_succeeded"] == 1
    assert len(summary["errors"]) == 2
    with Session(engine) as session:
        jobs = list(session.scalars(select(Job)))
        statuses = {
            j.payload["posting"]["provider"]: j.payload["posting"]["is_listed"] for j in jobs
        }
    assert statuses == {"greenhouse": False, "lever": True, "ashby": True}
    rows = ranked_jobs(engine, profile, Settings())
    assert next(r for r in rows if r["provider"] == "greenhouse")["decision"] == "REJECTED"


def test_invalid_or_denied_feed_retains_last_good_snapshot(engine, profile):
    with mock_client() as client:
        discover(engine, profile, Settings(), WATCHLIST, client=client)
    with mock_client({"greenhouse": {"jobs": [{"id": 101}]}, "lever": 403, "ashby": 403}) as client:
        summary = discover(engine, profile, Settings(), WATCHLIST, client=client)
    assert summary["status"] == "FAILED"
    assert "sensitive response content" not in str(summary)
    rows = ranked_jobs(engine, profile, Settings())
    assert len(rows) == 3
    assert all("posting_not_current" not in row["hard_blocks"] for row in rows)
    stale = ranked_jobs(engine, profile, Settings(), moment=datetime.now(UTC) + timedelta(hours=25))
    assert all("posting_not_current" in row["hard_blocks"] for row in stale)


def test_empty_watchlist_is_failure_not_fake_success(engine, profile):
    with mock_client() as client:
        summary = discover(engine, profile, Settings(), Watchlist(companies=[]), client=client)
    assert summary["status"] == "FAILED"
    assert summary["errors"][0]["code"] == "empty_watchlist"
