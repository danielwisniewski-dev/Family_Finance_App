# Family Finance Accountability App — Project Plan

## Purpose

Build a private household finance accountability app for Daniel and Kara.

The app should help the household make better spending decisions before money disappears by combining:

- Monthly planned budgeting
- Live account awareness
- Transaction review
- Safe-to-spend checks
- Firm, practical accountability
- Later AI-assisted coaching

This is a private family tool, not a public product.

---

## Core Product Principle

The app must never answer based only on bank balance.

Every safe-to-spend answer should consider both:

1. Budget line remaining
2. Real cash remaining after upcoming bills before the next payday

Required safe-to-spend phrase pattern:

> After upcoming bills, you would have about $___ left for ___ days until payday.

---

## Planning Philosophy

Prioritize in this order:

1. Security
2. Privacy
3. Correct financial logic
4. Simplicity
5. Buildability
6. Low maintenance
7. MVP focus
8. Cost control

Avoid overbuilding.

Build one milestone at a time.

---

## Budget Philosophy

The budgeting model should be closer to Dave Ramsey / EveryDollar than YNAB.

Use a monthly planned budget:

- Plan the month ahead using expected main income.
- Main income is predictable and paid twice monthly.
- Sporadic secondary income should not be planned until it actually arrives.
- Every planned dollar should be assigned to a budget line.
- Budget line remaining is separate from real account balance.
- The app should track both budget line balances and real account cash position.

---

## MVP Account Scope

MVP accounts:

- Two checking accounts
- One savings account

MVP excludes:

- Credit cards
- Investment accounts
- Loans
- Multi-household support

Savings should be visible, but its effect on cash reality should depend on whether it is marked included or excluded.

Credit cards are intentionally excluded because the household is pausing credit card use for now.

---

## Safe-to-Spend Logic

For a purchase request, the backend should calculate:

- Requested amount
- Selected budget category
- Category remaining before purchase
- Category remaining after purchase
- Included account balance
- Bills expected before next payday
- Cash remaining after those bills
- Days until next payday
- Cash cushion per day
- Warning level

Warning levels:

- `safe`
- `caution`
- `no`
- `discuss`

A purchase may fit the category but still receive a caution if the remaining cash cushion is low relative to the number of days until payday.

The app should clearly explain:

- Whether the purchase fits the budget line
- How much remains in that line
- How much cash remains after bills
- How many days remain until payday
- Whether the cushion is low

---

## Architecture Principle

Use this separation:

- Android app = user interface
- Backend server = system of record, deterministic rules, data access
- Database = budget, transactions, accounts, audit history
- Plaid integration = backend-only financial data import
- AI agent = advisor/explanation layer, not the owner of budget truth

The AI agent must not invent balances, change budgets silently, or directly own the financial logic.

---

## Agent Behavior Rules

The eventual AI coach should be:

- Firm
- Clear
- Practical
- Not shame-based
- Focused on tradeoffs
- Honest about uncertainty
- Good at saying no when needed
- Helpful to both spouses
- Careful with private financial details

The agent may eventually:

- Explain safe-to-spend results
- Suggest moving money between categories
- Suggest creating or reducing categories
- Flag risky spending
- Ask brief clarifying questions
- Draft budget changes for approval

The agent may not:

- Directly change budgets without approval
- Delete or hide transactions
- Override backend calculations
- Access Plaid directly
- Invent financial facts
- Make shame-based comments

Either spouse may approve an agent-suggested change.

All approved budget changes should generate a notification to the other spouse.

---

## Security and Privacy Rules

- Do not expose Plaid access tokens to the frontend.
- Do not commit `.env` files.
- Do not commit real Plaid credentials.
- Do not commit local SQLite database files.
- Do not commit `.venv`, `__pycache__`, `.pytest_cache`, or generated junk.
- Real Plaid credentials should not be used until production-grade token storage and authorization exist.
- Backend should sanitize API responses.
- Household financial data should be treated as private and sensitive.

Milestone 2 Plaid behavior is scaffolding/mock behavior only.

Before real Plaid use, add:

- Real Plaid SDK-backed client
- Encrypted persistent token storage or secrets manager
- Auth/authorization
- Migration system
- Sandbox integration tests
- Redacted logging
- Full transaction sync semantics

---

## Git and Build Workflow

Use one milestone per branch and PR.

Standard workflow:

1. Start from latest `main`
2. Create a feature branch
3. Build only the current milestone
4. Run full tests
5. Push branch
6. Open PR against `main`
7. Review changed files
8. Confirm no secrets/junk
9. Merge manually in GitHub
10. Delete feature branch
11. Pull latest `main`

Main branch should be protected from deletion and force pushes.

Do not push directly to `main`.

---

## Completed Milestones

### Milestone 1 — Core Budget Engine

Built deterministic household budget logic.

Included:

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

Excluded:

- Plaid
- AI
- Android
- Receipt scanning
- Push notifications
- Credit cards

---

### Milestone 2 — Plaid and Account Scaffolding

Built backend-only Plaid/account scaffolding.

Included:

- Plaid link-token and public-token exchange API scaffolding
- Backend-only Plaid item records with token references
- No frontend-exposed access tokens
- Plaid account metadata attached to checking/savings cash accounts
- Account inclusion/exclusion controls for cash reality
- Balance sync and transaction sync service abstractions
- Plaid transaction deduplication by transaction ID
- Sync error capture without crashing budget reads
- Tests for account selection, transaction deduplication, and sync error handling

