# TriLingual Career Agent

Phases 1–5: public discovery, company-site search, verified documents, guarded forms and scheduled operations.
Japanese, English and Mandarin capability and physics-degree relevance drive future matching.
**Live applications are disabled.** The foundation dry-run is offline; discovery only reads public jobs. No submissions occur.

## Quick start

From this checkout, with Python 3.12+ and uv:

```sh
uv sync --locked
uv run career-agent validate-profile
uv run career-agent init-db
uv run career-agent dry-run
uv run ruff check .
uv run pytest
```

In this cloud environment the default home cache is read-only. Before running uv, use:

```sh
export UV_CACHE_DIR=/workspace/.cache/uv
```

The default local database is ignored `data/career.db` (SQLite). Alembic applies versioned
migrations; `init-db` is repeatable. `dry-run` validates settings/profile, upserts the profile
and claims, and records a completed workflow and audit log in a single transaction. It prints
only readiness counts and unresolved checks, never contact details or profile content.
No jobs, scores or successful submissions are fabricated. A successful dry-run means the
foundation works, not that the candidate is eligible to work or ready for live applications.

## PostgreSQL

```sh
docker compose up -d --wait postgres
export CAREER_DATABASE_URL='postgresql+psycopg://career@127.0.0.1:5432/career'
uv run career-agent init-db
uv run career-agent dry-run
CAREER_TEST_DATABASE_URL="$CAREER_DATABASE_URL" uv run pytest tests/integration/test_postgres.py
```

Use a dedicated test database: the PostgreSQL test creates and removes its own test schema.
The Compose database permits unauthenticated **local development only** on loopback.
Deployment will require authenticated access and TLS; it is not delivered in Phase 1.
`docker compose stop postgres` stops the service without deleting stored data.

## Private candidate profile

The supplied profile and resume are stored only in ignored `data/profile/`, with private
filesystem permissions. GitHub contains a fictional sample. To use the local profile:

```sh
uv run career-agent validate-profile --profile data/profile/candidate_profile.yaml
uv run career-agent dry-run --profile data/profile/candidate_profile.yaml
```

All imported skills/experience are SELF_REPORTED; generated resumes may later use only
claims explicitly marked VERIFIED with source, reviewer and verification date. DSO answers
and identity remain unverified. CIP and OPT/STEM OPT are separate fields; UNKNOWN does not
mean verified. Keep the private folder backed up securely; a Git clone does not restore it.
The local DB contains personal data after this command; it is ignored and must be protected.
Tokens and secrets are not needed for Phase 1. `.env` is an example only; export variables in
the shell. Do not put database credentials in command-line arguments or committed files.

## Phase boundaries and GitHub

See [the implementation plan](docs/IMPLEMENTATION_PLAN.md). Phase 1 includes 12 foundational
SQLAlchemy tables, foreign keys, unique constraints, profile import/upsert, Alembic migration,
strict validated configuration, redacted diagnostics, CI and tests. Phase 2 adds discovery and scoring. Later phases implement
state transitions, document generation, submission policy and email/calendar integrations.

Use one reviewed commit/PR per phase. Run tests before committing. CI runs on GitHub pushes
and pull requests; local test success alone does not establish a GitHub CI result.

## Phase 2 — Public job discovery and scoring

Greenhouse, Lever and Ashby public **GET** feeds are supported. The default employer watchlist
contains Astranis, Zoox and OpenAI. This is a configurable starting set, not a search of every
US employer or a confirmation of E-Verify membership. Edit `config/company_watchlist.yaml`
to add known board IDs and employer domains. Candidate data is never sent to job-board APIs.

```sh
export UV_CACHE_DIR=/workspace/.cache/uv # Needed in this cloud environment
uv sync --locked
uv run career-agent discover --profile data/profile/candidate_profile.yaml
uv run career-agent list-jobs --profile data/profile/candidate_profile.yaml --query physics --limit 10
uv run streamlit run src/career_agent/dashboard/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false
```

Omit `--profile` to use the fictional sample if private inputs are absent. PostgreSQL uses
the same commands with `CAREER_DATABASE_URL` exported as above. Run from this checkout.
The dashboard can switch between sample/local private profiles and displays source links,
score components, quoted evidence, language roles, unresolved eligibility, provider-supplied
salary metadata, freshness and run errors. Search accepts multiple terms (all must match)
and quoted phrases. Saved searches come from `config/job_keywords.yaml`.

Required outbound HTTPS hosts: `boards-api.greenhouse.io`, `api.lever.co`,
`api.ashbyhq.com`. Keep TLS verification enabled. No API keys or OpenAI/OAuth setup is needed.
Network denial is a failed/partial run, never a successful zero-job discovery. Exit codes:
0 complete, 3 partial (some boards failed), 2 failed. Safe error codes are in the run summary;
response bodies, candidate details and database credentials are excluded from diagnostics.

