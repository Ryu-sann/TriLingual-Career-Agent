import pytest
import yaml

from career_agent.applications.policy import digest
from career_agent.models.candidate import CandidateProfile, Claim
from career_agent.operations.profile_review import confirm_profile


def test_explicit_review_only_and_changed_input_rejected(profile, tmp_path):
    profile.claims = [
        Claim(
            claim_id="python",
            category="skill",
            text="Python coursework.",
            source="Fixture transcript",
            verification="SELF_REPORTED",
        )
    ]
    path = tmp_path / "private.yaml"
    path.write_text(yaml.safe_dump(profile.model_dump(mode="json")))
    with pytest.raises(ValueError, match="changed"):
        confirm_profile(
            path,
            "wrong",
            identity_confirmed=True,
            claim_ids=["python"],
            languages=[],
            timezone="America/New_York",
        )
    confirm_profile(
        path,
        digest(profile.model_dump(mode="json")),
        identity_confirmed=True,
        claim_ids=["python"],
        languages=["Japanese"],
        timezone="America/New_York",
    )
    loaded = CandidateProfile.load(path)
    assert loaded.identity_verified and len(loaded.verified_claims) == 1
    assert not loaded.work_authorization.answers_verified
    assert loaded.education.cip_verification.value == "UNKNOWN"
    assert path.stat().st_mode & 0o077 == 0
    confirm_profile(
        path,
        digest(loaded.model_dump(mode="json")),
        identity_confirmed=False,
        claim_ids=[],
        languages=[],
        timezone="America/New_York",
    )
    assert not CandidateProfile.load(path).identity_verified
    assert not CandidateProfile.load(path).verified_claims
