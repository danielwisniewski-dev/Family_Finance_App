# Provision funds

This milestone adds named funds beneath Combined Monthly Provision for irregular household expenses. The combined `codex/provision-funds` release includes [bank sync controls and transaction review improvements](bank-sync-controls.md). Daniel authorized commit and deployment September 23; backend deployment and household setup are pending.

## Household workflow

- Each fund has a monthly contribution plan, annual allowance, timing notes, and an optional itemized annual breakdown. Exact household amounts and account selection remain in ignored `work/provision-fund-setup.json`, never in release source or test fixtures.
- Money stays in the selected existing checking account. Setting aside money records an earmark, not a bank transfer, income, or expense. Either spouse explicitly confirms the amount; partial contributions are supported.
- All initial saved balances are zero. Planning a contribution never creates saved money. Existing bank balances and the old category's remaining amount are not used to infer opening reserves.
- Saved balances persist across budget months. The new month's contribution plan remains distinct from money saved in earlier months.
- Categorize a real transaction to the appropriate fund category, including existing split and refund workflows. The purchase remains one expense and reduces that fund's balance. Overspending is visible; actual bank spending is not discarded because a fund lacked money.
- Release earmarked money or move it between funds explicitly, with shared audit history. These actions do not move cash at USAA.
- Annual allowances and timing notes are planning information. The app does not increase contributions automatically to catch up for a near-term purchase in the first year, or invent exact bill due dates from month names.
- Restoring a fund in a month without its budget category adds a zero-plan category. An explicit plan edit can also add the category in a month created without copying. Existing monthly plans and saved balances are preserved.

## Accounting and preservation

The backend owns all balances. Actual fund balances come from the contribution ledger and active, non-ignored spending/refund allocations. Imported transaction corrections, removals, recategorization and split changes must affect the reserve consistently without double-counting.

Ordinary safe-to-spend protects funded reserves in included accounts. Spending from a selected fund can use that fund's saved money while protecting other funds. Excluded backing cash must not be subtracted a second time. A planned bill can identify its fund so cash already reserved for that bill is not held twice. Missing or insufficient backing must not yield a reassuring spending result.

Monetary actions require an idempotency key. A retry cannot create another contribution, release, or movement, and reuse with different contents is rejected. Ownership and actor checks apply to the fund, budget month, backing account and movement destination.

Schema 4 adds fund records and history without reseeding the household, changing authentication or Plaid tokens, or assigning old spending to new funds. Setup is a separate explicit operation. Replacing the existing provision plan preserves old transactions and categories and avoids adding the same monthly provision twice.

## API surface

- `GET /budget-months/{id}/funds`: backend overview, breakdown and fund history.
- `POST /budget-months/{id}/funds`: create a zero-balance fund and its monthly category.
- `POST /budget-months/{id}/funds/setup`: atomically set up a list of funds, optionally replacing an existing category's monthly plan.
- `PATCH /funds/{id}`: change fund metadata or its selected month's contribution plan.
- `POST /funds/{id}/entries`: record a confirmed contribution or release.
- `POST /funds/{id}/transfer`: move an earmark between funds, without moving bank cash.
- Existing expected-bill routes accept an optional `reserve_fund_id`.

## Release checks

Before commit approval, verify targeted fund accounting and authenticated route tests, the full backend suite, Android unit tests and debug build, and a practical synthetic flow through contribution, purchase, carryover and protected cash. Include schema upgrade preservation, cross-household denial, duplicate requests, bank corrections, refunds, split transactions, excluded backing and funded upcoming bills.

Production deployment and household setup follow review. Preserve the existing service, database, recovery key, Plaid Item and Android signing identity; use the running service's verified recovery key for a fresh backup, as documented in `stage-2-usaa-plaid.md` and the ignored operational handoff. Do not use the known-different SSH key environment blindly.

## Local verification, September 23, 2026

- Final combined backend suite: 289 tests passed. Two old upgrade fixtures were corrected to start from the pre-provision schema. Existing test dependency permissions and a Windows-aborted local HTTP connection were resolved; affected tests passed focused reruns before the final clean suite.
- Android `testDebugUnitTest` and `assembleDebug`: passed, 99 tests, no failures or errors; version `0.7.0-provision`, code 6. The signed release build also passed, with the original certificate, existing HTTPS backend, and non-debuggable configuration verified. Physical phone installation remains unobserved.
- `python -m backend.smoke_funds`: passed using disposable synthetic data. Both spouses can see zero opening balances, partial funding, a safe retry, categorized spending, protected cash, month carryover, and persisted balances.
- A separate local setup dry run validated all eight supplied funds and ten annual breakdown items, zero saved balances, exact supplied amounts/timing notes, and replacement of the old plan without double assignment. It did not change the real household.
- A disposable, read-only Pixel 8 emulator passed login, overview/detail screens, an explicit contribution, annual breakdown display, and persisted balance after APK reinstall/restart. Screenshots were inspected; redundant form labels were fixed. Physical phone acceptance remains unobserved.
- Review fixes include copied-category archive enforcement, deficit repair without reserving already-spent cash twice, restoration after month rollover, unchanged bill fund links, and archived plan preservation.
- The private setup and synthetic screenshots remain in ignored `work/`. Source secret/junk checks found no credentials, private household figures, databases, or generated build files among the release candidates.
- `git diff --check` passed. Daniel approved committing and deploying this release September 23. The existing household, bank connection, recovery key, and signing files must remain preserved throughout rollout; merge requires separate approval under `AGENTS.md`.
