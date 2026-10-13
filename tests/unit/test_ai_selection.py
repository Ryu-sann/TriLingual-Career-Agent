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
