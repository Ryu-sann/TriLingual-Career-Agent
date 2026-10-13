from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def load_yaml(path: Path) -> dict:
    if path.stat().st_size > 1_000_000:
        raise ValueError("YAML exceeds the 1 MB input limit")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a YAML mapping")
    return value


class ProjectSettings(StrictModel):
    name: str = "TriLingual Career Agent"
    timezone: str = "America/New_York"
    environment: str = "development"

    @model_validator(mode="after")
    def valid_timezone(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return self


class SearchSettings(StrictModel):
    country: str = "United States"
    relocation_allowed: bool = True
    work_modes: list[str] = Field(default_factory=lambda: ["remote", "hybrid", "onsite"])


class Weights(StrictModel):
    stem_relevance: int = Field(default=30, ge=0, le=100)
    multilingual_value: int = Field(default=25, ge=0, le=100)
    skills_match: int = Field(default=20, ge=0, le=100)
    graduation_timing: int = Field(default=15, ge=0, le=100)
    work_arrangement: int = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def sum_to_100(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError("Matching weights must sum to 100")
        return self


class MatchingSettings(StrictModel):
    minimum_auto_apply_score: int = Field(default=80, ge=80, le=100)
    minimum_review_score: int = Field(default=65, ge=0, le=100)
    weights: Weights = Field(default_factory=Weights)

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if self.minimum_review_score > self.minimum_auto_apply_score:
            raise ValueError("Review threshold exceeds auto-apply threshold")
        return self


class AutomationSettings(StrictModel):
    enabled: bool = False
    dry_run: bool = True
    kill_switch: bool = True
    daily_application_limit: int = Field(default=10, ge=1, le=10)
    max_per_company_per_day: int = Field(default=1, ge=1, le=1)

    @model_validator(mode="after")
    def discovery_only(self):
        if self.enabled or not self.dry_run:
            raise ValueError("Phases 1–2 support disabled automation and dry-run only")
        return self


class DiscoverySettings(StrictModel):
    freshness_hours: int = Field(default=24, ge=1, le=168)
    request_interval_seconds: float = Field(default=0.5, ge=0.1, le=30)
    page_size: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=100, ge=1, le=100)


class Settings(StrictModel):
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    job_search: SearchSettings = Field(default_factory=SearchSettings)
    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(load_yaml(path), strict=True)
