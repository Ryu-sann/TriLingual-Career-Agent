import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career_agent.database.connection import engine_for
from career_agent.database.models import Application, AuditLog, CandidateProfileRecord, WorkflowRun
from career_agent.main import main

ROOT = Path(__file__).resolve().parents[2]


def test_cli_dry_run_persists_and_never_submits(tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    args = ["dry-run", "--root", str(ROOT), "--database-url", url]
    assert main(args) == 0
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "Sample Candidate" not in output
    summaries = [json.loads(line) for line in output.splitlines()]
    assert len(summaries) == 2
    assert all(s["applications_submitted"] == 0 for s in summaries)
    engine = engine_for(url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 2
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 2
        assert session.scalar(select(func.count()).select_from(CandidateProfileRecord)) == 1
        assert session.scalar(select(func.count()).select_from(Application)) == 0
    engine.dispose()


def test_bad_profile_does_not_leak_input(tmp_path, capsys):
    path = tmp_path / "profile.yaml"
    path.write_text("name: confidential-test-name\ncandidate_id: invalid id")
    assert main(["validate-profile", "--root", str(ROOT), "--profile", str(path)]) == 2
    output = capsys.readouterr().out
    assert "confidential-test-name" not in output
    assert "validation_failed" in output


def test_live_enabled_fails_before_database(tmp_path, capsys):
    path = tmp_path / "settings.yaml"
    path.write_text("automation:\n  enabled: true")
    db = tmp_path / "must-not-exist.db"
    assert (
        main(
            [
                "dry-run",
                "--root",
                str(ROOT),
                "--settings",
                str(path),
                "--database-url",
                f"sqlite:///{db}",
            ]
        )
        == 2
    )
    assert not db.exists()
    assert "validation_failed" in capsys.readouterr().out


def test_malformed_yaml_returns_safe_error(tmp_path, capsys):
    path = tmp_path / "settings.yaml"
    path.write_text("secret-personal-input: [")
    assert main(["dry-run", "--root", str(ROOT), "--settings", str(path)]) == 2
    assert "secret-personal-input" not in capsys.readouterr().out


def test_unknown_key_does_not_leak(tmp_path, capsys):
    path = tmp_path / "settings.yaml"
    path.write_text("secret-personal-input: value")
    assert main(["dry-run", "--root", str(ROOT), "--settings", str(path)]) == 2
    assert "secret-personal-input" not in capsys.readouterr().out


def test_database_relative_to_root(tmp_path, capsys):
    import shutil

    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / "migrations", tmp_path / "migrations")
    shutil.copy(ROOT / "alembic.ini", tmp_path / "alembic.ini")
    assert (
        main(["init-db", "--root", str(tmp_path), "--database-url", "sqlite:///data/test.db"]) == 0
    )
    assert (tmp_path / "data/test.db").is_file()
    assert "initialized" in capsys.readouterr().out
