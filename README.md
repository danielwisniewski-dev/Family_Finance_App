# Family Finance Accountability App

The private Android beta is deployed on Render with the Stage 2 USAA/Plaid integration. PR #19 was merged and deployed on September 12, 2026; Daniel confirmed native USAA linking and matching bank data. On September 17 he reported that the app is working well. See [the Stage 2 runbook and acceptance record](docs/stage-2-usaa-plaid.md) for verified results and checks not yet individually recorded.

Stage 1 security, Render configuration, encrypted backups, migration, and signed Android build instructions remain in [docs/stage-1-private-beta.md](docs/stage-1-private-beta.md). The earlier recovery review is in [docs/overnight-review.md](docs/overnight-review.md). Local development uses Sandbox; the existing private household explicitly enabled Production Plaid under the Trial plan.

The previous interface update is Android `0.6.1-interface`, code 4. PR #20 was merged and its backend deployed September 17, preserving the household database and Plaid connection. It adds the streak/personal-best dashboard, streamlined transaction review and multi-select categorization, merchant-rule management, quieter routine notifications, and bank sync before safe-to-spend. See [interface release notes](docs/interface-tweaks.md); the latest operational evidence is in the ignored `work/interface-tweaks-handoff.md`. Phone installation has not been independently observed.

Android `0.6.2-warmth` / code 5 adds warmer colors, distinct typography, household illustrations, confirmed-action celebrations, a tappable notifications card, attention for negative category balances only, and compact budget/sync text. Daniel approved GitHub publication and signed phone delivery September 19. The signed APK is `work/releases/family-finance-0.6.2-warmth.apk`, using the original signing certificate and existing HTTPS backend. See [release notes, installation, and verification](docs/ui-warmth.md). Install it as an update over the existing app; it requires no backend deployment, data migration, or bank reconnection. Physical phone installation has not yet been verified.

Android `0.7.0-provision` / code 6 adds [provision funds](docs/provision-funds.md), [separate USAA sync controls](docs/bank-sync-controls.md), newest-first transactions, and a quieter review queue with categorized items first. Daniel authorized commit and deployment September 23. The signed update uses the original certificate and existing HTTPS backend; backend deployment and household setup are pending. Install `work/releases/family-finance-0.7.0-provision.apk` as an update after backend deployment, preserving the existing app data.

The milestone descriptions below document how the app was built. Preserve the existing hosted household/database, bank connection, and Android signing key when making changes. Broader household access remains deferred.

The implemented slices are Milestone 1, Milestone 2, Milestone 3 backend scaffolding, Milestone 4 Android MVP screens, Milestone 5A/5B backend coach scaffolding, Milestone 6 spouse accountability notifications, Milestone 7 private household access, Milestone 8 Plaid Sandbox linking/sync, Milestone 9 budget setup/monthly planning, Milestone 10 transaction review workflow and merchant rules, Milestone 11 household setup/settings, Milestone 12 MVP usability hardening/data integrity, Milestone 13 MVP release-candidate stabilization, and Milestone 14 Android visual polish/local gamification.

Milestone 1 built deterministic household budget logic that can answer safe-to-spend questions without Plaid or AI. It includes:

- Household and spouse records
- Monthly budget months
- Planned income
- Budget groups and categories
- Category planned, spent, and remaining amounts
- Expected bills before payday
- Payday schedule
- Included-account cash balance
- Manual checking/savings accounts for cash-reality inclusion rules
- Safe-to-spend calculation
- SQLite persistence
- Small JSON HTTP API
- Unit tests for core and edge-case budget behavior

Milestone 2 adds backend-only Plaid/account integration scaffolding:

- Plaid link-token and public-token exchange API scaffolding
- Backend-only Plaid item records with token references, not frontend-exposed access tokens
- Plaid account metadata attached to checking/savings cash accounts
- Account inclusion/exclusion controls for cash reality
- Balance sync and transaction sync service abstractions
- Plaid transaction deduplication by transaction ID
- Sync error capture without crashing budget reads
- Tests for account selection, transaction deduplication, and sync error handling

Milestone 3 adds backend-only transaction review and categorization:

- Transaction list, detail, and review-queue support
- Reviewed/unreviewed transaction state
- Manual category assignment, recategorization, and category removal
- Merchant-based categorization rules with deterministic priority, then id ordering
- Plaid category/name data stored as hints only
- Uncategorized queue for transactions without a final category
- Transaction splitting across multiple budget categories
- Ignored/excluded transactions that stay in history but do not affect budget spending
- Audit events for imports, category decisions, splits, review changes, and ignores
- Category spent/remaining totals that include active, non-ignored transaction assignments
- Tests for queue behavior, category totals, rules, hints, splits, ignored transactions, and audit metadata

