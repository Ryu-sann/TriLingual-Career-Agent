import json
from pathlib import Path

import yaml

from career_agent.main import main
from career_agent.workflows import job_pipeline
from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client

ROOT = Path(__file__).resolve().parents[2]


def test_discovery_and_list_cli(tmp_path, capsys, monkeypatch):
    watchlist = tmp_path / "boards.yaml"
    watchlist.write_text(yaml.safe_dump(WATCHLIST.model_dump()))
    monkeypatch.setattr(job_pipeline, "PublicJobClient", lambda **_: mock_client())
    shared = ["--root", str(ROOT), "--database-url", f"sqlite:///{tmp_path / 'jobs.db'}"]
    assert main(["discover", *shared, "--watchlist", str(watchlist)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["boards_succeeded"] == 3 and summary["applications_submitted"] == 0
    assert main(["list-jobs", *shared, "--query", "photonics", "--limit", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 1
    assert result["jobs"][0]["source_url"].startswith("https://")
    assert not result["jobs"][0]["live_submission_allowed"]


def test_denied_discovery_has_nonzero_exit_and_safe_error(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        job_pipeline,
        "PublicJobClient",
        lambda **_: mock_client({"greenhouse": 403, "lever": 403, "ashby": 403}),
    )
    assert (
        main(
            ["discover", "--root", str(ROOT), "--database-url", f"sqlite:///{tmp_path / 'jobs.db'}"]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "FAILED"
    assert "sensitive response content" not in output
