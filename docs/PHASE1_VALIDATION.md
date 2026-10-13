# Phase 1 validation

Validated in the cloud workspace on 2026-10-13 using Python 3.12.14 and uv 0.12.23.

- Locked installation (`uv sync --locked`) succeeded and was repeated.
- Ruff lint passed.
- 35 pytest tests passed, 0 skipped, with PostgreSQL integration enabled.
- SQLite and PostgreSQL 17.6: all 12 application tables plus Alembic version table created;
  migrations repeated safely, matched ORM metadata, and downgraded/upgraded in tests.
- Sample and private-profile validation/dry-runs succeeded; repeated profile upsert
  kept one profile/claim set and added distinct workflow/audit records.
- Transaction rollback, foreign-key enforcement and duplicate application refusal verified.
- Invalid settings, enabled submission, malformed YAML and private error input rejected.
- Package wheel/source build succeeded.
- No jobs discovered or applications submitted. No live network job/email/AI calls.
- Private inputs, original documents and local SQLite database are Git-ignored; published
  source was checked for the imported candidate's contact details.

GitHub Actions is configured to run lint, the same tests with PostgreSQL, and a sample
smoke check on push/PR. This document records local execution, not a GitHub Actions result.

Phase 2–5 are planned in IMPLEMENTATION_PLAN.md and are not implemented in this commit.
