import re
from typing import Literal

from pydantic import Field

from career_agent.core.config import StrictModel


class Question(StrictModel):
    label: str
    kind: Literal[
        "identity",
        "technical",
        "motivation",
        "work_authorization",
        "sponsorship",
        "salary",
        "demographic",
        "legal",
        "unknown",
    ] = "unknown"
    field: str | None = None
    required: bool = True


class Answer(StrictModel):
    status: Literal["VERIFIED", "DRAFT", "HOLD", "OMIT"]
    value: str | None = None
    reason: str
    claim_ids: list[str] = Field(default_factory=list)


def answer_question(question: Question, profile):
    # Legal/authorization terms override a mislabeled field or malicious site instructions.
    text = question.label.casefold()
    if re.search(
        r"signature|certif|consent|agree|attest|legal|sponsor|authoriz|visa|citizen", text
    ):
        if question.kind not in {"work_authorization", "sponsorship"}:
            return Answer(
                status="HOLD", reason="Legal, immigration or consent question requires review"
            )
    if question.kind in {"legal", "unknown"}:
        return Answer(status="HOLD", reason="Unknown or legal question requires review")
    if question.kind == "demographic":
        return Answer(
            status="HOLD" if question.required else "OMIT", reason="No demographic answer inferred"
        )
    if question.kind in {"work_authorization", "sponsorship"}:
        auth = profile.work_authorization
        value = (
            auth.sponsorship_answer
            if question.kind == "sponsorship"
            else auth.work_authorization_answer
        )
        if not auth.answers_verified or not auth.dso_verified or not value:
            return Answer(status="HOLD", reason="DSO-confirmed answer missing")
        return Answer(status="VERIFIED", value=value, reason="Stored confirmed answer")
    if question.kind == "identity":
        fields = {
            "name": profile.name,
            "email": profile.application_email or profile.email,
            "phone": profile.phone,
            "location": profile.location,
        }
        value = fields.get(question.field)
        if not profile.identity_verified or not value:
            return Answer(status="HOLD", reason="Verified identity field missing")
        return Answer(status="VERIFIED", value=value, reason="Verified profile field")
    if question.kind == "technical":
        claims = profile.verified_claims
        if not claims:
            return Answer(status="HOLD", reason="Verified technical claims missing")
        return Answer(
            status="DRAFT",
            value="\n".join(c.text for c in claims if c.category == "skill"),
            claim_ids=[c.claim_id for c in claims if c.category == "skill"],
            reason="Claim-backed draft requires question-specific review",
        )
    return Answer(status="HOLD", reason="Salary/motivation answer requires specific review")
