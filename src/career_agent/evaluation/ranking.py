import re
from datetime import UTC, datetime

from career_agent.models.evaluation import Component, EligibilityCheck, Evaluation, Evidence

PHYSICS_TERMS = [
    "physics",
    "photonics",
    "optics",
    "semiconductor",
    "spectroscopy",
    "electromagnetic",
    "experimental",
    "scientific instrumentation",
]
TECHNICAL_TERMS = [
    "test engineer",
    "validation engineer",
    "data analysis",
    "data analyst",
    "research",
    "measurement",
    "simulation",
    "laboratory",
    "numerical",
]
SKILLS = {
    "python": r"\bpython\b",
    "excel": r"\bexcel\b",
    "data analysis": r"\bdata analys(?:is|es)\b",
    "laboratory": r"\b(?:lab|laboratory)\b",
    "optics": r"\boptics\b",
    "mathematics": r"\bmathematics\b",
    "linear algebra": r"\blinear algebra\b",
}
LANGUAGES = {
    "Japanese": ["japanese", "日本語"],
    "English": ["english", "英語"],
    "Mandarin Chinese": ["mandarin", "chinese", "中国語", "中文"],
}
US_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|"
    "MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
US_CITIES = [
    "san francisco",
    "new york",
    "seattle",
    "austin",
    "foster city",
    "san mateo",
    "sunnyvale",
    "los angeles",
    "boston",
    "washington, dc",
    "mountain view",
    "palo alto",
    "san diego",
    "redwood city",
    "san jose",
    "chicago",
    "pittsburgh",
]
NON_US = [
    "canada",
    "toronto",
    "vancouver",
    "london",
    "united kingdom",
    "germany",
    "berlin",
    "france",
    "paris",
    "japan",
    "tokyo",
    "china",
    "beijing",
    "singapore",
    "india",
    "australia",
    "sydney",
    "ireland",
    "dublin",
    "switzerland",
    "zurich",
]


def sentences(text):
    return [s.strip() for s in re.split(r"\n|(?<=[.!?])\s+", text) if s.strip()]


def evidence(job, lines, interpretation):
    return [
        Evidence(source_url=job.source_url, excerpt=line[:500], interpretation=interpretation)
        for line in lines[:3]
    ]


def us_location(job):
    if job.country in {"US", "USA", "United States", "United States of America"}:
        return "VERIFIED", "Structured job-board address identifies the United States"
    locations = job.location.casefold()
    us = False
    for segment in job.location.split(";"):
        lower = segment.casefold()
        foreign = any(country in lower for country in NON_US)
        explicit_us = bool(re.search(r"\bunited states\b|\bu\.?s\.?a?\b", lower))
        state = re.search(r",\s*(" + US_STATES + r")\b", segment)
        state_us = bool(state) and (not foreign or state.group(1) not in {"CA", "IN"})
        city_us = any(city in lower for city in US_CITIES) and not job.country and not foreign
        us = us or explicit_us or state_us or city_us
    non_us = any(country in locations for country in NON_US)
    if us:
        return "VERIFIED", "Listed location includes a US location; exact site needs review"
    if non_us or (job.country and job.country not in {"US", "USA"}):
        return "REJECTED", "Only non-US locations were identified"
    return "UNKNOWN", "Remote/global or ambiguous location is not proof of US-based work"


def language_roles(job, profile):
    roles, lines = {}, []
    for language in profile.languages:
        aliases = LANGUAGES.get(language.language, [language.language.casefold()])
        matching = [
            s
            for s in sentences(job.description)
            if any(
                re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", s.casefold())
                for alias in aliases
            )
        ]
        role = "NONE"
        for line in matching:
            lower = line.casefold()
            if re.search(r"not required|not necessary|no .{0,40}required|do not require", lower):
                candidate = "MENTION_ONLY"
            elif re.search(r"\b(required|must|fluen\w*|proficien\w*)\b", lower):
                candidate = "REQUIRED"
            elif re.search(r"\b(preferred|plus|advantage|bonus)\b", lower):
                candidate = "PREFERRED"
            elif re.search(r"\b(customer|collaborat\w*|support|document\w*|team)\b", lower):
                candidate = "USEFUL"
            else:
                candidate = "MENTION_ONLY"
            order = ["NONE", "MENTION_ONLY", "USEFUL", "PREFERRED", "REQUIRED"]
            if order.index(candidate) > order.index(role):
                role = candidate
            lines.append(line)
        roles[language.language] = role
    return roles, lines


