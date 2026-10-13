import shlex
from pathlib import Path

from career_agent.core.config import StrictModel, load_yaml


class SearchKeywords(StrictModel):
    priority_searches: list[str]
    secondary_searches: list[str]

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(load_yaml(path), strict=True)


def matches_query(text: str, query: str) -> bool:
    """All terms match locally; quotes preserve a phrase. Never execute search strings."""
    return all(term.casefold() in text.casefold() for term in shlex.split(query))
