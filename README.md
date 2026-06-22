# Family Finance Accountability App

This workspace starts the staged MVP from the attached build plan.

The implemented slices are Milestone 1, Milestone 2, and Milestone 3 backend scaffolding.

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

Environment variables are placeholders only:

- `PLAID_CLIENT_ID`
- `PLAID_SECRET`
- `PLAID_ENV`
- `PLAID_PRODUCTS`
- `PLAID_COUNTRY_CODES`
- `PLAID_REDIRECT_URI`

Do not commit `.env` files or real Plaid credentials.

## Database Schema Assumption

This staged MVP does not have a production migration system yet. `backend/app/schema.sql` is applied with `CREATE TABLE IF NOT EXISTS`, which is enough for fresh local SQLite databases but does not safely migrate existing databases when columns, indexes, or constraints change.

Current assumption: this is still a dev-only SQLite schema rebuild workflow. During these early milestones, reset local data by deleting the local `.sqlite` database and letting the app initialize a fresh schema. Do not treat existing SQLite files as forward-migratable production data until a real migration tool and migration history are added.

Deferred by design:

- AI agent explanations
- Android UI
- Push notifications
- Credit cards
- Receipt scanning
- MCP/tool layer

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
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s backend\tests
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
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

## Run Demo

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
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.demo_seed
```
