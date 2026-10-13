"""Reusable employer/role rules: no per-application approval when all facts are known.

Rules are supplied by the user in trusted local configuration, never by job text or AI.
Unknown checks remain unverified. An empty rule set cannot authorize real submissions.
"""

from datetime import UTC, datetime

from career_agent.applications.policy import REQUIRED_CHECKS, FormSpec, Gate, Review, digest


def from_rule(profile, posting, manifest, rule):
    if rule.get("company_domain") != posting.company_domain:
        raise ValueError("Employer rule mismatch")
    spec = FormSpec.model_validate(
        {
            **rule["form"],
            "url": posting.source_url,
            "provider": posting.provider,
            "post_url": rule["post_url_template"].format(external_id=posting.external_id),
        }
    )
    proofs = rule.get("verified_checks", {})
    gates = {}
    for key in REQUIRED_CHECKS | {"cip_stem_list", "everify", "i983"}:
        proof = proofs.get(key, {})
        verified = isinstance(proof, dict) and proof.get("status") == "VERIFIED"
        evidence = proof.get("evidence", "") if isinstance(proof, dict) else ""
        gates[key] = Gate(verified=bool(verified and evidence), evidence=evidence)
    text = posting.description.casefold()
    terms = rule.get("degree_duty_terms", [])
    titles = rule.get("allowed_title_fragments", [])
    degree_confirmed = any(
        c.category == "education"
        and profile.education.major.casefold() in c.text.casefold()
        and profile.education.degree.casefold() in c.text.casefold()
        for c in profile.verified_claims
    )
    gates["degree_related_duties"] = Gate(
        verified=bool(
            terms
            and degree_confirmed
            and all(t.casefold() in text for t in terms)
            and any(t.casefold() in posting.title.casefold() for t in titles)
        ),
        evidence=posting.source_url if terms else "",
    )
    current = posting.current_at(datetime.now(UTC), 24)
    gates["current_posting"] = Gate(verified=current, evidence=posting.source_api_url)
    gates["identity"] = Gate(verified=profile.identity_verified, evidence="verified profile")
    gates["visa_answers"] = Gate(
        verified=profile.work_authorization.answers_verified
        and profile.work_authorization.dso_verified,
        evidence="stored DSO-confirmed answers",
    )
    gates["documents"] = Gate(verified=bool(manifest.get("claim_ids")), evidence=digest(manifest))
    # Timing is established only through an employer-sourced window, never graduation guessing.
    window = rule.get("verified_start_window")
    available = profile.preferences.available_start_date
    if window and available:
        from datetime import date

        gates["start_date"] = Gate(
            verified=date.fromisoformat(window["earliest"])
            <= available
            <= date.fromisoformat(window["latest"]),
            evidence=window.get("evidence", ""),
        )
    return spec, Review(
        reviewer="trusted-policy:" + rule["rule_id"],
        reviewed_at=datetime.now(UTC),
        profile_hash=digest(profile.model_dump(mode="json")),
        job_hash=digest(posting.model_dump(mode="json")),
        document_hash=digest(manifest),
        schema_hash=digest(spec.model_dump(mode="json")),
        checks=gates,
    )
