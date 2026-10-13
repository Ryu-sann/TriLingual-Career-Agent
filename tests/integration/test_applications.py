import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.applications.policy import REQUIRED_CHECKS, FormSpec, Gate, Review, digest
from career_agent.core.config import Settings
from career_agent.database.models import Application, Job
from career_agent.workflows.application_pipeline import apply, reserve
from career_agent.workflows.document_pipeline import prepare_documents
from career_agent.workflows.job_pipeline import discover
from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client
from tests.integration.test_documents import verified_profile


@pytest.fixture
def form_server():
    state = {"posts": 0, "extra": "", "confirmation": "Thank you, application received"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                (
                    """<form action="/submit" method="post" enctype="multipart/form-data">
              <label for="name">Full name</label><input id="name" name="name" required>
              <input id="resume" name="resume" type="file" required>
              """
                    + state["extra"]
                    + '<button id="send" type="submit">Apply</button></form>'
                ).encode()
            )

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["posts"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(('<p id="confirmation">' + state["confirmation"] + "</p>").encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    thread.join()
    server.server_close()


def prepared(engine, profile, tmp_path, url):
    profile = verified_profile(profile)
    profile.work_authorization.dso_verified = True
    profile.work_authorization.work_authorization_answer = "Yes"
    profile.work_authorization.sponsorship_answer = "Yes, in the future"
    profile.work_authorization.answers_verified = True
    with mock_client() as c:
        discover(engine, profile, Settings(), WATCHLIST, client=c)
    with Session(engine) as s:
        job = next(
            j for j in s.scalars(select(Job)) if j.payload["posting"]["provider"] == "greenhouse"
        )
        job_id, posting = job.id, job.payload["posting"]
    document = prepare_documents(engine, profile, job_id, tmp_path)
    spec = FormSpec(
        url=url + "/form",
        provider="fixture",
        permitted=True,
        permission_evidence="Owned local test server",
        post_url=url + "/submit",
        fields=[
            {
                "selector": "#name",
                "question": {"label": "Full name", "kind": "identity", "field": "name"},
            }
        ],
        resume_selector="#resume",
        submit_selector="#send",
        confirmation_selector="#confirmation",
        confirmation_text="Thank you, application received",
    )
    manifest = json.loads((tmp_path / document["document_path"] / "manifest.json").read_text())
    review = Review(
        reviewer="Fixture policy",
        reviewed_at=datetime.now(UTC),
        profile_hash=digest(profile.model_dump(mode="json")),
        job_hash=digest(posting),
        document_hash=digest(manifest),
        schema_hash=digest(spec.model_dump(mode="json")),
        checks={
            key: Gate(verified=True, evidence="Owned fixture evidence") for key in REQUIRED_CHECKS
        },
    )
    return profile, job_id, document["resume_id"], spec, review


def test_browser_submit_confirmation_and_duplicate_block(engine, profile, tmp_path, form_server):
    url, state = form_server
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    result = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert result["status"] == "SUBMITTED" and state["posts"] == 1, result
    again = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert again["status"] == "HOLD" and state["posts"] == 1
    with Session(engine) as s:
        assert s.scalar(select(Application)).status == "SUBMITTED"


def test_ambiguous_submission_never_retried(engine, profile, tmp_path, form_server):
    url, state = form_server
    state["confirmation"] = "Processing, outcome unclear"
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    result = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert result["status"] == "UNKNOWN_SUBMISSION", result
    assert (
        apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")["status"]
        == "HOLD"
    )
    assert state["posts"] == 1


@pytest.mark.parametrize(
    "extra", ['<input id="unexpected" required>', '<iframe src="/captcha"></iframe>']
)
def test_unknown_questions_or_captcha_hold_before_submit(
    engine, profile, tmp_path, form_server, extra
):
    url, state = form_server
    state["extra"] = extra
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    result = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert result["status"] == "HOLD" and state["posts"] == 0


def test_fixture_mode_cannot_target_real_site(engine, profile, tmp_path, form_server):
    url, state = form_server
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    spec.url = "https://job-boards.greenhouse.io/example/jobs/101"
    result = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert "fixture_must_be_loopback" in result["reasons"] and state["posts"] == 0


def test_cap_and_document_tamper_hold(engine, profile, tmp_path, form_server):
    url, _ = form_server
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    limited = Settings()
    limited.automation.daily_application_limit = 1
    reserve(engine, p, job, resume, limited)
    with Session(engine) as s:
        other = next(j.id for j in s.scalars(select(Job)) if j.id != job)
    from career_agent.applications.browser import FormHold

    with pytest.raises(FormHold, match="daily_limit"):
        reserve(engine, p, other, resume, limited)
    with Session(engine) as s:
        from career_agent.database.models import ResumeVersion

        folder = tmp_path / s.get(ResumeVersion, resume).document_path
    (folder / "resume.pdf").write_bytes(b"tampered")
    assert apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")[
        "reasons"
    ] == ["document_changed"]


def test_dry_run_prefills_but_never_posts(engine, profile, tmp_path, form_server):
    from career_agent.applications.browser import execute_form
    from career_agent.database.models import ResumeVersion

    url, state = form_server
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    with Session(engine) as s:
        path = tmp_path / s.get(ResumeVersion, resume).document_path / "resume.pdf"

    def forbidden(*_):
        raise AssertionError("No reservation or submission during dry-run")

    result = execute_form(
        p, spec, path, tmp_path / "dry-evidence", mode="dry_run", before_submit=forbidden
    )
    assert result["status"] == "DRY_RUN" and state["posts"] == 0


def test_changed_review_and_live_kill_switch_hold(engine, profile, tmp_path, form_server):
    url, state = form_server
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    review.profile_hash = "changed"
    result = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert "review_does_not_match_current_inputs" in result["reasons"]
    assert state["posts"] == 0
    from career_agent.applications.policy import policy_reasons
    from career_agent.models.job import JobPosting

    with Session(engine) as s:
        posting = JobPosting.model_validate(s.get(Job, job).payload["posting"])
    reasons = policy_reasons(p, posting, {}, spec, review, Settings(), 99, "live")
    assert "live_submission_disabled" in reasons


def test_emergency_flag_stops_before_any_browser_or_document_work(engine, profile, tmp_path):
    flag = tmp_path / "data/emergency_stop.flag"
    flag.parent.mkdir()
    flag.write_text("paused")
    assert apply(
        engine, profile, "missing", "missing", tmp_path, None, None, Settings(), mode="live"
    )["reasons"] == ["emergency_stop"]


def test_new_required_demographic_question_is_not_omitted(engine, profile, tmp_path, form_server):
    from career_agent.applications.policy import FormField

    url, state = form_server
    state["extra"] = '<label for="gender">Gender</label><input id="gender" aria-required="true">'
    p, job, resume, spec, review = prepared(engine, profile, tmp_path, url)
    spec.fields.append(
        FormField(
            selector="#gender",
            question={"label": "Gender", "kind": "demographic", "required": False},
        )
    )
    review.schema_hash = digest(spec.model_dump(mode="json"))
    result = apply(engine, p, job, resume, tmp_path, spec, review, Settings(), mode="fixture")
    assert result["status"] == "HOLD" and "required_question_changed" in result["reasons"]
    assert state["posts"] == 0
