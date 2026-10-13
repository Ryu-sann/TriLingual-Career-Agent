# Phase 2 validation

Validated in this cloud instance on 2026-10-13 with Python 3.12.14 and uv 0.12.23.

- Locked dependency installation, Ruff lint and package wheel/source builds succeeded.
- 84 tests passed, 0 skipped, including PostgreSQL foundation and discovery tests.
- Public API discovery completed successfully for all configured boards:
  - Astranis / Greenhouse: 180 postings.
  - Zoox / Lever: 236 postings, fetched with skip/limit pagination.
  - OpenAI / Ashby: 808 listed postings.
  - Total: 1,224 observed and evaluated postings, 0 API errors, 0 applications submitted.
- Discovery was repeated: the database retained 1,224 unique jobs rather than duplicating them.
- Streamlit AppTest rendered 1,060 current US/unknown-location records by default, including
  source URLs from all three providers. A physics search returned 59 records. Other records
  were excluded from the default view by the non-US/delisted filter; they remain stored.
- The local Streamlit HTTP health route returned ok and the HTML bootstrap was served.
- Offline tests verified pagination completeness/repetition, bounded rate-limit retries,
  blocked redirects/SSRF destinations, HTML/script removal, actual ampersand-title regression,
  malformed feeds, inactive Ashby rows, URL/identity deduplication, cross-board review flags,
  failed-source snapshot preservation, stale/delisted rejection, verified-claim-only skills,
  language roles/negation, evidence references, search filtering and malformed search quotes.
- High-scoring fixture jobs remained HOLD with separate UNKNOWN OPT and STEM OPT statuses;
  posting text claiming verification or requesting submission could not authorize anything.

Counts are observations at validation time; future refreshes can legitimately change them.
Watchlist membership is not an independent employer verification or a STEM OPT endorsement.
Candidate data was not sent to job boards. Job data, private profiles and logs remain ignored.
GitHub Actions is configured for these offline/DB/UI tests; this file does not claim a hosted
Actions result. No resume generation or application execution is included in Phase 2.

Company-site search: exact site:/quoted-title/Remote queries and search links verified;
automated Brave search tested offline with employer-domain-only result filtering.