Lever uses documented `skip`/`limit` pagination; the other two providers return full feeds.
Requests are rate-limited, transient 429/502/503/504 responses receive bounded backoff, and
redirects are rejected. Partial pagination or malformed data never closes saved postings.
A valid complete empty board does mark that board's missing postings delisted. Multiple
observed source aliases are preserved; identical source URLs/identities deduplicate, while
possible same-company/title/location duplicates across providers are held for review.
Repeated discovery preserves jobs and appends evaluation/workflow history.

The 100-point score uses configured weights: physics/STEM 30, language advantage 25,
verified skills 20, graduation timing 15, work arrangement 10. Rules provide **preliminary
signals**, not AI judgment or immigration advice. Only verified candidate claims contribute
skill points; self-reported language levels remain identified as such. Titles alone never
prove degree-related duties. Missing information lowers evidence/points rather than being
invented. Salary fields retain the provider's original units; no automatic annual conversion
or candidate salary answers are generated.

Post-completion OPT and STEM OPT statuses remain separately UNKNOWN in this phase. Degree
relationship, employer identity, E-Verify, I-983, supervision, exact start date and other
hard checks require confirmation. A high score is still HOLD; old/non-US/delisted postings
are blocked regardless of score. Readiness is recomputed using observation timestamps
(default 24-hour freshness), not an indefinitely cached score. No resumes, emails, browser
submissions or live application controls are implemented in Phase 2.

Validation: `uv run ruff check .`, `uv run pytest` and `uv build`. Set
`CAREER_TEST_DATABASE_URL` to run both PostgreSQL checks. Tests use fictional offline feeds
and Streamlit AppTest; live API results are checked separately and stored only under ignored
`data/`. See [Phase 2 validation](docs/PHASE2_VALIDATION.md).

### Company-site search

`uv run career-agent site-search --job-title 'Photonics Engineer'` produces
`site:company-careers-site ("Photonics Engineer" AND "Remote")` queries and search links.
The dashboard provides these alongside official careers pages. LinkedIn and aggregators
are not application routes. Optional `--automated-search` uses Brave Web Search with
`CAREER_BRAVE_API_KEY`; only employer-domain results survive filtering, and all remain
unverified leads until an actual employer posting is checked. No search-engine scraping
or access-control bypass is used.

## Phase 3 — Verified documents and answers

`uv run career-agent documents --job-id <id-from-list-jobs> --profile <private-profile.yaml>`
creates versioned resume and cover-letter DOCX/PDF files plus SHA-256 manifests under ignored
`data/resumes/`. Identity must be confirmed and claims marked VERIFIED with source, reviewer
and date. No imported claim is automatically verified. Exact verified claim text is used;
unknown language levels, GPA, achievements and dates are not added. Both PDF extraction and
DOCX text are checked for the selected claims. Unsupported font glyphs stop generation.

Optional `--use-ai` uses OpenAI Structured Outputs to select/reorder approved claim IDs only.
Set `CAREER_OPENAI_API_KEY` and a currently available `CAREER_OPENAI_MODEL`; no model name or
credential is guessed. Unknown/generated claim IDs fail validation. LangGraph orchestrates
selection/render/validation; external tracing is disabled. OpenAI live calls have not been
validated without credentials. Offline deterministic generation requires no AI key.

Applicant answers come from verified fields and DSO-confirmed authorization answers.
Technical prose remains a draft until question-specific review. Unknown legal, consent,
immigration, salary and required demographic questions stop progression; optional
demographics are omitted. Private supplied claims currently remain SELF_REPORTED, so
personal production documents are blocked until review; fixture documents were generated
and validated successfully.

## Phase 4 — Permitted form execution

Playwright operates only on an explicitly permitted employer/ATS route and a reviewed
form contract. Field labels and required inputs are checked before any fill/upload.
CAPTCHA, login/MFA, changed labels, unknown/legal questions and unverified answers pause
execution. Dry-run freezes all networking before prefill and never enables POST.

`career-agent application --job-id <id> --resume-id <id> --form-spec <private-json>
--review <private-json> --profile <private-yaml>` defaults to dry-run. `--live` additionally
requires enabled=true, dry_run=false, kill_switch=false and the exact official route
in trusted application_policy.yaml. Defaults approve no real route. Review evidence binds
profile/job/document/form hashes; changed artifacts or stale reviews are blocked.
Reusable employer rules can construct evidence from previously verified company/role
configuration, so fully known cases need no new case-by-case approval. Unknown checks stop.

Submission reservations and caps are committed before clicking: candidate/job uniqueness,
10/day and 1/company/day, counted in the configured timezone. SQLite uses BEGIN IMMEDIATE;
PostgreSQL locks the candidate row. Answers, audit transitions and screenshots are retained
privately. A missing/ambiguous confirmation becomes UNKNOWN_SUBMISSION and is never retried.
Only owned loopback fixtures can use fixture mode; public sites cannot. Real Greenhouse,
Lever and Ashby forms require a site-specific permitted contract; no blanket claim that
every current ATS form is supported is made. LinkedIn/aggregator submission is forbidden.

