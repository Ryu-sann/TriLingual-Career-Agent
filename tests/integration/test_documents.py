from datetime import date

import pytest
from docx import Document
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from career_agent.core.config import Settings
from career_agent.database.models import Job, ResumeVersion
from career_agent.documents.tailoring import DocumentError, Selection, validate_selection
from career_agent.models.candidate import Claim
from career_agent.workflows.document_pipeline import prepare_documents
from career_agent.workflows.job_pipeline import discover
from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client


def verified_profile(profile):
    profile.identity_verified = True
    profile.claims = [
        Claim(
            claim_id="python",
            text="Python for scientific data analysis.",
            category="skill",
            verification="VERIFIED",
            source="Fictional transcript",
            verified_by="Fixture candidate",
            verified_on=date(2026, 10, 13),
        ),
        Claim(
            claim_id="degree",
            text="Bachelor of Arts in Physics undergraduate, expected December 2027.",
            category="education",
            verification="VERIFIED",
            source="Fictional transcript",
            verified_by="Fixture candidate",
            verified_on=date(2026, 10, 13),
        ),
        Claim(
            claim_id="unverified",
            text="Unverified achievement must never appear.",
            category="experience",
            verification="SELF_REPORTED",
        ),
    ]
    return profile


def test_versioned_docx_pdf_have_only_verified_claims(engine, profile, tmp_path):
    profile = verified_profile(profile)
    with mock_client() as client:
        discover(engine, profile, Settings(), WATCHLIST, client=client)
    with Session(engine) as session:
        job_id = session.scalar(select(Job.id))
    first = prepare_documents(engine, profile, job_id, tmp_path)
    second = prepare_documents(engine, profile, job_id, tmp_path)
    assert first["version"] == 1 and second["version"] == 2
    path = tmp_path / first["document_path"]
    text = " ".join(p.text for p in Document(path / "resume.docx").paragraphs)
    pdf_text = " ".join(p.extract_text() for p in PdfReader(path / "resume.pdf").pages)
    assert "Python for scientific data analysis." in text and "Python" in pdf_text
    assert "Unverified achievement" not in text + pdf_text
    assert "GPA" not in text
    with Session(engine) as session:
        records = list(session.scalars(select(ResumeVersion)))
        assert len(records) == 2 and all("unverified" not in r.claim_ids for r in records)


def test_unverified_profile_creates_no_documents(engine, profile, tmp_path):
    with mock_client() as client:
        discover(engine, profile, Settings(), WATCHLIST, client=client)
    with Session(engine) as session:
        job_id = session.scalar(select(Job.id))
    with pytest.raises(DocumentError, match="identity_not_verified"):
        prepare_documents(engine, profile, job_id, tmp_path)
    assert not list(tmp_path.rglob("*.pdf"))


def test_model_cannot_invent_claim_ids(profile):
    profile = verified_profile(profile)
    with pytest.raises(DocumentError, match="unverified"):
        validate_selection(profile, Selection(claim_ids=["unverified"]))
    with pytest.raises(DocumentError, match="unverified"):
        validate_selection(profile, Selection(claim_ids=["fabricated-metric"]))
