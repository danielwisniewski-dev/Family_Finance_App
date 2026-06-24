# AGENTS.md

## Purpose

This is a private household finance Android app for Daniel and Kara.

The backend is the source of truth for money, budget, account, transaction, and safe-to-spend logic. Android must not fake financial state. Coach/AI features are advisory only and must not mutate budget data without explicit user action.

For broader product direction, read `docs/project-plan.md`.

## Repository Layout

- `backend/` — Python backend, domain logic, SQLite persistence, API routes, tests
- `backend/app/` — backend application code
- `backend/tests/` — backend unit/integration tests
- `android/` — native Android app
- `docs/` — project planning and design notes
- `work/` — local demo/runtime files; do not commit

## Core Budget Rules

Use EveryDollar/Dave Ramsey-style monthly planning.

Safe-to-spend must use both:

1. budget category remaining
2. real cash/account position after upcoming bills before next payday

Safe-to-spend responses must include:

“After upcoming bills, you would have about $___ left for ___ days until payday.”

## Current Scope Rules

Do not add unless the current milestone explicitly asks for it:

- production Plaid
- credit cards
- receipt scanning
- MCP/tool layer
- Firebase/cloud push
- production auth provider
- public signup/password reset/OAuth
- autonomous coach budget changes
- full visual redesign

Plaid is Sandbox-only until explicitly changed.

## Security Rules

Never expose in API or Android responses:

- Plaid access tokens
- Plaid token references
- OpenAI API keys
- password hashes
- session token hashes
- provider internals
- `.env` contents

Never commit:

- `.env`
- real credentials
- local SQLite databases
- token files
- logs
- `.venv`
- `__pycache__`
- `.pytest_cache`
- Android build output
- `.idea`
- generated junk files

## Category and Transaction Rules

Archived categories must preserve history but cannot be used for new:

- categorization
- manual spending
- split lines
- merchant rules
- safe-to-spend requests

Ignored transactions must not affect budget totals.

Split transactions must not double-count the parent transaction.

Merchant rules must not make surprising bulk edits unless explicitly requested.

## Commands

Backend tests:

```bash
python -m unittest discover -s backend\tests
```

Windows launcher alternative:

```bash
py -m unittest discover -s backend\tests
```

Android tests/build:

```bash
cd android
.\gradlew.bat testDebugUnitTest
.\gradlew.bat assembleDebug
```

If `python` or `py` is unavailable in the Codex sandbox, use the working local Python runtime path or bundled Codex runtime. Do not modify project files only to fix sandbox PATH.

## Testing Policy

Daniel often works remotely from mobile and may not have access to his PC. Therefore, Codex should run final verification by default unless Daniel explicitly says not to.

During implementation:

* Run targeted tests for the changed feature area.
* Do not repeatedly run the full backend suite unless broad shared logic changed.
* Do not repeatedly run Android `assembleDebug` unless Android/build files changed.
* After a failed test, rerun the failed or related test first.
* Rerun the full suite only after targeted tests pass.

Before commit approval, run final verification once by default:

* full backend test suite
* Android unit tests
* Android `assembleDebug`
* practical smoke test for the milestone’s main user flow, when feasible
* `git status`
* `git diff --stat`
* `git diff --check`
* secret/junk scan

If final verification fails:

* fix the issue
* rerun targeted tests first
* rerun full final verification once after targeted tests pass

Avoid multiple full verification loops unless the milestone touches:

* auth/security
* Plaid/token handling
* safe-to-spend math
* cross-household access
* transaction double-counting
* production-readiness changes

## Git Workflow

Use one branch per milestone.

Do not commit until Daniel approves.

Open a PR against `main`.

Do not merge the PR unless Daniel explicitly approves.

## Reporting Style

Keep summaries concise.

Prefer this final format:

* changed files
* tests run
* failures/fixes
* smoke result
* secret/junk result
* commit readiness