Milestone 4 adds Android MVP screens that call the local backend API:

- Dashboard with included cash, upcoming bills, cash remaining after bills, days until payday, low cushion warning, and uncategorized count
- Monthly budget category list from backend summary data
- Category detail with assigned transactions
- Transaction list and transaction detail screens
- Uncategorized review queue
- Safe-to-spend check using backend-calculated results
- Transaction category assignment, reviewed/unreviewed, and ignore/unignore actions where supported by the backend
- Accounts/settings screen with backend URL, budget month ID, health check, and account inclusion display

Milestone 5A adds backend-first AI coach scaffolding without connecting to a real AI API:

- `POST /coach/safe-to-spend` returns the deterministic backend safe-to-spend result plus a structured coach explanation
- `POST /coach/budget-change-suggestion` returns a draft budget change proposal only
- Coach service and provider interface separate backend facts from coach wording
- `MockCoachProvider` gives deterministic responses for tests and demos
- A future `OpenAICoachProvider` placeholder exists but intentionally makes no API calls
- Coach responses include summary, recommendation, tone, warning level, facts used, tradeoffs, suggested actions, spouse discussion flag, proposed budget change, confidence, and limitations
- Tests verify the coach uses backend-calculated facts, includes the required safe-to-spend phrase, does not mutate budget/category/transaction data, and does not expose Plaid token references

Milestone 5A is intentionally backend-first. Android coach display, chatbot UI, conversation history, autonomous actions, and push notifications remain deferred.

Milestone 5B adds a production-shaped OpenAI coach provider scaffold, disabled by default:

- `MockCoachProvider` remains the default provider
- `OpenAICoachProvider` is selected only when `COACH_PROVIDER=openai`
- OpenAI receives only controlled backend fact packets
- OpenAI responses are expected as structured JSON and mapped into the existing `CoachResponse` schema
- Missing OpenAI configuration returns a clear configuration error
- Timeout or provider failure returns a sanitized fallback coach response
- Tests use fake OpenAI transports only; they make no live OpenAI network calls
- No OpenAI API key is required for tests, demo seed, or default local development

Milestone 7 adds a lean private household access layer:

- Local/demo username or email plus password login for Daniel and Kara
- PBKDF2-SHA256 password hashes stored in SQLite
- Backend-issued bearer tokens with only token hashes stored server-side
- Protected financial routes derive current user and household from the bearer token
- Notification unread/read state uses the authenticated user by default
- Android login/logout with local MVP token storage and `Authorization: Bearer ...` API calls

This is not production SaaS authentication. There is no public signup, password reset, email verification, OAuth, admin role system, or production identity-provider integration.

Milestone 8 adds Plaid Sandbox linking and sync:

- Backend-created Plaid Link tokens for authenticated users
- Android Plaid Link launch using the official Plaid Link SDK
- Backend-only public token exchange and access token handling
- Local MVP SQLite token references with backend-only raw token storage
- Checking/savings account import and balance sync
- Credit card, loan, and investment accounts ignored for MVP scope
- Transactions Sync support for added, modified, and removed transactions
- Cursor persistence for incremental transaction sync
- Removed Plaid transactions marked ignored/auditable rather than deleted
- Sanitized sync errors that do not expose Plaid or OpenAI secrets

Milestone 8 was Sandbox-only. Local development still requires `PLAID_ENV=sandbox`; Stage 2 adds explicitly enabled Production access for the private USAA connection through the hosted runtime.

Milestone 9 adds budget setup and monthly planning edits:

- Budget month list, selection, activation, and copy-forward creation
- Budget detail API with planned income, assigned/funded total, remaining-to-assign, total spent, overspent categories, groups, categories, bills, and paydays
- Category create/edit/funding/archive flows with archived categories excluded from new spending, categorization, and safe-to-spend
- Planned income add/edit/remove
- Expected bill add/edit/remove feeding cash-reality and safe-to-spend calculations
- Payday add/edit/remove feeding next-payday and days-until-payday calculations
- Accountability notification events for budget setup changes
- Android screens for budget months, category funding, income planning, and bills/paydays

Milestone 12 hardens MVP daily-use behavior:

