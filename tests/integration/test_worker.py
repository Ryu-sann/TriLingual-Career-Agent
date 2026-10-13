import shutil
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career_agent.database.connection import engine_for
from career_agent.database.models import ResumeVersion
from career_agent.operations import worker
from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client
from tests.integration.test_documents import verified_profile

ROOT = Path(__file__).resolve().parents[2]


def test_worker_document_reuse_and_no_unconfigured_applications(tmp_path, profile, monkeypatch):
    for name in ["config", "examples", "migrations"]:
        shutil.copytree(ROOT / name, tmp_path / name)
    shutil.copy(ROOT / "alembic.ini", tmp_path / "alembic.ini")
    private = tmp_path / "data/profile"
    private.mkdir(parents=True)
    profile = verified_profile(profile)
    (private / "candidate_profile.yaml").write_text(yaml.safe_dump(profile.model_dump(mode="json")))
    (tmp_path / "config/company_watchlist.yaml").write_text(yaml.safe_dump(WATCHLIST.model_dump()))
    monkeypatch.delenv("CAREER_DATABASE_URL", raising=False)
    original = worker.discover

    def offline(*args, **kwargs):
        with mock_client() as client:
            return original(*args, **kwargs, client=client)

    monkeypatch.setattr(worker, "discover", offline)
    first = worker.discovery_cycle(tmp_path)
    second = worker.discovery_cycle(tmp_path)
    assert first["documents_generated"] == 1
    assert second["documents_generated"] == 0
    assert first["applications_attempted"] == second["applications_attempted"] == 0
    engine = engine_for("sqlite:///" + str(tmp_path / "data/career.db"))
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(ResumeVersion)) == 1
    engine.dispose()
