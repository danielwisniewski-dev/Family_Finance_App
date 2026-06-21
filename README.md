# Family Finance Accountability App

This workspace starts the staged MVP from the attached build plan.

The implemented slice is Milestone 1: deterministic household budget logic that can answer safe-to-spend questions without Plaid or AI. It includes:

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

Deferred by design:

- Plaid
- AI agent explanations
- Android UI
- Push notifications
- Credit cards
- Receipt scanning
- MCP/tool layer

## Run Tests

Use the bundled Codex Python runtime:

```powershell
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s backend\tests
```

## Run API

```powershell
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.api --db work\family_finance.sqlite --host 127.0.0.1 --port 8080
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

## Run Demo

```powershell
C:\Users\danny\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m backend.app.demo_seed
```