- Consistent sanitized API error payloads with stable `error`, `message`, `code`, and `status` fields
- Authenticated `/app/diagnostics` response with read-only integrity checks
- Validation for common names, dates, password, and amount inputs
- Clear safe-to-spend errors when budget, category, or payday data is missing
- Sanitized Plaid Sandbox configuration and request failures
- Android empty/loading/error states for setup, dashboard, budget, review queue, safe-to-spend, Plaid/accounts, settings, and diagnostics

Milestone 13 stabilizes the local MVP release candidate:

- Keeps the app local/private and Plaid Sandbox-only
- Preserves merchant-rule history through archive/reactivation instead of destructive removal
- Confirms local demo seed, backend startup, Android navigation, diagnostics, transaction review, and safe-to-spend smoke paths
- Documents fresh setup, demo seed, emulator URL, Sandbox setup, smoke checks, and MVP limitations

Milestone 14 improves the Android demo experience without changing backend financial logic:

- Warmer Android visual system with styled cards, buttons, inputs, loading states, warnings, and success states
- Dashboard hierarchy focused first on cash after upcoming bills, review progress, and clear next actions
- Monthly budget category cards with simpler remaining/spent/planned summaries
- Transaction review rows with clearer status wording and progress toward clearing the queue
- Safe-to-spend request/result screens with calmer wording while preserving backend-calculated results and the required phrase
- Local-only motivational cues for budget check-in streaks, review queue progress, and queue-cleared celebration

Milestone 14 gamification is read-only/local Android UI state. It does not mutate backend budget, account, transaction, category, notification, Plaid, or safe-to-spend data.

Environment variables:

- `PLAID_CLIENT_ID`
- `PLAID_SECRET`
- `PLAID_ENV=sandbox`
- `PLAID_PRODUCTS=transactions`
- `PLAID_COUNTRY_CODES=US`
- `PLAID_REDIRECT_URI`
- `COACH_PROVIDER`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_TIMEOUT_SECONDS`

Do not commit `.env` files, real Plaid credentials, or real OpenAI API keys.

Do not commit real passwords. The demo credentials below are local-only values for the seeded SQLite demo database.

## Database Schema Assumption

Stage 1 adds ordered, transactional SQLite migrations with a version ledger. The known local MVP schema is the baseline; upgrades reject future versions and inconsistent history. Hosted startup creates an encrypted recovery archive before upgrading an existing database.

The hosted beta already has an initialized household and a schema 3 database. Never reset or reseed it. For an offline local import, use the copy-and-upgrade procedure in [the stage 1 runbook](docs/stage-1-private-beta.md); it preserves the original and validates an encrypted recovery copy. Arbitrary historical schemas still require investigation before migration.

Deferred by design:

- Live OpenAI provider use in demos/tests
- Push notifications
- Credit cards
- Receipt scanning
- MCP/tool layer

Still intentionally excluded:

- Production auth
- Production Plaid outside the explicitly enabled private Stage 2 USAA connection
- AI autonomous budget changes
- Receipt scanning
- Credit cards
- MCP/tool layer
- Push notifications
- Support for arbitrary historical schemas beyond the versioned stage 1 migration baseline

## Transaction Review API Notes

Milestone 3 API routes are backend-only JSON routes:

```text
GET /budget-months/{budget_month_id}/transactions
GET /budget-months/{budget_month_id}/transaction-review-queue
GET /transactions/{transaction_id}
GET /merchant-category-rules?include_inactive=true
POST /merchant-category-rules
PATCH /merchant-category-rules/{rule_id}
DELETE /merchant-category-rules/{rule_id}
PATCH /transactions/{transaction_id}/review
PATCH /transactions/{transaction_id}/category
PATCH /transactions/{transaction_id}/split
PATCH /transactions/{transaction_id}/ignore
```

Transaction category assignment payload:

```json
{
  "category_id": 123,
  "source": "manual",
  "reviewed": true
}
```

Send `"category_id": null` to remove the active category assignment. Split payloads must add up to the absolute transaction amount:

```json
{
  "splits": [
    {"category_id": 123, "amount_cents": 4000},
    {"category_id": 456, "amount_cents": 2000}
  ],
  "reviewed": true
}
```

Ignored transactions remain in transaction history and audit events, but active category assignments are superseded and ignored transactions do not reduce category remaining.

Android manual category assignment sends `reviewed: true`. New selections start blank and active categories are alphabetical; an existing merchant-rule editor or split editor can show its saved category. Merchant-rule edits do not apply to existing transactions unless explicitly requested through the API. Deleting a rule archives it and preserves past assignments. Routine category assignments and splits retain audit history without creating new notifications; recategorization still notifies.

## Run Tests

Install the backend dependencies from `requirements.txt` into the Python environment used for tests; the hosted HTTP tests require Waitress. A missing test dependency is not a reason to skip those tests.

Use Python from your PATH:

```powershell
python -m unittest discover -s backend\tests
```

On Windows, the Python launcher also works:

```powershell
py -m unittest discover -s backend\tests
```

If `python` is not available on PATH, use the bundled Codex Python runtime:

```powershell
C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s backend\tests
```

## Run API

Use Python from your PATH:

```powershell
python -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

