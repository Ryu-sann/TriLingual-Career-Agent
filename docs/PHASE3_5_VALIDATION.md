# Phases 3–5 validation

Validated in this cloud instance on 2026-10-13.

Final native run: 112 tests passed, 0 skipped; Ruff and wheel/source builds passed.

Phase 3: fictional verified profiles generated versioned resume/cover-letter DOCX/PDF files;
PDF/DOCX claim extraction, hashes, immutable versions, unknown claim rejection and structured
AI selection allowlists were tested. No live OpenAI call or personal verified resume is claimed.

Phase 4: real Chromium submitted an owned loopback fixture, captured confirmation, and
blocked duplicates. CAPTCHA/unknown fields held without POST; dry-run prefills never posted;
ambiguous outcomes stayed UNKNOWN and never retried. Caps, stale evidence, artifact tampering,
kill switch, fixture/public separation and answer constraints were tested. No real ATS sent.

Phase 5: offline REST fixtures exercised token refresh, Gmail pagination/dedup/account binding,
calendar confirmed-time checks, normalized timezones, stable event-ID reconciliation and
wrong-account rejection. Ciphertext/0600 storage, explicit profile review/revocation,
worker document reuse, scheduler defaults, dashboard pages and confirmed email reconciliation
were tested. Gmail sending is absent. Live OAuth, Brave and OpenAI remain unconfigured.

Public data: 1,224 real jobs from three APIs remain stored; worker --once completed refresh,
evaluated them, generated 0 personal documents and attempted 0 applications because candidate
verification is missing. This is an expected hold, not a successful live application workflow.

Docker: image built with TLS/APT signatures/uv hashes enabled; a non-root container served
health/HTML, ran the foundation dry-run and Chromium fixture successfully. Private inputs and
credentials were excluded from explicit image COPY instructions. Cloud builder proxy/DNS/CA
requirements are captured in scripts/build_cloud_image.py. No cloud environment publication
or fresh-task snapshot restoration is claimed. GitHub Actions execution is not claimed.

Emergency stop is checked again immediately before a real submission; the private flag
stops browser work even if cached settings were loaded earlier. Known non-US and explicit
USD salary conflicts cannot be overridden by scores or review flags.
