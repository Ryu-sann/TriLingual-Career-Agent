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
