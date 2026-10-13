import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field

from career_agent.core.config import StrictModel
from career_agent.evaluation.ranking import us_location
from career_agent.models.job import JOB_HOSTS

REQUIRED_CHECKS = {
    "current_posting",
    "employer_identity",
    "us_location",
    "degree_related_duties",
    "start_date",
    "identity",
    "visa_answers",
    "documents",
    "authorized_route",
    "questions",
    "remote_supervision",
    "experience_requirements",
    "known_eligibility_constraints",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Gate(StrictModel):
    verified: bool = Field(default=False, strict=True)
    evidence: str = ""


class Review(StrictModel):
    reviewer: str = Field(min_length=1)
    reviewed_at: AwareDatetime
    profile_hash: str
    job_hash: str
    document_hash: str
    schema_hash: str
    checks: dict[str, Gate]


class FormField(StrictModel):
    selector: str = Field(pattern=r"^#[A-Za-z_][A-Za-z0-9_-]*$")
    question: dict


class FormSpec(StrictModel):
    url: str
    provider: str
    permitted: bool = Field(default=False, strict=True)
    permission_evidence: str = ""
    fields: list[FormField]
    resume_selector: str = Field(pattern=r"^#[A-Za-z_][A-Za-z0-9_-]*$")
    submit_selector: str
    confirmation_selector: str
    confirmation_text: str = Field(min_length=5)
    post_url: str
    resource_domains: list[str] = Field(default_factory=list)


def policy_reasons(profile, posting, manifest, spec, review, settings, score, mode):
    reasons = []
    if us_location(posting)[0] == "REJECTED":
        reasons.append("outside_us")
    salary = posting.compensation.get("salaryRange", {})
    if isinstance(salary, dict) and salary.get("currency") == "USD":
        floor = (
            profile.preferences.minimum_monthly_usd_remote
            if posting.work_mode == "remote"
            else profile.preferences.minimum_monthly_usd_onsite
            if posting.work_mode == "onsite"
            else None
        )
        maximum = salary.get("max")
        units = {"per-year-salary": 12, "per-month-salary": 1}
        if (
            floor is not None
            and type(maximum) in {int, float}
            and salary.get("interval") in units
            and maximum < floor * units[salary["interval"]]
        ):
            reasons.append("salary_below_candidate_floor")
    target = urlsplit(spec.url)
    if target.username is not None:
        reasons.append("url_credentials_not_allowed")
    if mode != "fixture" and spec.provider != posting.provider:
        reasons.append("adapter_provider_mismatch")
    if any(
        (target.hostname or "").endswith(domain)
        for domain in [
            "linkedin.com",
            "indeed.com",
            "ziprecruiter.com",
            "glassdoor.com",
            "monster.com",
        ]
    ):
        reasons.append("aggregator_route_forbidden")
    if mode == "fixture":
        if target.hostname not in {"127.0.0.1", "localhost"} or target.scheme != "http":
            reasons.append("fixture_must_be_loopback")
    else:
        host = target.hostname or ""
        if (
            spec.url != posting.source_url
            or target.scheme != "https"
            or not (
                host in JOB_HOSTS
                or host == posting.company_domain
                or host.endswith("." + posting.company_domain)
            )
        ):
            reasons.append("not_official_employer_route")
        if mode == "live" and (
            not settings.automation.enabled
            or settings.automation.dry_run
            or settings.automation.kill_switch
        ):
            reasons.append("live_submission_disabled")
    if not spec.permitted or not spec.permission_evidence:
        reasons.append("route_permission_not_confirmed")
    if not profile.identity_verified or not profile.work_authorization.answers_verified:
        reasons.append("candidate_verification_missing")
    if not posting.current_at(datetime.now(UTC), settings.discovery.freshness_hours):
        reasons.append("posting_not_current")
    if score < settings.matching.minimum_auto_apply_score:
        reasons.append("score_below_threshold")
    expected = {
        "profile_hash": digest(profile.model_dump(mode="json")),
        "job_hash": digest(posting.model_dump(mode="json")),
        "document_hash": digest(manifest),
        "schema_hash": digest(spec.model_dump(mode="json")),
    }
    if any(getattr(review, name) != value for name, value in expected.items()):
        reasons.append("review_does_not_match_current_inputs")
    age = (datetime.now(UTC) - review.reviewed_at).total_seconds()
    if age < 0 or age > 72 * 3600:
        reasons.append("review_expired")
    checks = REQUIRED_CHECKS | (
        {"cip_stem_list", "everify", "i983"}
        if profile.work_authorization.stem_opt_extension.value == "VERIFIED"
        else set()
    )
    for name in sorted(checks):
        gate = review.checks.get(name)
        if gate is None or not gate.verified or not gate.evidence:
            reasons.append("unverified_" + name)
    return reasons
