from datetime import UTC, datetime

from pydantic import ValidationError

from career_agent.discovery.http import DiscoveryError
from career_agent.discovery.normalizer import normalize
from career_agent.models.job import EmployerBoard


class PublicBoardAdapter:
    """Greenhouse/Ashby return full feeds; only Lever uses skip/limit pagination."""

    def __init__(self, client, *, page_size=100, max_pages=100):
        if page_size not in range(1, 101) or max_pages not in range(1, 101):
            raise ValueError("Invalid pagination limits")
        self.client, self.page_size, self.max_pages = client, page_size, max_pages

    def fetch(self, employer: EmployerBoard):
        moment = datetime.now(UTC)
        provider = employer.provider
        if provider == "greenhouse":
            url = f"https://boards-api.greenhouse.io/v1/boards/{employer.board}/jobs"
            data = self.client.get_json(url, {"content": "true"})
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise DiscoveryError("invalid_feed")
        elif provider == "ashby":
            url = f"https://api.ashbyhq.com/posting-api/job-board/{employer.board}"
            data = self.client.get_json(url)
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise DiscoveryError("invalid_feed")
            if any(not isinstance(r, dict) or type(r.get("isListed")) is not bool for r in rows):
                raise DiscoveryError("invalid_feed")
            rows = [r for r in rows if isinstance(r, dict) and r.get("isListed") is True]
        else:
            url = f"https://api.lever.co/v0/postings/{employer.board}"
            rows, seen_pages = [], set()
            for page in range(self.max_pages):
                items = self.client.get_json(
                    url, {"mode": "json", "skip": page * self.page_size, "limit": self.page_size}
                )
                if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
                    raise DiscoveryError("invalid_feed")
                ids = tuple(str(x.get("id", "")) for x in items)
                if items and ids in seen_pages:
                    raise DiscoveryError("pagination_repeated")
                seen_pages.add(ids)
                rows.extend(items)
                if len(items) < self.page_size:
                    break
            else:
                raise DiscoveryError("pagination_incomplete")
        try:
            return [normalize(provider, r, employer, moment, url) for r in rows]
        except (KeyError, TypeError, ValueError, AttributeError, ValidationError) as exc:
            # Reject an incomplete/invalid board snapshot; never use it to close old jobs.
            raise DiscoveryError("invalid_posting") from exc
