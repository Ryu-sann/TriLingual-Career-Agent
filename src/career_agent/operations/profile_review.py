import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

from career_agent.applications.policy import digest
from career_agent.models.candidate import CandidateProfile, Verification


def confirm_profile(
    path: Path, expected_hash, *, identity_confirmed, claim_ids, languages, timezone
):
    profile = CandidateProfile.load(path)
    if digest(profile.model_dump(mode="json")) != expected_hash:
        raise ValueError("profile_changed_during_review")
    known = {c.claim_id for c in profile.claims}
    if not set(claim_ids) <= known:
        raise ValueError("unknown_claim_id")
    profile.identity_verified = identity_confirmed is True
    for claim in profile.claims:
        if claim.claim_id in claim_ids:
            if not claim.source:
                raise ValueError("claim_source_missing")
            claim.verification = Verification.VERIFIED
            claim.verified_by = "candidate-dashboard"
            claim.verified_on = datetime.now(ZoneInfo(timezone)).date()
        elif claim.verification == Verification.VERIFIED:
            claim.verification = Verification.SELF_REPORTED
            claim.verified_by = None
            claim.verified_on = None
    for language in profile.languages:
        if language.language in languages:
            language.verification = Verification.VERIFIED
        elif language.verification == Verification.VERIFIED:
            language.verification = Verification.SELF_REPORTED
    # Validate again before atomic save; this operation never infers immigration answers.
    profile = CandidateProfile.model_validate(profile.model_dump(mode="json"))
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as file:
        yaml.safe_dump(profile.model_dump(mode="json"), file, allow_unicode=True, sort_keys=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)
    return {
        "verified_claims": len(profile.verified_claims),
        "identity_verified": profile.identity_verified,
    }
