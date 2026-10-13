from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.database.models import EmailEvent
from career_agent.integrations.google import GoogleClient, IntegrationError
from career_agent.integrations.vault import TokenVault
from career_agent.workflows.calendar_pipeline import InterviewEvent, schedule_interview
from career_agent.workflows.email_pipeline import sync_email


@pytest.fixture
def google(monkeypatch):
    for name in [
        "CAREER_GOOGLE_CLIENT_ID",
        "CAREER_GOOGLE_CLIENT_SECRET",
        "CAREER_GOOGLE_REFRESH_TOKEN",
    ]:
        monkeypatch.setenv(name, "test-only")
    state = {"insertions": 0, "events": {}, "requests": []}

    def handler(request):
        state["requests"].append((request.method, str(request.url)))
        if request.url.host == "oauth2.googleapis.com":
            assert request.method == "POST" and b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "fixture-access", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer fixture-access"
        path = request.url.path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "sample@example.test"})
        if path.endswith("/messages"):
            if "pageToken" not in request.url.params:
                return httpx.Response(
                    200, json={"messages": [{"id": "m1"}], "nextPageToken": "page2"}
                )
            return httpx.Response(200, json={"messages": [{"id": "m2"}]})
        if "/messages/" in path:
            return httpx.Response(
                200,
                json={
                    "snippet": "Interview invitation for review",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Hiring <jobs@example.test>"},
                            {"name": "Subject", "value": "Interview opportunity"},
                        ]
                    },
                },
            )
        if request.method == "GET" and "/events/" in path:
            event = state["events"].get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=event) if event else httpx.Response(404)
        if request.method == "POST" and path.endswith("/events"):
            import json

            body = json.loads(request.content)
            state["insertions"] += 1
            state["events"][body["id"]] = body
            return httpx.Response(200, json=body)
        raise AssertionError("Unexpected endpoint")

    client = GoogleClient(transport=httpx.MockTransport(handler))
    yield client, state
    client.close()


def test_gmail_pagination_dedup_and_account_binding(engine, profile, google):
    client, state = google
    profile.application_email = "sample@example.test"
    assert sync_email(engine, profile, client=client)["added"] == 2
    assert sync_email(engine, profile, client=client)["skipped"] == 2
    with Session(engine) as s:
        assert len(list(s.scalars(select(EmailEvent)))) == 2
        assert all(e.payload["needs_review"] for e in s.scalars(select(EmailEvent)))
    assert not any(
        method == "POST" and "gmail.googleapis.com" in url for method, url in state["requests"]
    )
    profile.application_email = "someone-else@example.test"
    with pytest.raises(IntegrationError, match="does_not_match"):
        sync_email(engine, profile, client=client)


def test_calendar_verified_time_and_idempotency(engine, profile, google):
    client, state = google
    profile.application_email = "sample@example.test"
    sync_email(engine, profile, client=client)
    event = InterviewEvent(
        source_message_id="m1",
        summary="Sample interview",
        start=datetime.now(UTC) + timedelta(days=1),
        end=datetime.now(UTC) + timedelta(days=1, hours=1),
    )
    assert schedule_interview(engine, event)["status"] == "PREVIEW" and state["insertions"] == 0
    with pytest.raises(IntegrationError, match="time_not_verified"):
        schedule_interview(engine, event, write=True, client=client)
    event.time_verified = True
    event.evidence = "Confirmed invitation"
    assert schedule_interview(engine, event, write=True, client=client)["status"] == "RECORDED"
    assert (
        schedule_interview(engine, event, write=True, client=client)["status"] == "ALREADY_RECORDED"
    )
    assert state["insertions"] == 1


def test_vault_ciphertext_and_permissions(tmp_path):
    vault = TokenVault(tmp_path / "separate-key/key", tmp_path / "state/tokens.enc")
    vault.save({"refresh_token": "private-test-token"})
    assert b"private-test-token" not in vault.data_path.read_bytes()
    assert vault.load()["refresh_token"] == "private-test-token"
    assert vault.key_path.stat().st_mode & 0o077 == 0
    assert vault.data_path.stat().st_mode & 0o077 == 0


def test_calendar_wrong_account_and_normalized_timestamps(engine, profile, google):
    client, state = google
    profile.application_email = "sample@example.test"
    sync_email(engine, profile, client=client)
    event = InterviewEvent(
        source_message_id="m1",
        summary="Interview",
        start=datetime.now(UTC) + timedelta(days=2),
        end=datetime.now(UTC) + timedelta(days=2, hours=1),
        time_verified=True,
        evidence="Confirmed",
    )
    import hashlib

    event_id = "ca" + hashlib.sha256(b"m1").hexdigest()
    state["events"][event_id] = {
        "id": event_id,
        "start": {"dateTime": event.start.isoformat().replace("+00:00", "Z")},
        "end": {"dateTime": event.end.isoformat().replace("+00:00", "Z")},
    }
    assert schedule_interview(engine, event, write=True, client=client)["status"] == "RECORDED"
    assert state["insertions"] == 0
    event.source_message_id = "m2"
    client.profile = lambda: {"emailAddress": "other@example.test"}
    with pytest.raises(IntegrationError, match="account_does_not_match"):
        schedule_interview(engine, event, write=True, client=client)