Important limitation:

Milestone 2 is not live Plaid network integration. It is scaffolding plus mock/placeholder Plaid behavior.

Excluded:

- Real Plaid credentials
- Real Plaid API calls
- Persistent encrypted token vault
- Auth/authorization
- Production migrations
- Android
- AI
- Receipt scanning
- Credit cards

---

### Milestone 3 — Transaction Review and Categorization

Goal:

Make imported/mock Plaid transactions usable for the budget before building Android UI or AI behavior.

Scope:

- Transaction list and detail behavior
- Uncategorized transaction queue
- Reviewed/unreviewed state
- Manual category assignment
- Recategorization
- Category assignment removal
- Merchant-based categorization rules
- Plaid category/name as hints only
- User/manual category choice overrides Plaid hints
- Transaction splitting across categories
- Split validation
- Ignored/excluded transactions
- Audit metadata
- Category totals from active non-ignored assignments

Tests should cover:

- Uncategorized transactions appear in review queue
- Assigning category updates spent/remaining
- Recategorizing removes spending from old category and applies to new category
- Removing category assignment works
- Merchant rules categorize future matching transactions
- Merchant rule overrides Plaid hints
- Manual choice overrides Plaid hint
- Splits update multiple category totals correctly
- Split amounts must equal original transaction amount
- Ignored transactions do not affect category spending
- Unignore does not restore stale assignments incorrectly
- No double-counting with manual spending plus transactions
- API transaction review/detail routes are sanitized
- No access tokens or token references exposed
- All prior milestone tests still pass

Excluded:

- Android UI
- AI behavior
- Receipt scanning
- Credit cards
- MCP/tool layer
- Push notifications
- Real Plaid network integration

---

## Upcoming Milestones

### Milestone 4 — Android MVP Screens

Goal:

Create the first usable Android app experience after backend transaction categorization is stable.

Likely screens:

1. Login / household access
2. Dashboard
3. Monthly budget
4. Category detail
5. Transactions
6. Uncategorized transaction review
7. Safe-to-spend check
8. Budget change approval placeholder
9. Settings / accounts

Dashboard should show:

- Total included account balance
- Bills before next payday
- Cash remaining after those bills
- Days until next payday
- Low cushion warning
- Categories needing attention
- Uncategorized transactions

Forbidden in Milestone 4:

- AI agent behavior
- Receipt scanning
- Credit cards
- MCP
- Push notifications unless explicitly scoped
- Complex charts
- Polished design work beyond MVP usability

---

### Milestone 5A - Coach Scaffolding

Goal:

Add the backend coach architecture without connecting to a real AI provider.

The coach should use:

- Android app -> backend coach endpoint -> coach service -> provider interface -> mock provider
- Backend-calculated fact packets only
- Structured, predictable coach responses
- Draft budget change suggestions only

The mock provider is deterministic and does not require an OpenAI, Anthropic, Gemini, or other AI API key.

The coach may:

- Explain safe-to-spend results
- Suggest caution/no/discuss
- Draft budget changes for later approval

The coach may not:

- Make budget changes without approval
- Recategorize transactions
- Mark transactions reviewed or ignored
- Create, archive, or delete categories
- Access Plaid directly
- Invent balances, bills, payday dates, or transactions

### Milestone 5B - OpenAI Provider Scaffold

Goal:

Add production-shaped OpenAI coach provider integration without making it the default provider.

The provider should:

- Stay disabled unless `COACH_PROVIDER=openai`
- Require `OPENAI_API_KEY` only when OpenAI is explicitly selected
- Use `OPENAI_MODEL` and `OPENAI_TIMEOUT_SECONDS`
- Receive only backend-produced fact packets
- Request structured JSON output and map it into the existing coach response schema
- Return sanitized fallback responses on timeout or provider error
- Avoid live OpenAI calls in tests and demos

The agent should use backend-calculated numbers only.

Agent may:

- Explain safe-to-spend results
- Suggest budget changes
- Draft budget changes for approval
- Flag risky spending
- Ask brief clarifying questions

Agent may not:

- Make budget changes without approval
- Access Plaid directly
- Invent balances or bills
- Hide transactions
- Override deterministic backend rules

---

### Milestone 6 — Spouse Accountability and Notifications

Goal:

Make budget changes visible to both spouses.

Build:

- Either spouse can approve suggested changes
- Approved changes notify the other spouse
- Budget change history
- Notification event records
- Useful, non-shaming alerts

Notify on:

- Category created
- Category archived
- Funding changed
- Money moved between categories
- Transaction recategorized
- Safe-to-spend request marked discuss
- Low cash cushion warning

---

## Later / Not MVP

Delay these until the core app is useful:

- Receipt photo scanning
- Weekly wasted-wealth audit
- Advanced AI coaching
- MCP layer
- Predictive forecasting
- Credit card handling
- Multi-account optimization
- Complex charts
- Investment tracking
- Subscription cancellation
- Multi-household support
- Polished gamification

---

## Codex Instruction

This document is project background.

It is not permission to build everything.

For each Codex task:

- Read this plan for context.
- Implement only the milestone explicitly requested in the current prompt.
- Do not build later milestones early.
- Preserve security/privacy boundaries.
- Keep deterministic financial logic tested.
- Run the full test suite before committing.
