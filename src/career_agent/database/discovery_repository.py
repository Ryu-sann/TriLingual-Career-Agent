from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from career_agent.discovery.deduplicator import deduplicate, fingerprint
from career_agent.models.job import JobPosting

from .models import Company, Job


def reconcile_board(session, employer, postings):
    """Only call after a COMPLETE successful fetch, including a valid empty feed."""
    company = session.scalar(select(Company).where(Company.canonical_domain == employer.domain))
    if company is None:
        company = Company(
            name=employer.name,
            canonical_domain=employer.domain,
            evidence={
                "configured_careers_url": employer.careers_url,
                "identity_verification": "UNKNOWN",
            },
        )
        session.add(company)
        session.flush()
    records = list(session.scalars(select(Job).where(Job.company_id == company.id)))
    by_url = {record.canonical_url: record for record in records}
    by_alias = {}
    for record in records:
        for alias in record.payload.get("sources", {}):
            by_alias[alias] = record
    prefix = employer.key + ":"
    observed, changed = set(), {}
    unique = deduplicate(postings)
    for posting in unique:
        observed.add(posting.source_key)
        record = by_alias.get(posting.source_key) or by_url.get(posting.source_url)
        if record is None:
            record = Job(
                id=str(uuid4()),
                company_id=company.id,
                external_job_id=posting.source_key,
                title=posting.title,
                canonical_url=posting.source_url,
                payload={},
            )
            session.add(record)
            records.append(record)
        sources = dict(record.payload.get("sources", {}))
        sources[posting.source_key] = posting.model_dump(mode="json")
        record.payload = {**record.payload, "sources": sources}
        by_alias[posting.source_key] = record
        by_url[posting.source_url] = record
        changed[record.id] = record
    for record in records:
        sources = dict(record.payload.get("sources", {}))
        for alias, observation in list(sources.items()):
            if alias.startswith(prefix) and alias not in observed and observation["is_listed"]:
                sources[alias] = {**observation, "is_listed": False}
                changed[record.id] = record
        if sources:
            listed = [s for s in sources.values() if s["is_listed"]]
            preferred = max(listed or list(sources.values()), key=lambda s: s["fetched_at"])
            record.payload = {**record.payload, "sources": sources, "posting": preferred}
            record.title = preferred["title"]
            record.canonical_url = preferred["source_url"]
    # Same title/location on different ATS boards can be duplicate requisitions. Preserve both
    # unless source identity/URL is identical; flag them for review instead of losing evidence.
    groups = {}
    for record in records:
        posting_data = record.payload.get("posting")
        if posting_data:
            posting = JobPosting.model_validate(posting_data)
            if posting.is_listed:
                groups.setdefault(fingerprint(posting), []).append((record, posting.provider))
    for record in records:
        record.payload = {**record.payload, "possible_duplicate_ids": []}
    for group in groups.values():
        if len({provider for _, provider in group}) > 1:
            ids = [record.id for record, _ in group]
            for record, _ in group:
                record.payload = {
                    **record.payload,
                    "possible_duplicate_ids": [i for i in ids if i != record.id],
                }
    session.flush()
    return {
        "received": len(postings),
        "unique": len(unique),
        "changed": len(changed),
        "checked_at": datetime.now(UTC).isoformat(),
    }
