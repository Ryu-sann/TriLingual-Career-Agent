from types import SimpleNamespace

import pytest

from career_agent.discovery.adapters import PublicBoardAdapter
from career_agent.documents.tailoring import DocumentError, Selection, select_claims
from tests.helpers import board, client_for, fixture
from tests.integration.test_documents import verified_profile


def test_structured_selection_validates_claim_allowlist(profile, monkeypatch):
    profile = verified_profile(profile)
    monkeypatch.setenv("CAREER_OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("CAREER_OPENAI_MODEL", "test-model")
    with client_for(fixture("greenhouse")) as c:
        job = PublicBoardAdapter(c).fetch(board())[0]
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=Selection(claim_ids=["python"]))

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    assert select_claims(profile, job, use_ai=True, client=client).claim_ids == ["python"]
    assert calls[0]["text_format"] is Selection
    client.responses.parse = lambda **_: SimpleNamespace(
        output_parsed=Selection(claim_ids=["invented"])
    )
    with pytest.raises(DocumentError):
        select_claims(profile, job, use_ai=True, client=client)


def test_default_selection_never_imports_ai(profile, monkeypatch):
    import builtins

    profile = verified_profile(profile)
    with client_for(fixture("greenhouse")) as c:
        job = PublicBoardAdapter(c).fetch(board())[0]
    original_import = builtins.__import__

    def forbid_ai(name, *args, **kwargs):
        if name.split(".")[0] in {"openai", "langgraph", "langsmith", "langchain_core"}:
            raise AssertionError("default workflow attempted an AI import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_ai)
    monkeypatch.delenv("CAREER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CAREER_OPENAI_MODEL", raising=False)
    first = select_claims(profile, job)
    assert select_claims(profile, job) == first
    assert set(first.claim_ids) == {c.claim_id for c in profile.verified_claims}


def test_explicit_ai_without_extra_has_clear_error(profile, monkeypatch):
    import builtins

    profile = verified_profile(profile)
    with client_for(fixture("greenhouse")) as c:
        job = PublicBoardAdapter(c).fetch(board())[0]
    original_import = builtins.__import__

    def missing_ai(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("optional dependency absent")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_ai)
    monkeypatch.setenv("CAREER_OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("CAREER_OPENAI_MODEL", "test-model")
    with pytest.raises(DocumentError, match="ai_extra_not_installed"):
        select_claims(profile, job, use_ai=True)
