# Family Finance Accountability App

This workspace starts the staged MVP from the attached build plan.

The implemented slices are Milestone 1, Milestone 2, Milestone 3 backend scaffolding, Milestone 4 Android MVP screens, Milestone 5A/5B backend coach scaffolding, Milestone 6 spouse accountability notifications, Milestone 7 private household access, and Milestone 8 Plaid Sandbox linking/sync.

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

This is Sandbox-only. `PLAID_ENV` must be `sandbox`; production Plaid is intentionally unsupported in this app.

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

This staged MVP does not have a production migration system yet. `backend/app/schema.sql` is applied with `CREATE TABLE IF NOT EXISTS`, which is enough for fresh local SQLite databases but does not safely migrate existing databases when columns, indexes, or constraints change.

Current assumption: this is still a dev-only SQLite schema rebuild workflow. During these early milestones, reset local data by deleting the local `.sqlite` database and letting the app initialize a fresh schema. Do not treat existing SQLite files as forward-migratable production data until a real migration tool and migration history are added.

Deferred by design:

- Live OpenAI provider use in demos/tests
- Push notifications
- Credit cards
- Receipt scanning
- MCP/tool layer

Still intentionally excluded:

- Production auth
- Production Plaid
- AI autonomous budget changes
- Receipt scanning
- Credit cards
- MCP/tool layer
- Push notifications
- Budget editing workflows beyond placeholder copy
- Transaction split editing in Android

## Transaction Review API Notes

Milestone 3 API routes are backend-only JSON routes:

```text
GET /budget-months/{budget_month_id}/transactions
GET /budget-months/{budget_month_id}/transaction-review-queue
GET /transactions/{transaction_id}
POST /merchant-category-rules
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

## Run Tests

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

## Plaid Sandbox Setup

Do not use production Plaid credentials with this app. For local Sandbox linking:

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

The backend creates Link tokens and exchanges public tokens. Android never receives Plaid access tokens or token refs. For this local MVP, raw Plaid access tokens are stored in SQLite behind token refs so sync can work across backend calls. Production requires encrypted persistent secret storage or a secrets manager before using real financial credentials.

Sandbox manual flow:

1. Run the backend with the env vars above.
2. Log into Android as Daniel or Kara.
3. Open `Accounts / settings`.
4. Tap `Link bank with Plaid Sandbox`.
5. Complete Plaid Link with Sandbox test credentials.
6. Confirm linked checking/savings accounts appear.
7. Tap `Sync balances` and `Sync transactions`.
8. Confirm imported transactions appear in `Transactions` and uncategorized items appear in `Uncategorized review`.

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

The demo seed rebuilds `work/demo_family_finance.sqlite` from scratch with safe local demo data:

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

The seed prints the demo database path and budget month ID. Android defaults to budget month ID `1`, which matches a freshly rebuilt demo database.

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

## Milestone 4 Smoke Test

With the demo API running and the Pixel 8 emulator open, verify:

- Dashboard shows real backend data: included account balance, bills before next payday, cash remaining after bills, days until payday, and uncategorized count.
- Login succeeds with local-only Daniel or Kara demo credentials.
- Logout clears the local MVP token and returns to the login screen.
- Monthly budget shows backend categories.
- Tapping a budget category opens category detail.
- Transactions shows seeded mock transactions.
- Uncategorized review shows items from the demo seed.
- Tapping a transaction opens transaction detail.
- Safe to spend returns a backend-calculated result and required phrase.
- Transaction detail can assign a category, toggle reviewed/unreviewed, and ignore/unignore a transaction.

Real in Milestone 4:

- Backend API calls from Android
- Backend summary, account, transaction, review queue, transaction detail, safe-to-spend, category assignment, review, and ignore data
- Deterministic backend financial calculations
- Local mock/demo account and transaction data

Placeholder or intentionally limited:

- Login/household access is a private local access layer, not production auth
- Budget change approval is not implemented
- Budget group names are not exposed by the current backend summary route
- Funding edits are placeholder-only
- Transaction split editing is read-only in Android
- Plaid is Sandbox-only and requires local Plaid env vars for live linking
- AI, receipt scanning, credit cards, MCP, and push notifications are not included

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
