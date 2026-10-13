from datetime import date

from career_agent.applications.approved_rules import from_rule
from career_agent.discovery.adapters import PublicBoardAdapter
from tests.helpers import board, client_for, fixture
from tests.integration.test_documents import verified_profile


def test_reusable_rule_unknown_is_not_verified(profile):
    p = verified_profile(profile)
    p.preferences.available_start_date = date(2028, 1, 3)
    with client_for(fixture("greenhouse")) as client:
        job = PublicBoardAdapter(client).fetch(board())[0]
    rule = {
        "rule_id": "fixture-rule",
        "company_domain": "example.test",
        "verified_checks": {
            "everify": "UNKNOWN",
            "employer_identity": {"status": "UNKNOWN", "evidence": "not checked"},
        },
        "degree_duty_terms": ["design", "photonics"],
        "allowed_title_fragments": ["Photonics"],
        "verified_start_window": {
            "earliest": "2028-01-01",
            "latest": "2028-02-01",
            "evidence": "Fixture employer dates",
        },
        "post_url_template": "https://job-boards.greenhouse.io/example/jobs/{external_id}",
        "form": {
            "permitted": False,
            "permission_evidence": "",
            "fields": [],
            "resume_selector": "#resume",
            "submit_selector": "#submit",
            "confirmation_selector": "#confirmation",
            "confirmation_text": "Application received",
        },
    }
    _, review = from_rule(p, job, {"claim_ids": ["python"]}, rule)
    assert not review.checks["everify"].verified
    assert not review.checks["employer_identity"].verified
    assert review.checks["degree_related_duties"].verified
    assert review.checks["start_date"].verified


def test_known_location_and_salary_conflicts_cannot_be_overridden(profile):
    from types import SimpleNamespace

    from career_agent.applications.policy import policy_reasons
    from career_agent.core.config import Settings

    p = verified_profile(profile)
    with client_for(fixture("greenhouse")) as client:
        job = PublicBoardAdapter(client).fetch(board())[0]
    # A very high score cannot override known non-US location or explicit salary conflict.
    spec = SimpleNamespace(
        url="http://127.0.0.1/form",
        permitted=False,
        permission_evidence="",
        model_dump=lambda **_: {},
    )
    review = SimpleNamespace(
        profile_hash="",
        job_hash="",
        document_hash="",
        schema_hash="",
        reviewed_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        checks={},
    )
    foreign = job.model_copy(update={"location": "London, United Kingdom", "country": "GB"})
    assert "outside_us" in policy_reasons(p, foreign, {}, spec, review, Settings(), 100, "fixture")
    low = job.model_copy(
        update={
            "compensation": {
                "salaryRange": {"currency": "USD", "interval": "per-year-salary", "max": 30000}
            }
        }
    )
    assert "salary_below_candidate_floor" in policy_reasons(
        p, low, {}, spec, review, Settings(), 100, "fixture"
    )