On Windows, the Python launcher also works:

```powershell
py -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

If `python` is not available on PATH, use the bundled Codex Python runtime:

```powershell
C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

## Fresh First-Run Setup

For a fresh local database, start the API with a new local SQLite path:

```powershell
python -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

In Android, open the app with backend URL `http://10.0.2.2:8080`, tap `Check first-run setup`, create the private household and local users, then log in. After login, create the starter budget month if no budget month exists. This setup flow is for the private local MVP only; it is not public signup or production identity management.

## Plaid Sandbox Setup

Do not use Production credentials with the local Sandbox backend. Hosted Production setup is documented separately in [the Stage 2 runbook](docs/stage-2-usaa-plaid.md). For local Sandbox linking:

1. In the Plaid Dashboard, add Android package name `com.familyfinance.app` to the allowed Android package names.
2. Set local environment variables outside git:

```powershell
$env:PLAID_CLIENT_ID = "<your sandbox client id>"
$env:PLAID_SECRET = "<your sandbox secret>"
$env:PLAID_ENV = "sandbox"
$env:PLAID_PRODUCTS = "transactions"
$env:PLAID_COUNTRY_CODES = "US"
```

`PLAID_REDIRECT_URI` is optional and should only be set if your Plaid Dashboard/app configuration requires it.

The local Sandbox backend creates Link tokens and exchanges public tokens. Android never receives Plaid access tokens or token refs. Local Sandbox mode without an encryption key retains the legacy token store. With `FF_ENCRYPTION_KEY`, token values are encrypted; plaintext legacy values require the explicit offline upgrade. Hosted linking stays disabled by default and requires the explicit Stage 2 Production/Trial configuration already applied to the existing private service.

Sandbox manual flow:

1. Run the backend with the env vars above.
2. Log into Android as Daniel or Kara.
3. Open `Accounts / settings`.
4. Tap `Link bank with Plaid Sandbox`.
5. Complete Plaid Link with Sandbox test credentials.
6. Confirm linked checking/savings accounts appear.
7. Use the available bank-sync controls in Accounts / settings; the live Stage 2 flow has a combined `Sync bank data` action.
8. Confirm imported transactions appear in `Transactions` and items needing attention appear in `Transaction Review`.

Credit cards, loans, and investments returned by Plaid are ignored for this MVP.

Login for protected API routes:

```powershell
$auth = Invoke-RestMethod http://127.0.0.1:8080/auth/login `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"username":"daniel","password":"daniel-local-demo-only"}'

