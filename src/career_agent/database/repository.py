from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from career_agent.database.models import CandidateClaim, CandidateProfileRecord, now
from career_agent.models.candidate import CandidateProfile


def save_profile(session: Session, profile: CandidateProfile):
    payload = profile.model_dump(mode="json")
    record = session.get(CandidateProfileRecord, profile.candidate_id)
    if record is None:
        record = CandidateProfileRecord(id=profile.candidate_id, payload=payload)
        session.add(record)
    else:
        record.payload = payload
        record.updated_at = now()
    session.flush()
    session.execute(
        delete(CandidateClaim).where(CandidateClaim.candidate_id == profile.candidate_id)
    )
    for claim in profile.claims:
        session.add(
            CandidateClaim(
                candidate_id=profile.candidate_id,
                claim_id=claim.claim_id,
                verification=claim.verification.value,
                payload=claim.model_dump(mode="json"),
            )
        )
    session.flush()


def load_profile(session: Session, candidate_id: str) -> CandidateProfile:
    record = session.get(CandidateProfileRecord, candidate_id)
    if record is None:
        raise ValueError("Candidate profile not found")
    return CandidateProfile.model_validate(record.payload)


def verified_claims(session: Session, candidate_id: str):
    return list(
        session.scalars(
            select(CandidateClaim).where(
                CandidateClaim.candidate_id == candidate_id,
                CandidateClaim.verification == "VERIFIED",
            )
        )
    )
