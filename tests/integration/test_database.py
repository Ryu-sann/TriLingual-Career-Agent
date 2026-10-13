from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from career_agent.database.connection import migrate
from career_agent.database.models import (
    Application,
    Base,
    CandidateClaim,
    CandidateProfileRecord,
    Company,
    Job,
)
from career_agent.database.repository import load_profile, save_profile, verified_claims
from career_agent.models.candidate import Claim

ROOT = Path(__file__).resolve().parents[2]


def test_migrations_match_models_and_repeat(engine):
    migrate(engine, ROOT)
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    assert len(Base.metadata.tables) == 12
    with engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def test_migration_downgrade_upgrade(engine):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    migrate(engine, ROOT)
    assert len(inspect(engine).get_table_names()) == 13


def test_profile_roundtrip_and_idempotent_upsert(engine, profile):
    profile.claims = [
        Claim(
            claim_id="lab",
            text="Lab coursework",
            category="skill",
            verification="SELF_REPORTED",
            source="Sample resume",
        )
    ]
    for _ in range(2):
        with Session(engine) as session, session.begin():
            save_profile(session, profile)
    with Session(engine) as session:
        assert load_profile(session, profile.candidate_id) == profile
        assert session.scalar(select(func.count()).select_from(CandidateProfileRecord)) == 1
        assert session.scalar(select(func.count()).select_from(CandidateClaim)) == 1
        assert verified_claims(session, profile.candidate_id) == []
    profile.claims = []
    with Session(engine) as session, session.begin():
        save_profile(session, profile)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CandidateClaim)) == 0


def test_profile_transaction_rolls_back(engine, profile):
    with pytest.raises(RuntimeError), Session(engine) as session, session.begin():
        save_profile(session, profile)
        raise RuntimeError("Abort transaction")
    with Session(engine) as session:
        assert session.get(CandidateProfileRecord, profile.candidate_id) is None


def test_duplicate_application_blocked_by_database(engine, profile):
    with Session(engine) as session, session.begin():
        save_profile(session, profile)
        session.add(Company(id="company", name="Example", canonical_domain="example.test"))
        session.flush()
        session.add(
            Job(
                id="job",
                company_id="company",
                external_job_id="123",
                title="Test",
                canonical_url="https://example.test/jobs/123",
            )
        )
        session.flush()
        session.add(Application(candidate_id=profile.candidate_id, job_id="job"))
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(Application(candidate_id=profile.candidate_id, job_id="job"))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Application)) == 1


def test_foreign_keys_enforced(engine):
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(Application(candidate_id="missing", job_id="missing"))
