import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from career_agent.core.config import StrictModel, load_yaml


class Verification(StrEnum):
    UNKNOWN = "UNKNOWN"
    SELF_REPORTED = "SELF_REPORTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Education(StrictModel):
    institution: str = Field(min_length=1)
    degree: str = Field(min_length=1)
    major: str = Field(min_length=1)
    minor: str | None = None
    graduation_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    cip_code: str | None = Field(default=None, pattern=r"^\d{2}\.\d{4}$")
    cip_verification: Verification = Verification.UNKNOWN
    gpa: float | None = Field(default=None, ge=0, le=4)

    @model_validator(mode="after")
    def verified_cip_present(self):
        if self.cip_verification == Verification.VERIFIED and not self.cip_code:
            raise ValueError("Verified CIP requires a code")
        return self


class Language(StrictModel):
    language: str = Field(min_length=1)
    proficiency: Literal["native", "near_native", "advanced", "intermediate", "basic"]
    verification: Verification = Verification.UNKNOWN


class Claim(StrictModel):
    claim_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    text: str = Field(min_length=1)
    category: Literal["skill", "education", "experience", "project", "volunteer"]
    verification: Verification = Verification.UNKNOWN
    source: str | None = None
    verified_by: str | None = None
    verified_on: date | None = None

    @model_validator(mode="after")
    def evidence_for_verified(self):
        if self.verification == Verification.VERIFIED and not (
            self.source and self.verified_by and self.verified_on
        ):
            raise ValueError("Verified claims require source, reviewer and verification date")
        return self


class Preferences(StrictModel):
    country: Literal["United States"] = "United States"
    relocation_allowed: bool = True
    preferred_work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=lambda: ["remote", "hybrid"]
    )
    minimum_monthly_usd_remote: int | None = Field(default=None, ge=0)
    minimum_monthly_usd_onsite: int | None = Field(default=None, ge=0)
    available_start_date: date | None = None


class WorkAuthorization(StrictModel):
    current_status: str | None = None
    post_completion_opt: Verification = Verification.UNKNOWN
    stem_opt_extension: Verification = Verification.UNKNOWN
    dso_verified: bool = False
    sponsorship_answer: str | None = None
    work_authorization_answer: str | None = None
    answers_verified: bool = False

    @model_validator(mode="after")
    def verified_answers_present(self):
        if self.answers_verified and not (
            self.dso_verified and self.sponsorship_answer and self.work_authorization_answer
        ):
            raise ValueError("Verified answers require DSO confirmation and both answers")
        return self


class CandidateProfile(StrictModel):
    schema_version: Literal[1] = 1
    candidate_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    name: str = Field(min_length=1)
    email: str | None = None
    application_email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    identity_verified: bool = False
    education: Education
    languages: list[Language]
    claims: list[Claim] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)

    @model_validator(mode="after")
    def unique_claims_and_contact(self):
        ids = [c.claim_id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("Claim IDs must be unique")
        for email in (self.email, self.application_email):
            if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise ValueError("Invalid email format")
        return self

    @property
    def verified_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.verification == Verification.VERIFIED]

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate(load_yaml(path))
