# TriLingual Career Agent

Phase 1: Python 3.12+ foundation for an evidence-based US technical job-search agent.
Japanese, English and Mandarin capability and physics-degree relevance drive future matching.
**Live applications are disabled.** This phase runs offline and submits nothing.

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
strict validated configuration, redacted diagnostics, CI and tests. Later phases implement
state transitions, scoring, document generation, submission policy and API integrations.

Use one reviewed commit/PR per phase. Run tests before committing. CI runs on GitHub pushes
and pull requests; local test success alone does not establish a GitHub CI result.