Browser tests use /usr/bin/chromium when available; set CAREER_CHROMIUM_PATH for a compatible
binary or install the pinned Playwright Chromium. No production submission was performed.

## Phase 5 — Tracking and scheduled operations

The dashboard has Jobs, Documents, Applications, Email/Interviews, Analytics and Settings
views. Select the local private profile before using the one-time identity/claim/language
confirmation controls. Confirmed claims keep source, reviewer and date; unchecking a claim
withdraws verification. That action never verifies CIP/DSO answers or immigration eligibility.

```sh
uv run career-agent worker --once       # Public refresh + eligible document/application pipeline
uv run career-agent worker              # One worker, persisted scheduler
uv run career-agent sync-email          # Read-only Gmail; requires configured OAuth
uv run career-agent calendar --event data/confirmed_interview.json   # Preview only
uv run career-agent calendar --event data/confirmed_interview.json --write-calendar
```

Schedules are America/New_York: discovery at 09:00/21:00, a private summary at 22:00.
Email polling is disabled initially (15 minutes when enabled); alerts appear after a poll,
not via a real-time push service. Calendar writes and AI are disabled initially. Operations
settings are in config/operations.yaml. Optional site_search_enabled runs the requested
site:/quoted-role/Remote searches with Brave, retaining only employer-domain results as
unverified leads. Search snippets cannot authorize applications. Add employer boards to
the watchlist to normalize actual postings. This does not search all US employers by default.

Documents are cached by profile and stable job-content hashes, versioned when changed, and
limited to 25 new versions/cycle. Previously attempted/ambiguous jobs never resubmit.
A worker lock and APScheduler max_instances/coalescing prevent competing local workers.
Scheduler data is private trusted state; do not import scheduler DB files from untrusted sources.

OAuth requires CAREER_GOOGLE_CLIENT_ID, CAREER_GOOGLE_CLIENT_SECRET and
CAREER_GOOGLE_REFRESH_TOKEN. Grant only gmail.readonly and calendar.events.owned.
Configure your own desktop/web OAuth client and obtain a refresh token through Google's
authorized consent flow; keys/tokens must be entered through environment settings, never
chat or Git. Account email must match the candidate's application Gmail. Metadata/snippets
are saved locally, classified as candidates and left for review. No Gmail send operation
is implemented. Confirmed association can reconcile an ambiguous application via
workflows/tracking.py without clicking Submit again.

Calendar proposals require an observed email, explicit time/evidence and the same Google
account. Stable event IDs prevent duplicates; mismatched existing events stop reconciliation.
Use the Email/Interviews page to save confirmed time proposals; a calendar-enabled worker
can process them. Unknown dates, calendar output and email/job association are never guessed.
An optional TokenVault encrypts local tokens with Fernet; keep its 0600 key separately from
Git and ciphertext. CAREER_GOOGLE_VAULT_PATH/CAREER_GOOGLE_KEY_PATH can replace an injected
refresh token when using that local vault. Access tokens live only in memory.

## Deployment

```sh
docker build -t trilingual-career-agent:phase5 .
export CAREER_RUN_UID=$(id -u) CAREER_RUN_GID=$(id -g)
docker compose -f docker-compose.operations.yml up -d
```

Containers use a non-root identity, Chromium and DejaVu fonts. Match the data-volume UID/GID
to its owner; private data is mounted at /app/data and excluded from image copies. The
example service binds only loopback. Use your own authenticated/TLS ingress for deployment
to a shared host. The standalone PostgreSQL compose service is an alternative DB; set
CAREER_DATABASE_URL and supply proper credentials/TLS for production. The provided local
PostgreSQL trust configuration is development-only.

In this cloud instance, home caches and build DNS require supported overrides:

```sh
export DOCKER_CONFIG=/workspace/.cache/docker
python scripts/build_cloud_image.py
```

The helper forwards the existing platform proxy, resolves its host for the builder, and
mounts the supplied public CA bundle temporarily. TLS, APT signatures and uv lockfile
hashes stay enabled; no credential values or CA bundle are copied into image layers.
Future services must use the platform proxy/trust route as appropriate; snapshots do not
preserve running processes. See docs/OPERATIONS.md for required runtime setup.

Current validation covers public APIs, local browser fixtures, documents, mock OAuth/Gmail/
Calendar, UI, PostgreSQL and Docker. Real OpenAI, Brave and Google account access and real
ATS submission remain unvalidated without credentials/verified facts/permitted contracts.
Live submission remains disabled. No production application or outbound email was sent.

Emergency stop: the Settings page writes private data/emergency_stop.flag. It is checked
before browser preparation and again before clicking, alongside freshly loaded kill-switch
settings. Removing the flag alone never enables live submission. Explicit non-US and
known USD salary conflicts remain blocked independently of manual review/score. Monthly
floors are compared only when currency and published month/year units are unambiguous;
no salary answer or hourly/annual estimate is generated.

Validation milestone: 112 local tests passed, including PostgreSQL and real browser fixtures.
