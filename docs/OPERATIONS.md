# Activation and reusable configuration

The code supports all five build phases. The instance currently has no live application
permission, verified personal claims/DSO answers, or external service credentials.
This is an implementation and validation milestone; full autonomous real-account operation
still requires those external prerequisites. No case-by-case approval is needed once a
trusted reusable employer rule matches and every required check is verified; otherwise hold.

1. Work from this existing checkout. Do not create worktrees for cloud tasks unless requested.
2. Export UV_CACHE_DIR=/workspace/.cache/uv; run uv sync --locked and career-agent init-db.
3. Start the local dashboard with the README command. Choose the private profile and verify
   only facts you have actually reviewed. Do not mark legal or employer criteria confirmed
   based on job-title keywords or uploaded speculative statements.
4. Supply OpenAI/Brave credentials only if those optional modes are enabled. OpenAI uses
   CAREER_OPENAI_API_KEY because the platform reserves OPENAI_ variable names. Choose a model
   available to your account via CAREER_OPENAI_MODEL; no unsupported model is assumed.
5. Set Google OAuth credentials/refresh token in secure environment settings, with
   gmail.readonly and calendar.events.owned scopes. Enable email polling only after account
   and access validation. Calendar writes require confirmed invitation times.
6. Configure site-specific FormSpec/contracts and employer verification records under
   trusted config/application_policy.yaml; default authorized_routes and employer_rules are
   empty. verified_checks entries use {status: VERIFIED, evidence: <actual source>}.
   UNKNOWN strings/objects never become verification. Rules include role/duty conditions,
   an employer-sourced start window, permitted route evidence and all required checks.
   LinkedIn, Indeed and other aggregator submission paths are forbidden. Complex/changed
   forms pause rather than guessing selectors, answers or permissions.
7. Run each permitted route in dry-run/test fixtures first. Real execution additionally
   needs enabled=true, dry_run=false, kill_switch=false, minimum score 80, matching evidence
   hashes and intact documents. Resume/email/template defaults alone do not authorize a send.
8. Start one worker. It reads current settings on each cycle; caps/uniqueness are locked in DB
   before a click. SUBMITTING/UNKNOWN_SUBMISSION remain blocked until evidence reconciliation.
9. Review stored errors, holds, interview candidates and private daily summary in the UI.

Network destinations for public discovery: boards-api.greenhouse.io, api.lever.co,
api.ashbyhq.com. Optional integrations: api.openai.com, api.search.brave.com,
oauth2.googleapis.com, gmail.googleapis.com and www.googleapis.com. Each approved browser
route/resource needs its own environment network access. Use the existing proxy and trusted
CA; do not bypass TLS, CAPTCHA, MFA or access restrictions. Browser route permission and
network access are different requirements.

Docker build was validated using the cloud proxy/CA helper. Runtime containers need proxy
and CA propagation when used in this cloud network; local workstation networking differs.
The example compose deliberately starts no Google writes or approved submission route.
Secrets are environment bindings or encrypted local vault data, not image contents.

Retained files: repo, .venv, ignored data/profile/, career.db, document/evidence outputs and
scheduler.db. Processes must restart after snapshot restoration. GitHub does not restore
private inputs; keep a secure backup. Review/save/publish in environment settings activates
saved snapshots; a draft save and a Git push do not themselves publish the cloud environment.
