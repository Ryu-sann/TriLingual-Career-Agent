from datetime import date

import pytest
from pydantic import ValidationError

from career_agent.main import readiness
from career_agent.models.candidate import CandidateProfile, Claim, Verification


def test_unknown_never_verified(profile):
    assert profile.education.cip_verification == Verification.UNKNOWN
    assert profile.verified_claims == []
    summary = readiness(profile)
    assert summary["opt_status"] == "UNKNOWN"
    assert summary["stem_opt_status"] == "UNKNOWN"
    assert summary["applications_submitted"] == 0
    assert not summary["live_submission_enabled"]


def test_verified_claim_needs_evidence():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="python", text="Python coursework", category="skill", verification="VERIFIED"
        )
    claim = Claim(
        claim_id="python",
        text="Python coursework",
        category="skill",
        verification="VERIFIED",
        source="Transcript",
        verified_by="Candidate",
        verified_on=date(2026, 10, 13),
    )
    assert claim.verification == Verification.VERIFIED


def test_only_verified_claims_can_be_used(profile):
    profile.claims = [
        Claim(
            claim_id="one",
            text="Self-reported skill",
            category="skill",
            verification="SELF_REPORTED",
        ),
        Claim(
            claim_id="two",
            text="Verified skill",
            category="skill",
            verification="VERIFIED",
            source="Transcript",
            verified_by="Candidate",
            verified_on=date(2026, 10, 13),
        ),
    ]
    assert [c.claim_id for c in profile.verified_claims] == ["two"]


@pytest.mark.parametrize(
    "changes",
    [
        {"education": {"graduation_month": "2027-13"}},
        {"education": {"cip_code": "40.0899", "cip_verification": "maybe"}},
        {"education": {"cip_code": None, "cip_verification": "VERIFIED"}},
        {"work_authorization": {"answers_verified": True}},
    ],
)
def test_invalid_profile_rejected(profile, changes):
    payload = profile.model_dump(mode="json")
    for key, value in changes.items():
        payload[key].update(value)
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)


def test_duplicate_claim_ids_rejected(profile):
    payload = profile.model_dump(mode="json")
    payload["claims"] = [dict(claim_id="same", text="Skill", category="skill")] * 2
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(payload)
