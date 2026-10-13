import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from career_agent.database.connection import engine_for
from career_agent.database.models import Base
from career_agent.database.repository import load_profile, save_profile

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not os.environ.get("CAREER_TEST_DATABASE_URL"),
    reason="Set CAREER_TEST_DATABASE_URL for dedicated PostgreSQL test DB",
)
def test_postgres_migration_and_roundtrip(profile):
    engine = engine_for(os.environ["CAREER_TEST_DATABASE_URL"])
    assert engine.dialect.name == "postgresql"
    schema = "test_" + uuid4().hex
    try:
        # Bind every operation to one connection; never depend on pool session state.
        with engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET search_path TO "{schema}"'))
            conn.commit()
            cfg = Config(str(ROOT / "alembic.ini"))
            cfg.set_main_option("script_location", str(ROOT / "migrations"))
            cfg.attributes["connection"] = conn
            for _ in range(2):
                command.upgrade(cfg, "head")
            assert len(inspect(conn).get_table_names()) == 13
            assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
            conn.commit()
            with Session(conn) as session, session.begin():
                save_profile(session, profile)
            with Session(conn) as session:
                assert load_profile(session, profile.candidate_id) == profile
            conn.rollback()
            command.downgrade(cfg, "base")
            assert set(inspect(conn).get_table_names()) == {"alembic_version"}
    finally:
        with engine.begin() as conn:
            conn.execute(text("SET search_path TO public"))
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("CAREER_TEST_DATABASE_URL"),
    reason="Set CAREER_TEST_DATABASE_URL for dedicated PostgreSQL test DB",
)
def test_postgres_discovery_and_duplicate_protection(profile):
    from sqlalchemy import func, select

    from career_agent.core.config import Settings
    from career_agent.database.connection import migrate
    from career_agent.database.models import Application, Job
    from career_agent.workflows.job_pipeline import discover, ranked_jobs
    from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client

    url = os.environ["CAREER_TEST_DATABASE_URL"]
    admin = engine_for(url)
    schema = "test_" + uuid4().hex
    test_engine = None
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        test_engine = engine_for(url, connect_args={"options": f"-csearch_path={schema}"})
        migrate(test_engine, ROOT)
        for _ in range(2):
            with mock_client() as client:
                summary = discover(test_engine, profile, Settings(), WATCHLIST, client=client)
            assert summary["status"] == "SUCCEEDED"
        with Session(test_engine) as session:
            assert session.scalar(select(func.count()).select_from(Job)) == 3
            assert session.scalar(select(func.count()).select_from(Application)) == 0
        assert len(ranked_jobs(test_engine, profile, Settings())) == 3
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
