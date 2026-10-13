from pathlib import Path

import pytest

from career_agent.database.connection import engine_for, migrate
from career_agent.models.candidate import CandidateProfile

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def profile():
    return CandidateProfile.load(ROOT / "examples/candidate_profile.yaml")


@pytest.fixture
def engine(tmp_path):
    engine = engine_for(f"sqlite:///{tmp_path / 'test.db'}")
    migrate(engine, ROOT)
    yield engine
    engine.dispose()
