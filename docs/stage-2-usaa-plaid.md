# Stage 2: private USAA bank data

This milestone enables an explicit, private production Plaid connection for Daniel and Kara. Production stays disabled until the reviewed code is deployed and the existing Render service is configured. No live USAA connection or financial reconciliation is implied by passing the synthetic tests.

## Verified provider setup — September 12, 2026

The signed-in Plaid Dashboard shows **Free trial, 0/10 connections used**. Its OAuth institutions tab says automatic bank access requires no additional action for this Trial. The allowed Android package list already contains `com.familyfinance.app`. Institution search identifies USAA as `ins_7`; the handoff reported Auth, Balance, and Transactions coverage. The institution health dashboard is unavailable for this Trial, and the View details control did not expose further information. An actual Link session and successful data requests remain required to establish USAA connectivity and product entitlement end to end.

Current official references:

- [Trial and billing](https://plaid.com/docs/account/billing/): ten Production Items over the life of the Trial; removing an Item does not recover a slot. Transactions and Balance are available on Trial. Upgrading to a paid plan starts applicable subscriptions on existing Items. No paid-plan upgrade is part of this milestone.
- [Android Link](https://plaid.com/docs/link/android/) and [OAuth](https://plaid.com/docs/link/oauth/): register the package name and pass `android_package_name`; do not pass a web `redirect_uri` for the native Android SDK. USAA consent may need renewal after 18 months. No new domain is required.
- [Balance](https://plaid.com/docs/balance/): `/accounts/balance/get` refreshes balances; `/accounts/get` returns cached data. We initialize **Transactions only**, then use Balance on the same Item. Auth/routing/account-number retrieval and money movement are unnecessary.
- [Transaction states](https://plaid.com/docs/transactions/transactions-data/) and [Sync API](https://plaid.com/docs/api/products/transactions/): posting can change an ID, date, or amount. Pending removal and posting may span pages. Pagination must restart from the original cursor if the dataset changes during pagination.
- [Android SDK releases](https://github.com/plaid/plaid-link-android/releases): retained the existing tested 5.5.2 integration for this milestone; upgrading to 6.x changes the SDK lifecycle API and compile SDK and is separate work. Physical USAA OAuth return testing remains a launch gate.

## Runtime and preservation

Keep the same Render service, disk, `FF_DB_PATH`, `FF_ENCRYPTION_KEY`, setup code, household IDs, users, passwords, and Android signing files. Do not reset, reseed, regenerate secrets, or uninstall the phone app. Schema 3 adds sync/reconciliation state, refund allocations, and a transaction-to-month view. Existing accounts and transactions retain their IDs. Startup creates an encrypted backup and verifies a disposable restore **before migration**.

On September 12 a fresh offsite encrypted backup was created, restored and checked on Render, then downloaded with a matching SHA-256. Evidence and encrypted archives are under ignored `work/offsite-backups`. The hosted database remained schema 2 during implementation. Take another fresh verified backup if data changes before the eventual deployment. The signing directory remains `work/private-beta-signing`; the updated build script refuses to create a replacement key or password.

Do not add credentials to the running stage 1 build: it rejects them. After Daniel approves committing and reviewing the stage 2 code, deploy the approved code manually to the existing Render service with bank linking still disabled. Confirm health/readiness and existing logins. Then set these together in **Render environment settings**, using Plaid's Production values directly without putting secrets in chat:

| Setting | Value |
| --- | --- |
| `FF_PLAID_ENABLED` | `true` |
| `FF_PLAID_TRIAL_CONFIRMED` | `true`, only while the verified Trial remains in effect |
| `PLAID_ENV` | `production` |
| `PLAID_USAA_INSTITUTION_ID` | `ins_7` |
| `PLAID_PRODUCTS` | `transactions` |
| `PLAID_COUNTRY_CODES` | `US` |
| `PLAID_CLIENT_ID` | Plaid Production client ID; secret settings only |
| `PLAID_SECRET` | Plaid Production secret; secret settings only |
| `PLAID_REDIRECT_URI` | absent |

Leave the existing encryption/setup keys and mock coach configuration intact. `render.yaml` intentionally retains the disabled default; do not resync its Sandbox defaults over a live connection. Auto deploy is off in the saved service configuration. Blueprint Auto Sync still needs independent dashboard verification before rollout.

The live client refuses redirects, uses a fixed Production hostname/API version, and returns only sanitized errors. Tokens are encrypted and persisted immediately after exchange, before later account/transaction requests. One Item per household is supported; reconnect uses update mode instead of exchanging another public token. Two spouses linking the same shared USAA accounts separately would duplicate cash and consume Trial slots, so only link once. Additional separate USAA logins require a separately reviewed account-deduplication design.

## Financial behavior

- New bank accounts start excluded. Compare the USAA accounts and explicitly include the checking/savings accounts that fund household spending. Exclude any manually entered copies. Connected balances cannot be manually overwritten.
- Bank account ownership is household-wide. Transaction dates determine monthly review and spending; accounts are not moved or duplicated at rollover. History outside an existing budget month stays stored and appears when that month is created. Historical screens show the latest saved bank cash, not a historical bank balance; live safe-to-spend is restricted to today's current month.
- Sync applies complete added/modified/removed batches and the cursor atomically. Pending-to-posted updates keep local identity and audit history. A changed split or posting month requires review; removed transactions stop affecting the budget. Removed transactions that reappear return for review without resurrecting old allocations.
- Transfers require explicit **Mark as transfer** / exclusion. Incoming pay is reviewed and entered in the income plan by a person; imports do not automatically increase planned income. A posted refund can explicitly credit one active category in its transaction month, once. Remove category assignment to undo a refund. Amount/date changes and ignoring the transaction clear that refund allocation, retaining audit events. Cross-month refunds credit the month received, not the original purchase month. Partial refund splits are outside this milestone.
- Upcoming bills are drawn across household budget months before the next payday. Safe-to-spend requires the payday's month to exist, so plan the next month before crossing into it. Imported bill payments do not automatically mark planned bills paid: confirm them to avoid reserving cash twice.
- Safe-to-spend requires explicit monthly reconciliation, reviewed and categorized (or excluded) outflows, fresh available balances, a successful balance and transaction download within 15 minutes, and complete transaction history whose last bank update is within 24 hours. These are conservative application limits, not a claim that Plaid transactions are instantaneous. Unknown balances, missing included accounts, failed sync, or stale/incomplete history block the spending decision. Category remaining and real included cash after bills still both constrain the answer.
- Refresh household data reads saved backend data. **Sync bank data** makes user-initiated Balance/Transactions calls. There is no webhook endpoint, background worker, paid Transactions Refresh call, or automatic polling in this milestone. The dashboard labels saved balances; Settings displays bank and download timestamps. Repeat Sync if the initial bank history is still being prepared.

## Deployment and real-data acceptance

1. Obtain Daniel's commit approval; open the milestone PR against main. Merge requires separate approval. Deploy only the approved code to the existing service after a fresh verified backup.
2. Verify Blueprint Auto Sync is off and confirm `/health`, `/ready`, authenticated existing household access, and unauthenticated 401 responses. Configure production values as above without changing recovery secrets.
3. Build `scripts/build-private-beta.ps1 -BackendUrl https://family-finance-beta.onrender.com`. Verify `work/releases/family-finance-stage2.apk` is version `0.6.0-stage2`, code 3, and uses the stage 1 certificate. Install as an update on Pixel 7a and Pixel 9 after the server has stage 2 routes.
4. One spouse opens Settings → Connect USAA with Plaid, selects USAA, and completes USAA's own sign-in/consent. Bank credentials are entered only in the bank/Link flow. Confirm OAuth returns to the app. Select the shared checking/savings accounts once.
5. Sync until history is complete. Compare account masks and both current and available balances directly with USAA. Compare recent posted and pending transactions, dates, amounts, transfers, refunds and duplicates. Record mismatch findings without copying account numbers or raw provider payloads into Git or chat.
6. Review/categorize outflows, explicitly exclude transfers and duplicate manual spending, apply genuine refunds, record received income, and mark already-paid bills. Include the intended accounts. Confirm reconciliation in Settings only after the comparison passes.
7. Test an in-budget and an over-budget purchase, cash after upcoming bills, and next-payday days against USAA and the household plan. Verify both phones agree after refresh. Test failed sync and reconnect without another Item, posting changes, and a later month rollover. Preserve existing household edits and logins after restart.

Local tests establish review readiness. Stage 2 remains **unverified with real financial data** until these live acceptance steps pass.

## Implementation verification — September 12, 2026

- Final full backend suite: **210 passed**, including 25 stage 2 regressions and the real Waitress HTTP bank smoke with synthetic provider data. The schema 2-to-3 migration test preserved every existing household table row and session.
- Android: **38 unit tests passed**; debug and signed release builds passed. The final APK is code 3 / `0.6.0-stage2`, configured for the existing HTTPS backend. Both APK signatures verified and the stage 1/2 certificates matched; existing signing key/password file contents were unchanged. APK SHA-256 and signing evidence are in ignored `work/stage2-apk-verification.json` and `work/stage2-signing-preservation.json`.
- Both existing HTTP/persistence smokes passed, covering shared edits, financial totals, authorization, restart, encrypted restore and fresh login after restoration. Physical device OAuth and USAA reconciliation have not run.
- Verified live service: health/readiness 200, unauthenticated budget access 401, setup closed, bank linking still disabled. No live code/configuration migration or household mutation was performed. The fresh offsite archive is `work/offsite-backups/manual-offsite-20260912T185432Z-4fb407e3.ffbackup`; its disposable restore and download hash matched.
- Secret/junk scan: 100 repository candidates; no known private signing/SSH material, generated-file paths, or encoding issues. The only token-shaped regex match was the pre-existing synthetic Sandbox redaction fixture. `git diff --check` passed.
- Resolved verification issues included the legacy migration fixture's version count, a temporary Windows encoding error during Android edits, and stale account values on the reconciliation screen. No unresolved test failures. Existing Gradle/SDK deprecation notices remain.
- Daniel approved committing stage 2 and opening its PR on September 12, 2026; merge needs separate approval. Render Dashboard needs sign-in to independently check Blueprint Auto Sync and configure rollout.
