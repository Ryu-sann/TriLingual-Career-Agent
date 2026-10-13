import re


def fingerprint(posting):
    """Potential cross-board duplicate only, not a claim of shared requisition identity."""

    def fold(value):
        return re.sub(r"\W+", " ", value.casefold()).strip()

    return (posting.company_domain, fold(posting.title), fold(posting.location))


def deduplicate(postings):
    unique, keys, urls = [], set(), set()
    for posting in postings:
        if posting.source_key in keys or posting.source_url in urls:
            continue
        keys.add(posting.source_key)
        urls.add(posting.source_url)
        unique.append(posting)
    return unique