$headers = @{ Authorization = "Bearer $($auth.token)" }
Invoke-RestMethod http://127.0.0.1:8080/budget-months/1/summary -Headers $headers
```

## Run Demo Seed

The demo seed creates `work/demo_family_finance.sqlite` with safe synthetic data dated relative to today. It refuses to overwrite an existing file. Use `--db work/another_demo.sqlite` for another demo, and start the API with that same path. An optional `--today YYYY-MM-DD` makes a demonstration reproducible.

- One household and budget month
- Daniel and Kara local-only demo users
- Two included checking accounts and one excluded savings account
- Budget categories for groceries, eating out, household supplies, and gas
- Expected bills and payday data
- Assigned and uncategorized mock transactions
- No real Plaid credentials, real access tokens, production auth provider, AI, receipts, credit cards, MCP, or push notifications

Local-only demo credentials:

```text
Daniel: username daniel / password daniel-local-demo-only
Kara: username kara / password kara-local-demo-only
```

These passwords are intentionally fake demo values. The database stores password hashes, not plaintext passwords.

Use Python from your PATH:

```powershell
python -m backend.app.demo_seed
```

On Windows, the Python launcher also works:

```powershell
py -m backend.app.demo_seed
```

If `python` is not available on PATH, use the bundled Codex Python runtime:

```powershell
C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.demo_seed
```

The seed prints the demo database path and budget month ID. Android defaults to budget month ID `1`, which matches a freshly created demo database.

## Run Demo API

After seeding, run the backend against the demo database:

```powershell
python -m backend.app.api --db work\demo_family_finance.sqlite --host 127.0.0.1 --port 8080
```

Or with the Python launcher:

```powershell
py -m backend.app.api --db work\demo_family_finance.sqlite --host 127.0.0.1 --port 8080
```

Verify locally from Windows:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
$auth = Invoke-RestMethod http://127.0.0.1:8080/auth/login -Method Post -ContentType "application/json" -Body '{"username":"daniel","password":"daniel-local-demo-only"}'
$headers = @{ Authorization = "Bearer $($auth.token)" }
Invoke-RestMethod http://127.0.0.1:8080/budget-months/1/summary -Headers $headers
Invoke-RestMethod http://127.0.0.1:8080/budget-months/1/transactions -Headers $headers
Invoke-RestMethod http://127.0.0.1:8080/budget-months/1/transaction-review-queue -Headers $headers
```

## Run Android App

Open Android Studio, then:

1. Open the `android` folder as the Android project.
2. Start a Pixel 8 emulator.
3. Make sure the backend API is still running on Windows at `http://127.0.0.1:8080`.
4. Run the `app` configuration.
5. On the emulator login screen, keep the backend URL set to `http://10.0.2.2:8080`.
6. Keep budget month ID set to `1` for the demo seed.
7. Log in with `daniel` / `daniel-local-demo-only` or `kara` / `kara-local-demo-only`.

Android emulators use `10.0.2.2` to reach the host machine loopback address. Use `http://10.0.2.2:8080` in the app, not `http://127.0.0.1:8080`, because `127.0.0.1` inside the emulator points to the emulator itself.

The app allows cleartext HTTP for this local MVP demo only. Do not treat that as production network security.

