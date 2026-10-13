import hashlib
import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from career_agent.discovery.http import DiscoveryError
from career_agent.models.job import JOB_HOSTS, EmployerBoard, JobPosting


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "li", "br", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value) -> str:
    parser = PlainText()
    parser.feed(html.unescape(str(value or "")))
    parser.close()
    text = "".join(parser.parts)
    return "\n".join(
        re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()
    )


def source_url(value: str, employer: EmployerBoard) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    allowed = JOB_HOSTS | {employer.domain, "www." + employer.domain}
    if parsed.scheme != "https" or host not in allowed or parsed.username is not None:
        raise DiscoveryError("unsafe_source_url")
    try:
        if parsed.port not in {None, 443}:
            raise DiscoveryError("unsafe_source_url")
    except ValueError as exc:
        raise DiscoveryError("unsafe_source_url") from exc
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"source", "ref"}
    ]
    return urlunsplit(("https", host, parsed.path.rstrip("/"), urlencode(sorted(query)), ""))


def timestamp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, UTC)
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result


def mode(value, location):
    text = f"{value or ''} {location or ''}".casefold()
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text:
        return "remote"
    if any(w in text for w in ("on-site", "on site", "onsite")):
        return "onsite"
    return "unknown"


def normalize(provider, row, employer, fetched_at, api_url):
    if row.get("id") is None or isinstance(row.get("id"), bool):
        raise ValueError("Missing or invalid posting identity")
    if provider == "greenhouse":
        description = plain(row.get("content"))
        location = plain((row.get("location") or {}).get("name"))
        title, url = row["title"], row["absolute_url"]
        published, updated = None, timestamp(row.get("updated_at"))
        workplace, employment = None, None
        departments = row.get("departments") or []
        department = plain(departments[0].get("name")) if departments else None
        country = None
    elif provider == "lever":
        categories = row.get("categories") or {}
        # Include every location: a US primary location must not hide other locations.
        locations = categories.get("allLocations") or [categories.get("location", "")]
        location = "; ".join(plain(v) for v in locations)
        parts = [row.get("descriptionPlain") or row.get("description", "")]
        for section in row.get("lists") or []:
            parts.extend([section.get("text", ""), section.get("content", "")])
        parts.append(row.get("additionalPlain") or row.get("additional", ""))
        description = plain("\n".join(str(part or "") for part in parts))
        title, url = row["text"], row["hostedUrl"]
        published, updated = timestamp(row.get("createdAt")), None
        workplace, employment = row.get("workplaceType"), categories.get("commitment")
        department = categories.get("department") or categories.get("team")
        country = None
    else:
        description = plain(row.get("descriptionPlain") or row.get("descriptionHtml"))
        locations = [row.get("location", "")]
        locations.extend(x.get("location", "") for x in row.get("secondaryLocations") or [])
        location = "; ".join(plain(v) for v in locations if v)
        title, url = row["title"], row["jobUrl"]
        published, updated = timestamp(row.get("publishedAt")), None
        workplace = row.get("workplaceType") or ("remote" if row.get("isRemote") else None)
        employment, department = row.get("employmentType"), row.get("department")
        country = ((row.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
    return JobPosting(
        provider=provider,
        board=employer.board,
        external_id=str(row["id"]),
        company_name=employer.name,
        company_domain=employer.domain,
        title=plain(title),
        location=location,
        country=country,
        compensation={
            k: row[k]
            for k in ("salaryRange", "salaryDescriptionPlain", "compensation", "pay_input_ranges")
            if row.get(k) is not None
        },
        work_mode=mode(workplace, location),
        employment_type=employment,
        department=department,
        description=description,
        source_url=source_url(str(url), employer),
        fetched_at=fetched_at,
        published_at=published,
        updated_at=updated,
        description_sha256=hashlib.sha256(description.encode()).hexdigest(),
        source_api_url=api_url,
    )
