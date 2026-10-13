import os
import re
from urllib.parse import urlencode, urlsplit

import httpx

from career_agent.discovery.http import DiscoveryError


def company_query(employer, title: str) -> str:
    title = title.strip()
    if not re.fullmatch(r"[\w /&+.()\-]{1,120}", title):
        raise ValueError("Job title must be plain text without search operators or quotes")
    parsed = urlsplit(employer.careers_url)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or not (host == employer.domain or host.endswith("." + employer.domain))
    ):
        raise ValueError("Careers URL must belong to the configured employer")
    target = host + parsed.path.rstrip("/")
    return f'site:{target} ("{title}" AND "Remote")'


def search_links(employer, title):
    query = company_query(employer, title)
    return {
        "company": employer.name,
        "query": query,
        "google_url": "https://www.google.com/search?" + urlencode({"q": query}),
        "bing_url": "https://www.bing.com/search?" + urlencode({"q": query}),
        "careers_url": employer.careers_url,
    }


def brave_search(employer, title, *, transport=None):
    """Optional automated search; return only results on the employer's own domain.

    Search snippets are discovery leads, never a verified job, application route or permission.
    """
    key = os.environ.get("CAREER_BRAVE_API_KEY")
    if not key:
        raise DiscoveryError("search_credentials_missing")
    query = company_query(employer, title)
    try:
        with httpx.Client(transport=transport, timeout=30, follow_redirects=False) as client:
            response = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 20},
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
            )
            if response.status_code != 200:
                raise DiscoveryError(f"search_http_{response.status_code}")
            value = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DiscoveryError("search_request_failed") from exc
    results = []
    for row in value.get("web", {}).get("results", []):
        parsed = urlsplit(row.get("url", ""))
        host = parsed.hostname or ""
        if (
            parsed.scheme == "https"
            and parsed.username is None
            and (host == employer.domain or host.endswith("." + employer.domain))
        ):
            results.append(
                {
                    "title": row.get("title", ""),
                    "url": row["url"],
                    "description": row.get("description", ""),
                    "status": "UNVERIFIED_LEAD",
                }
            )
    return {"company": employer.name, "query": query, "results": results}
