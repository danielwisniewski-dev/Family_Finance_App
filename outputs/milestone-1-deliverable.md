# Milestone 1 Deliverable

Implemented the deterministic core budget engine from the staged MVP plan.

## What Works Now

- Create a household with two spouses.
- Create a monthly budget.
- Add main income and received sporadic income.
- Add/edit/archive budget categories.
- Track planned amount, actual spent, and remaining amount per category.
- Configure expected bills before payday.
- Configure paydays.
- Store an included-account cash balance for Milestone 1 cash-reality checks.
- Model manual checking/savings accounts and include or exclude them from cash reality.
- Calculate safe-to-spend without AI.
- Return the required phrase pattern:

  `After upcoming bills, you would have about $___ left for ___ days until payday.`

## Implementation

- `backend/app/domain.py`: deterministic budget and safe-to-spend math.
- `backend/app/schema.sql`: SQLite database schema, including manual cash accounts.
- `backend/app/db.py`: repository layer and SQLite persistence.
- `backend/app/api.py`: dependency-free JSON HTTP API.
- `backend/tests/test_budget_engine.py`: acceptance coverage for overspending, low cushion, upcoming bills, sporadic-income treatment, payday errors, archived categories, exact-zero category remaining, category funding edits, bills due today, and savings inclusion/exclusion.
- `backend/tests/test_api.py`: HTTP-level safe-to-spend smoke coverage.

## Verification

Run all tests:

```powershell
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s backend\tests
```

Current result: `Ran 12 tests ... OK`.

Run a demo safe-to-spend calculation:

```powershell
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.demo_seed
```

Run the API:

```powershell
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

## Deferred Milestones

- Milestone 2: Plaid connection, account selection, balance sync, transaction sync.
- Milestone 3: transaction review, categorization, split transactions, rules.
- Milestone 4: Android screens.
- Milestone 5: agent advisor explanations using backend-calculated numbers only.
- Milestone 6: spouse approvals, notifications, and change history.
