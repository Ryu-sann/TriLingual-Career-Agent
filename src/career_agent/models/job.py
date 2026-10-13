from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field

from career_agent.core.config import StrictModel, load_yaml

PROVIDER_HOSTS = {
    "greenhouse": "boards-api.greenhouse.io",
    "lever": "api.lever.co",
    "ashby": "api.ashbyhq.com",
}
JOB_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
}


class EmployerBoard(StrictModel):
    name: str = Field(min_length=1, max_length=256)
    domain: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,}$")
    provider: Literal["greenhouse", "lever", "ashby"]
    board: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    careers_url: str

    @property
    def key(self):
        return f"{self.provider}:{self.board}"


class Watchlist(StrictModel):
    companies: list[EmployerBoard] = Field(max_length=100)

    @classmethod
    def load(cls, path):
        value = cls.model_validate(load_yaml(path))
        keys = [b.key for b in value.companies]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate board configuration")
        return value


class JobPosting(StrictModel):
    provider: Literal["greenhouse", "lever", "ashby"]
    board: str
    external_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    company_name: str
    company_domain: str
    title: str = Field(min_length=1, max_length=512)
    location: str
    country: str | None = None
    work_mode: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    employment_type: str | None = None
    department: str | None = None
    compensation: dict = Field(default_factory=dict)
    description: str = Field(max_length=500_000)
    source_url: str
    fetched_at: AwareDatetime
    published_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    is_listed: bool = True
    description_sha256: str
    source_api_url: str

    @property
    def source_key(self):
        return f"{self.provider}:{self.board}:{self.external_id}"

    def current_at(self, moment: datetime, max_age_hours: int) -> bool:
        age = (moment - self.fetched_at).total_seconds()
        return self.is_listed and 0 <= age <= max_age_hours * 3600
