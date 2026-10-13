from pathlib import Path

from streamlit.testing.v1 import AppTest

from career_agent.core.config import Settings
from career_agent.workflows.job_pipeline import discover
from tests.integration.test_discovery_pipeline import WATCHLIST, mock_client

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/career_agent/dashboard/app.py"


def test_dashboard_renders_source_urls_evidence_and_filters(engine, profile, monkeypatch):
    with mock_client() as client:
        discover(engine, profile, Settings(), WATCHLIST, client=client)
    monkeypatch.setenv("CAREER_DATABASE_URL", str(engine.url))
    monkeypatch.setenv("CAREER_PROJECT_ROOT", str(ROOT))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception and not app.error
    assert app.metric[0].value == "3"
    frame = app.dataframe[0].value
    assert "source_url" in frame.columns
    assert all(frame["source_url"].str.startswith("https://"))
    assert "UNKNOWN" in set(frame["opt_status"])
    checks = next(frame.value for frame in app.dataframe if "item" in frame.value.columns)
    assert "degree_related_duties" in set(checks["item"])
    next(w for w in app.text_input if w.label == "求人のキーワード検索").set_value(
        "no_matching_position"
    ).run()
    assert not app.exception and not app.error
    assert app.metric[0].value == "0"
    assert app.warning
    next(w for w in app.text_input if w.label == "求人のキーワード検索").set_value(
        '"unfinished phrase'
    ).run()
    assert not app.exception and not app.error
    assert any("引用符" in w.value for w in app.warning)


def test_operations_pages_render_without_leaking_secret_values(engine, profile, monkeypatch):
    monkeypatch.setenv("CAREER_DATABASE_URL", str(engine.url))
    monkeypatch.setenv("CAREER_PROJECT_ROOT", str(ROOT))
    monkeypatch.setenv("CAREER_OPENAI_API_KEY", "secret-test-must-not-display")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    for name in ["書類", "応募履歴", "メール・面接", "分析", "設定・確認事項"]:
        next(w for w in app.sidebar.selectbox if w.label == "画面").select(name).run()
        assert not app.exception and not app.error
        assert "secret-test-must-not-display" not in str([x.value for x in app.json])
