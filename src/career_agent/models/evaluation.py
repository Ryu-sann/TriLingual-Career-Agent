from typing import Literal

from pydantic import Field

from career_agent.core.config import StrictModel


class Evidence(StrictModel):
    source_url: str
    excerpt: str
    interpretation: str


class Component(StrictModel):
    points: float = Field(ge=0)
    maximum: int = Field(ge=0, le=100)
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)


class EligibilityCheck(StrictModel):
    status: Literal["UNKNOWN", "VERIFIED", "REJECTED"] = "UNKNOWN"
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)


class Evaluation(StrictModel):
    version: Literal["rules-v1"] = "rules-v1"
    score: int = Field(ge=0, le=100)
    components: dict[str, Component]
    language_roles: dict[str, str]
    checks: dict[str, EligibilityCheck]
    opt_status: Literal["UNKNOWN", "REJECTED"] = "UNKNOWN"
    stem_opt_status: Literal["UNKNOWN", "REJECTED"] = "UNKNOWN"
    decision: Literal["HOLD", "LOW_PRIORITY", "REJECTED"]
    hard_blocks: list[str]
    unresolved: list[str]
    warnings: list[str]
    live_submission_allowed: Literal[False] = False