Run Android verification with the installed Android SDK and JDK (Android Studio's bundled JBR works):

```powershell
cd android
.\gradlew.bat testDebugUnitTest assembleDebug lintDebug
```

Changing the backend URL signs out and clears cached financial data before connecting to the new server. A successful password change also requires a fresh login; previous sessions are revoked. The Android client blocks HTTP redirects so a saved bearer token is not forwarded to a redirect destination.

## Recovery behavior and local smoke

- A budget remains readable when there is no upcoming payday. Cash forecast fields are `null` and `forecast_available` is false; the app prompts for a payday instead of showing a zero or a safe result. Safe-to-spend and coach budget proposals still require a future payday. Summary responses also include `as_of` and the backend's configured `low_cushion` decision.
- Copied months keep income plans but reset received amounts. Bank sync preserves category choices, reconciles changed single-category amounts, and returns changed splits to review while retaining their history. Pending-to-posted replacements count once. Batch transaction changes and their cursor commit together.
- Incoming/zero transactions cannot be assigned as expenses. Existing unsupported assignments are preserved and flagged by diagnostics. Stage 2 supports explicit transfer exclusion and single-category refunds; imports still do not automatically plan income. Transaction dates determine budget-month membership, and connected accounts cannot be moved to another month by relinking. See the Stage 2 runbook for reconciliation and rollover rules.
- Money requests use exact whole cents. Fractional JSON cents, booleans, malformed dates and invalid flags are rejected; Android rejects fractional cents and overflowing amounts instead of silently rounding or wrapping them.

Repeat the isolated HTTP/persistence smoke without starting another server or touching your local databases:

```powershell
python -m backend.smoke_review
```

It creates a temporary synthetic household, uses mock providers, exercises authorization, budgeting, categorization/splits/ignores and safe-to-spend, then verifies saved state after a server restart. It removes only its temporary data.

## MVP Smoke Test

With the demo API running and the Pixel 8 emulator open, verify:

- Login succeeds with local-only Daniel or Kara demo credentials.
- Dashboard shows real backend data: included account balance, bills before next payday, cash remaining after bills, days until payday, and uncategorized count.
- Dashboard starts with the check-in streak, personal best, and daily encouragement. Its compact month/sync line and cash-cushion heading use backend data; the Transaction Review card opens the queue.
- Monthly budget shows polished backend groups/categories and supports budget month switching/copy-forward, category add/edit/archive, and funding edits.
- Safe to spend syncs the enabled connected bank before requesting the backend result and required phrase. Failed sync stops calculation; review and explicit reconciliation gates remain. A manual demo without bank linking needs no sync.
- Transaction Review shows empty or non-empty state from backend data, plus local-only queue progress/cleared messaging. Category choices start blank and are alphabetical. Select transactions assigns only the selected eligible rows and reports partial completion if a save fails.
- Tapping a transaction opens transaction detail when demo transactions exist.
- Transaction detail can assign and review a category in one save, split a transaction, confirm an existing assignment when needed, create a merchant rule, and ignore/unignore a transaction. Merchant rules opens an alphabetical list with Edit/Delete; those actions preserve past transaction categories.
- New basic assignments and splits do not add notifications. Existing notification history is retained.
- Accounts / settings shows account inclusion, Plaid Sandbox actions, account settings, and diagnostics/integrity checks.
- Logout clears the local MVP token and returns to the login screen.

Real in current MVP:

- Backend API calls from Android
- Backend summary, account, transaction, review queue, transaction detail, safe-to-spend, category assignment, review, and ignore data
- Deterministic backend financial calculations
- Local mock/demo account and transaction data
- Local-only Android motivational progress/streak display state

Current scope and limitations:

- Login/household access is a private access layer without a managed identity provider
- Local Sandbox token storage without an encryption key is for development only; hosted Plaid tokens are encrypted and Android release sessions use Keystore protection
- Android motivational streak/progress cues are local to the device/app data and are not a backend accountability record
- Private Render deployment for the existing household; public or extended-family onboarding is not enabled
- Production Plaid is limited to the explicitly enabled USAA checking/savings integration; local development remains Sandbox-only
- Credit cards are not supported
- Receipt scanning is not included
- Cloud push notifications are not included
- Public signup, password reset, email verification, OAuth, and a production auth provider are not included
- Budget change approval is not implemented
- AI autonomous budget changes are not included
- MCP/tool integration is not included

## Coach API Notes

Milestone 5 coach routes are backend routes behind a provider abstraction:

```text
POST /coach/safe-to-spend
POST /coach/budget-change-suggestion
```

Safe-to-spend coach payload:

```json
{
  "budget_month_id": 1,
  "category_id": 1,
  "amount_cents": 7500,
  "today": "2026-06-21",
  "urgency": "planned_want",
  "purpose": "weekly groceries"
}
```

The response includes both `safe_to_spend` and `coach`. The deterministic safe-to-spend result remains the source of truth, and the coach explanation must include:

```text
After upcoming bills, you would have about $___ left for ___ days until payday.
```

Budget change suggestion payload:

```json
{
  "budget_month_id": 1,
  "from_category_id": 2,
  "to_category_id": 1,
  "amount_cents": 5000,
  "today": "2026-06-21",
  "purpose": "cover grocery overage"
}
```

This returns a draft `proposed_budget_change` only. It does not apply the change, update category funding, recategorize transactions, mark transactions reviewed, create/archive categories, or access Plaid.

No Anthropic, Gemini, Agents SDK, MCP/tool layer, real API key, or `.env` file is required for Milestone 5A/5B default mock operation.

### Coach Provider Configuration

By default, the backend uses the deterministic mock provider:

```powershell
$env:COACH_PROVIDER = "mock"
```

To enable the OpenAI provider later for local development, set:

```powershell
$env:COACH_PROVIDER = "openai"
$env:OPENAI_API_KEY = "<your real key outside git>"
$env:OPENAI_MODEL = "gpt-4o-mini"
$env:OPENAI_TIMEOUT_SECONDS = "10"
```

`OPENAI_API_KEY` is required only when `COACH_PROVIDER=openai`. Never commit `.env` files or real keys. Real OpenAI API use may incur cost, so keep `COACH_PROVIDER=mock` for tests and demos unless you intentionally opt in locally.

The OpenAI provider is a direct backend provider abstraction for short coach calls. It does not use the Agents SDK, does not expose provider internals to Android, does not access Plaid, and does not mutate budget, category, or transaction data.

Provider output cannot replace structured backend facts, the safe-to-spend decision, or draft amounts/category IDs. Stop/discuss decisions use deterministic wording. Optional model prose on other results remains advisory and is not guaranteed factually correct; live OpenAI was not used in recovery verification. Keep the default mock provider for the reproducible local demo.
