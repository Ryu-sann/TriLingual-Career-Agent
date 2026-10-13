import httpx
import pytest

from career_agent.discovery.http import DiscoveryError
from career_agent.discovery.site_search import brave_search, company_query, search_links
from tests.helpers import board


def test_company_query_is_exact_and_not_linkedin():
    query = company_query(board(), "Photonics Engineer")
    assert query == 'site:example.test/careers ("Photonics Engineer" AND "Remote")'
    assert "linkedin" not in search_links(board(), "Engineer")["google_url"]


@pytest.mark.parametrize("title", ['Engineer" OR site:linkedin.com', "Engineer\nRemote", "site:x"])
def test_operator_injection_blocked(title):
    with pytest.raises(ValueError):
        company_query(board(), title)


def test_optional_automated_search_filters_aggregators(monkeypatch):
    monkeypatch.setenv("CAREER_BRAVE_API_KEY", "test-only")

    def handler(request):
        assert request.method == "GET"
        assert request.url.params["q"].startswith("site:example.test/careers")
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"url": "https://example.test/careers/42", "title": "Engineer"},
                        {"url": "https://linkedin.com/jobs/42", "title": "Aggregator"},
                        {"url": "https://example.test.evil.com/jobs/42", "title": "Impostor"},
                    ]
                }
            },
        )

    result = brave_search(board(), "Engineer", transport=httpx.MockTransport(handler))
    assert len(result["results"]) == 1
    assert result["results"][0]["status"] == "UNVERIFIED_LEAD"


def test_missing_search_secret_is_explicit(monkeypatch):
    monkeypatch.delenv("CAREER_BRAVE_API_KEY", raising=False)
    with pytest.raises(DiscoveryError, match="search_credentials_missing"):
        brave_search(board(), "Engineer")
