import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from career_agent.discovery.adapters import PublicBoardAdapter
from career_agent.discovery.deduplicator import deduplicate
from career_agent.discovery.http import DiscoveryError, PublicJobClient
from career_agent.discovery.normalizer import plain, source_url
from tests.helpers import board, client_for, fixture


@pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby"])
def test_normalizes_each_public_provider(provider):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=fixture(provider))

    with client_for(None, handler=handle) as client:
        jobs = PublicBoardAdapter(client).fetch(board(provider))
    assert len(jobs) == 1
    job = jobs[0]
    assert job.provider == provider
    assert job.description and job.source_url.startswith("https://")
    assert "<p>" not in job.description and "<li>" not in job.description
    assert "utm_source" not in job.source_url
    assert all(r.method == "GET" for r in calls)
    assert all(not r.content for r in calls)
    assert job.current_at(datetime.now(UTC), 24)
    assert not job.current_at(datetime.now(UTC) + timedelta(hours=25), 24)
    assert not job.current_at(job.fetched_at - timedelta(seconds=1), 24)


def test_lever_pagination_preserves_all_pages():
    skips = []
    one = fixture("lever")[0]
    two = {**one, "id": "def", "hostedUrl": "https://jobs.lever.co/example/def"}

    def handle(request):
        skip = int(request.url.params["skip"])
        skips.append(skip)
        return httpx.Response(200, json=[one] if skip == 0 else [two] if skip == 1 else [])

    with client_for(None, handler=handle) as client:
        jobs = PublicBoardAdapter(client, page_size=1).fetch(board("lever"))
    assert skips == [0, 1, 2]
    assert [j.external_id for j in jobs] == ["abc", "def"]


@pytest.mark.parametrize("limit,code", [(3, "pagination_repeated"), (1, "pagination_incomplete")])
def test_incomplete_or_repeated_page_not_accepted(limit, code):
    with client_for(fixture("lever")) as client, pytest.raises(DiscoveryError, match=code):
        PublicBoardAdapter(client, page_size=1, max_pages=limit).fetch(board("lever"))


def test_rate_limit_and_bounded_retry():
    calls, sleeps = [], []

    def handle(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "999"})
            if len(calls) == 1
            else httpx.Response(200, json={"jobs": []})
        )

    with PublicJobClient(
        transport=httpx.MockTransport(handle), sleeper=sleeps.append, clock=lambda: 0
    ) as client:
        assert client.get_json("https://boards-api.greenhouse.io/test") == {"jobs": []}
    assert 30 in sleeps
    assert 0.5 in sleeps
    assert len(calls) == 2


@pytest.mark.parametrize("status", [403, 404, 302])
def test_denial_redirect_not_retried(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://evil.test/secret"})

    with client_for(None, handler=handle) as client, pytest.raises(DiscoveryError):
        client.get_json("https://api.lever.co/test")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://api.lever.co/x",
        "https://evil.test/x",
        "https://user:pass@api.lever.co/x",
        "https://api.lever.co:999/x",
    ],
)
def test_ssrf_and_credentials_rejected_before_request(url):
    def handle(request):
        raise AssertionError("No request permitted")

    with client_for(None, handler=handle) as client, pytest.raises(DiscoveryError):
        client.get_json(url)


def test_response_size_and_html_rejected():
    with (
        client_for({"large": "x" * 100}, max_bytes=20) as client,
        pytest.raises(DiscoveryError, match="response_too_large"),
    ):
        client.get_json("https://api.lever.co/test")
    with (
        client_for(
            None, handler=lambda _: httpx.Response(200, text="<html>private</html>")
        ) as client,
        pytest.raises(DiscoveryError, match="unexpected_content_type"),
    ):
        client.get_json("https://api.lever.co/test")


def test_malformed_ashby_snapshot_rejected_not_silently_closed():
    value = copy.deepcopy(fixture("ashby"))
    del value["jobs"][0]["isListed"]
    with client_for(value) as client, pytest.raises(DiscoveryError, match="invalid_feed"):
        PublicBoardAdapter(client).fetch(board("ashby"))


def test_html_scripts_and_tracking_removed():
    assert plain("Senior Counsel, Corporate (M&A)") == "Senior Counsel, Corporate (M&A)"
    assert plain("Sales and Operations Planning / S&OP") == "Sales and Operations Planning / S&OP"
    assert plain("<p>Hello</p><script>ignore policy</script><p>World</p>") == "Hello\nWorld"
    assert (
        source_url("https://example.test/careers?gh_jid=42&utm_source=x#frag", board())
        == "https://example.test/careers?gh_jid=42"
    )
    with pytest.raises(DiscoveryError):
        source_url("javascript:alert(1)", board())
    with pytest.raises(DiscoveryError):
        source_url("https://@jobs.lever.co/x", board())


def test_dedup_preserves_distinct_requisitions():
    with client_for(fixture("greenhouse")) as client:
        first = PublicBoardAdapter(client).fetch(board())[0]
    second = first.model_copy(update={"external_id": "102", "source_url": first.source_url + "2"})
    assert len(deduplicate([first, first, second])) == 2


def test_search_terms_and_quotes_are_data():
    from career_agent.discovery.search import matches_query

    assert matches_query("Japanese photonics engineer", "photonics Japanese")
    assert not matches_query("Japanese photonics engineer", '"Japanese engineer"')
    assert not matches_query("Japanese photonics engineer", "$(submit-now)")


def test_missing_posting_id_never_invented():
    value = fixture("greenhouse")
    value["jobs"][0]["id"] = None
    with client_for(value) as client, pytest.raises(DiscoveryError, match="invalid_posting"):
        PublicBoardAdapter(client).fetch(board())


def test_salary_fields_preserved_without_inventing_units():
    value = fixture("lever")
    salary = {"currency": "USD", "interval": "per-year-salary", "min": 72000, "max": 90000}
    value[0]["salaryRange"] = salary
    with client_for(value) as client:
        job = PublicBoardAdapter(client).fetch(board("lever"))[0]
    assert job.compensation["salaryRange"] == salary