def evaluate(job, profile, settings, *, moment=None):
    moment = moment or datetime.now(UTC)
    weights = settings.matching.weights.model_dump()
    text = job.description.casefold()
    duties = sentences(job.description)
    relevant = [
        s
        for s in duties
        if any(re.search(r"\b" + re.escape(t) + r"\b", s.casefold()) for t in PHYSICS_TERMS)
        and re.search(
            r"\b(design|develop|analy\w*|test\w*|perform|measure|simulate|research|"
            r"validate|characteriz\w*|model|build|calibrat\w*|operate)\b",
            s,
            re.I,
        )
        and not re.search(r"not required|not necessary|no .{0,40}required", s, re.I)
    ]
    technical = [s for s in duties if any(t in s.casefold() for t in TECHNICAL_TERMS)]
    # Title alone does not establish directly degree-related duties.
    stem_ratio = 0.8 if relevant else 0.4 if technical else 0
    roles, language_lines = language_roles(job, profile)
    values = {"REQUIRED": 1.0, "PREFERRED": 0.8, "USEFUL": 0.5, "MENTION_ONLY": 0, "NONE": 0}
    # English alone is common in US roles; additional languages drive the advantage signal.
    advantages = [values[role] for language, role in roles.items() if language != "English"]
    language_ratio = min(1.0, sum(advantages) / 2)
    required_skills = [s for s, pattern in SKILLS.items() if re.search(pattern, text)]
    matches, claim_ids = [], set()
    for skill in required_skills:
        for claim in profile.verified_claims:
            if re.search(SKILLS[skill], claim.text.casefold()):
                matches.append(skill)
                claim_ids.add(claim.claim_id)
                break
    skills_ratio = len(matches) / len(required_skills) if required_skills else 0
    graduation_year = profile.education.graduation_month[:4]
    cohort = [
        s
        for s in duties
        if graduation_year in s and re.search(r"graduate|graduation|class of", s, re.I)
    ]
    timing_ratio = 0.5 if cohort else 0
    location_status, location_reason = us_location(job)
    work_ratio = {"remote": 1, "hybrid": 0.8, "onsite": 0.4, "unknown": 0.2}[job.work_mode]
    if location_status != "VERIFIED":
        work_ratio = 0
    components = {
        "stem_relevance": Component(
            points=weights["stem_relevance"] * stem_ratio,
            maximum=weights["stem_relevance"],
            reason="Keyword evidence is a preliminary signal; "
            "direct degree relevance requires review",
            evidence=evidence(
                job,
                relevant or technical,
                "Potential technical/physics duties; not a legal eligibility conclusion",
            ),
        ),
        "multilingual_value": Component(
            points=weights["multilingual_value"] * language_ratio,
            maximum=weights["multilingual_value"],
            reason="Job language role signals; candidate language levels remain as reported",
            evidence=evidence(
                job,
                language_lines,
                "Required, preferred, useful and incidental language mentions are distinguished",
            ),
        ),
        "skills_match": Component(
            points=weights["skills_match"] * skills_ratio,
            maximum=weights["skills_match"],
            reason="Only VERIFIED claims count: " + (", ".join(matches) or "no verified matches"),
            claim_ids=sorted(claim_ids),
            evidence=evidence(
                job,
                [s for s in duties if any(re.search(SKILLS[k], s, re.I) for k in required_skills)],
                "Skill terms in posting",
            ),
        ),
        "graduation_timing": Component(
            points=weights["graduation_timing"] * timing_ratio,
            maximum=weights["graduation_timing"],
            reason="Cohort signal only; exact start date "
            "and employer flexibility require confirmation",
            evidence=evidence(job, cohort, "Graduation year match does not confirm a start date"),
        ),
        "work_arrangement": Component(
            points=weights["work_arrangement"] * work_ratio,
            maximum=weights["work_arrangement"],
            reason=location_reason,
            evidence=evidence(
                job, [job.location], "Listed location/work mode, not remote supervision"
            ),
        ),
    }
    current = job.current_at(moment, settings.discovery.freshness_hours)
    checks = {
        "current_posting": EligibilityCheck(
            status="VERIFIED" if current else "REJECTED",
            reason="Seen in a complete public board snapshot within freshness window"
            if current
            else "Posting is delisted or the saved snapshot needs refresh",
        ),
        "us_location": EligibilityCheck(
            status=location_status,
            reason=location_reason,
            evidence=evidence(job, [job.location], "Location evidence"),
        ),
        "degree_related_duties": EligibilityCheck(
            reason="Human review of duties and Physics degree relationship is required",
            evidence=components["stem_relevance"].evidence,
        ),
        "cip": EligibilityCheck(
            status="VERIFIED"
            if profile.education.cip_verification.value == "VERIFIED"
            else "UNKNOWN",
            reason="Candidate CIP verification status; code alone "
            "does not establish STEM-list membership or job eligibility",
        ),
        "everify": EligibilityCheck(
            reason="Employer membership not independently verified",
            evidence=evidence(
                job,
                [s for s in duties if "e-verify" in s.casefold()],
                "Posting statement needs verification",
            ),
        ),
        "i983": EligibilityCheck(
            reason="Employer I-983 training-plan feasibility not confirmed",
            evidence=evidence(
                job,
                [s for s in duties if "i-983" in s.casefold()],
                "Posting statement needs employer confirmation",
            ),
        ),
        "remote_supervision": EligibilityCheck(
            reason="US-based work and supervision/training must be confirmed"
            if job.work_mode in {"remote", "hybrid"}
            else "Worksite and training supervision must be confirmed"
        ),
        "work_authorization_answers": EligibilityCheck(
            status="VERIFIED" if profile.work_authorization.answers_verified else "UNKNOWN",
            reason="Candidate's stored answer verification state; no answer is invented",
        ),
        "start_date": EligibilityCheck(reason="Exact start date and employer timing not confirmed"),
        "employer_identity": EligibilityCheck(
            reason="Watchlist mapping is configured, "
            "not an independent employer identity verification"
        ),
    }
    blocks = []
    if not current:
        blocks.append("posting_not_current")
    if location_status == "REJECTED":
        blocks.append("outside_us")
    warnings = []
    if re.search(r"citizen|citizenship|security clearance|u\.?s\.? person", text):
        warnings.append("citizenship_or_export_control_requires_review")
    if re.search(r"senior|staff|principal|director|manager", job.title, re.I):
        warnings.append("seniority_requires_review")
    score = round(sum(c.points for c in components.values()))
    unresolved = [key for key, check in checks.items() if check.status == "UNKNOWN"]
    decision = (
        "REJECTED"
        if blocks
        else "HOLD"
        if score >= settings.matching.minimum_review_score
        else "LOW_PRIORITY"
    )
    return Evaluation(
        score=score,
        components=components,
        language_roles=roles,
        checks=checks,
        decision=decision,
        hard_blocks=blocks,
        unresolved=unresolved,
        warnings=warnings,
    )
