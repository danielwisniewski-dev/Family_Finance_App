# Stage 2: private USAA bank data

This milestone enables an explicit, private Production Plaid connection for Daniel and Kara. Production is disabled by default in source configuration and explicitly enabled on the existing Render service. Synthetic tests alone do not establish live financial correctness.

## Current handoff — September 19, 2026

The subsequent [interface update](interface-tweaks.md), Android `0.6.1-interface` / code 4, was merged in [PR #20](https://github.com/danielwisniewski-dev/Family_Finance_App/pull/20), and its backend was deployed September 17 with the household database, recovery key, and Plaid connection preserved. Its signed APK uses the original certificate; physical phone installation has not been independently observed. Safe-to-spend automatically calls the existing balance and transaction sync APIs before requesting a result; all backend readiness checks still apply.

The [warmer interface update](ui-warmth.md), Android `0.6.2-warmth` / code 5, adds visual polish, confirmed-action celebrations, and dashboard refinements. Daniel approved GitHub publication and signed phone delivery September 19. It requires no backend deployment, migration, or bank reconnection; see its release notes for delivery and verification. The Stage 2 observations below remain historical facts.

- Daniel merged [PR #19](https://github.com/danielwisniewski-dev/Family_Finance_App/pull/19) and deleted its remote branch. Release commit `16e9de6c2667b90e8970e5dd1798f5f27db80ea7` was deployed September 12; local `main` and GitHub `main` were verified to match on September 17 before these documentation edits.
- The existing Render service runs schema 3 with the original household and recovery key preserved. Blueprint Sync was verified paused and Auto-Deploy off. Daniel entered credentials directly in Render and saved/deployed the Production/Trial configuration. Do not reapply the disabled Blueprint defaults over the live configuration.
- The signed Android update is `0.6.0-stage2`, code 3, using the original signing certificate. Daniel confirmed the native USAA OAuth flow returned to Android and accounts appeared. One USAA Item was verified; do not create another connection to repeat completed setup.
- Live balance/transaction imports and complete initial history were verified without duplicate provider IDs. Daniel confirmed the app's balances and recent transaction amounts/dates matched USAA. His exact September budget and dated bills were loaded and independently verified, preserving income and transaction history. Financial values and operational evidence stay under ignored `work/`.
- Encrypted backup restore and bank-token recovery passed on Render. An explicitly authorized encrypted archive was downloaded with a matching checksum; Daniel confirmed keeping a cloud copy and the recovery key separately. Recurring offsite export is not configured. Preserve the existing Android signing directory and its separate recovery copy.
- On September 17 Daniel reported that the app is working well, requested the interface changes described above, and reviewed the local preview. Extended-family access was discussed only for future planning and remains outside the authorized scope.
- The last detailed acceptance snapshot on September 12 still had transaction review and explicit reconciliation outstanding. No later individual results were recorded for reconciled safe-to-spend examples, Stage 2 agreement on both phones, live reconnect, posting changes, or month rollover. The positive general report does not establish each of those checks; verify current state if a subsequent task depends on them.

For local operational details, read `work/stage2-implementation-handoff.md`. Its current-state section supersedes the historical log and the older `work/stage-2-handoff.md`. Do not rerun one-time setup/import helpers. Before recovery or deployment, review the local note about differing SSH and running-service key environments; do not rotate keys or restart to diagnose it casually.

## Provider setup before linking — September 12, 2026

The pre-link Plaid Dashboard showed **Free trial, 0/10 connections used**. Its OAuth institutions tab said automatic bank access required no additional action for this Trial. The allowed Android package list contained `com.familyfinance.app`; USAA was identified as `ins_7`. The institution health dashboard was unavailable for this Trial, and the View details control did not expose further information. Subsequent native Link and real data requests passed as recorded above; the 0/10 figure is a historical snapshot.

Current official references:

- [Trial and billing](https://plaid.com/docs/account/billing/): ten Production Items over the life of the Trial; removing an Item does not recover a slot. Transactions and Balance are available on Trial. Upgrading to a paid plan starts applicable subscriptions on existing Items. No paid-plan upgrade is part of this milestone.
- [Android Link](https://plaid.com/docs/link/android/) and [OAuth](https://plaid.com/docs/link/oauth/): register the package name and pass `android_package_name`; do not pass a web `redirect_uri` for the native Android SDK. USAA consent may need renewal after 18 months. No new domain is required.
- [Balance](https://plaid.com/docs/balance/): `/accounts/balance/get` refreshes balances; `/accounts/get` returns cached data. We initialize **Transactions only**, then use Balance on the same Item. Auth/routing/account-number retrieval and money movement are unnecessary.
- [Transaction states](https://plaid.com/docs/transactions/transactions-data/) and [Sync API](https://plaid.com/docs/api/products/transactions/): posting can change an ID, date, or amount. Pending removal and posting may span pages. Pagination must restart from the original cursor if the dataset changes during pagination.
- [Android SDK releases](https://github.com/plaid/plaid-link-android/releases): retained the existing tested 5.5.2 integration for this milestone; upgrading to 6.x changes the SDK lifecycle API and compile SDK and is separate work. Daniel subsequently confirmed physical-device USAA OAuth return.

The Trial rules were checked again on September 13: an Item is a bank connection that can contain multiple accounts; refreshing an existing Item does not create another Item, and Trial API calls to existing Items are not capped. The published rules did not state an expiration date, which is not a guarantee of perpetual free access. See [Plaid's Trial explanation](https://support.plaid.com/hc/en-us/articles/39994173227159-What-is-the-Plaid-Trial-plan); recheck current terms before expanding usage.

## Runtime and preservation

Keep the same Render service, disk, `FF_DB_PATH`, `FF_ENCRYPTION_KEY`, setup code, household IDs, users, passwords, and Android signing files. Do not reset, reseed, regenerate secrets, or uninstall the phone app. Schema 3 adds sync/reconciliation state, refund allocations, and a transaction-to-month view. Existing accounts and transactions retain their IDs. Startup creates an encrypted backup and verifies a disposable restore **before migration**.

On September 12 fresh encrypted backups were created and restored on Render before deployment and before the user-requested budget import. The authorized offsite downloads have matching SHA-256 verification under ignored `work/offsite-backups`. The hosted database moved from schema 2 to schema 3 during deployment with preexisting data preserved. Take a fresh verified backup before future migrations or operational data changes. The signing directory remains `work/private-beta-signing`; the build script refuses to create a replacement key or password.

The initial rollout deployed reviewed Stage 2 code with linking disabled, verified health/readiness and household preservation, then enabled the following settings together. These settings are already applied to the existing service; this is a reference for future authorized deployment or recovery. Enter secret values directly in **Render environment settings**, never in chat:

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

Leave the existing encryption/setup keys and mock coach configuration intact. `render.yaml` intentionally retains the disabled default; do not resync its Sandbox defaults over a live connection. Auto-Deploy was verified off and Blueprint Sync paused during the September 12 rollout. Recheck these settings before a future deployment.

The live client refuses redirects, uses a fixed Production hostname/API version, and returns only sanitized errors. Tokens are encrypted and persisted immediately after exchange, before later account/transaction requests. One Item per household is supported; reconnect uses update mode instead of exchanging another public token. Two spouses linking the same shared USAA accounts separately would duplicate cash and consume Trial slots, so only link once. Additional separate USAA logins require a separately reviewed account-deduplication design.

## Financial behavior

- New bank accounts start excluded. Compare the USAA accounts and explicitly include the checking/savings accounts that fund household spending. Exclude any manually entered copies. Connected balances cannot be manually overwritten.
- Bank account ownership is household-wide. Transaction dates determine monthly review and spending; accounts are not moved or duplicated at rollover. History outside an existing budget month stays stored and appears when that month is created. Historical screens show the latest saved bank cash, not a historical bank balance; live safe-to-spend is restricted to today's current month.
- Sync applies complete added/modified/removed batches and the cursor atomically. Pending-to-posted updates keep local identity and audit history. A changed split or posting month requires review; removed transactions stop affecting the budget. Removed transactions that reappear return for review without resurrecting old allocations.
- Transfers require explicit **Mark as transfer** / exclusion. Incoming pay is reviewed and entered in the income plan by a person; imports do not automatically increase planned income. A posted refund can explicitly credit one active category in its transaction month, once. Remove category assignment to undo a refund. Amount/date changes and ignoring the transaction clear that refund allocation, retaining audit events. Cross-month refunds credit the month received, not the original purchase month. Partial refund splits are outside this milestone.
- Upcoming bills are drawn across household budget months before the next payday. Safe-to-spend requires the payday's month to exist, so plan the next month before crossing into it. Imported bill payments do not automatically mark planned bills paid: confirm them to avoid reserving cash twice.
- Safe-to-spend requires explicit monthly reconciliation, reviewed and categorized (or excluded) outflows, fresh available balances, a successful balance and transaction download within 15 minutes, and complete transaction history whose last bank update is within 24 hours. These are conservative application limits, not a claim that Plaid transactions are instantaneous. Unknown balances, missing included accounts, failed sync, or stale/incomplete history block the spending decision. Category remaining and real included cash after bills still both constrain the answer.
- Refresh household data reads saved backend data. **Sync bank data** makes user-initiated Balance/Transactions calls; the interface update also runs those calls when the user checks safe-to-spend. There is no webhook endpoint, background worker, paid Transactions Refresh call, or automatic polling. The updated dashboard shows the last bank-sync timestamp; Settings displays bank and download timestamps. Complete bank history, reviewed spending, and explicit reconciliation remain required even after a successful sync.

## Deployment and real-data acceptance checklist

This is the reusable rollout checklist. Consult the dated current handoff above for completed work; do not repeat setup, bank linking, or data imports merely because an item appears here.

1. Obtain Daniel's commit approval; open the milestone PR against main. Merge requires separate approval. Deploy only the approved code to the existing service after a fresh verified backup.
2. Verify Blueprint Auto Sync is off and confirm `/health`, `/ready`, authenticated existing household access, and unauthenticated 401 responses. Configure production values as above without changing recovery secrets.
3. For the original Stage 2 rollout, `scripts/build-private-beta.ps1 -BackendUrl https://family-finance-beta.onrender.com` produced `work/releases/family-finance-stage2.apk`, version `0.6.0-stage2`, code 3, with the original certificate. For the interface update, follow its delivery notes: the source version is now code 4, and the script still uses the old output filename. Preserve the historical APK before any authorized release build. Install using the same signing key as an update after the reviewed backend is deployed.
4. One spouse opens Settings → Connect USAA with Plaid, selects USAA, and completes USAA's own sign-in/consent. Bank credentials are entered only in the bank/Link flow. Confirm OAuth returns to the app. Select the shared checking/savings accounts once.
5. Sync until history is complete. Compare account masks and both current and available balances directly with USAA. Compare recent posted and pending transactions, dates, amounts, transfers, refunds and duplicates. Record mismatch findings without copying account numbers or raw provider payloads into Git or chat.
6. Review/categorize outflows, explicitly exclude transfers and duplicate manual spending, apply genuine refunds, record received income, and mark already-paid bills. Include the intended accounts. Confirm reconciliation in Settings only after the comparison passes.
7. Test an in-budget and an over-budget purchase, cash after upcoming bills, and next-payday days against USAA and the household plan. Verify both phones agree after refresh. Test failed sync and reconnect without another Item, posting changes, and a later month rollover. Preserve existing household edits and logins after restart.

Native USAA linking, real imports, and the user's bank-data comparison passed. The remaining individually unrecorded acceptance checks are identified in the current handoff above; do not infer them from synthetic tests.

## Historical implementation verification — before rollout, September 12, 2026

The following records the state at commit approval. Deployment, native linking, and bank-data comparison occurred afterward as recorded in the current handoff.

- Final full backend suite: **210 passed**, including 25 stage 2 regressions and the real Waitress HTTP bank smoke with synthetic provider data. The schema 2-to-3 migration test preserved every existing household table row and session.
- Android: **38 unit tests passed**; debug and signed release builds passed. The final APK is code 3 / `0.6.0-stage2`, configured for the existing HTTPS backend. Both APK signatures verified and the stage 1/2 certificates matched; existing signing key/password file contents were unchanged. APK SHA-256 and signing evidence are in ignored `work/stage2-apk-verification.json` and `work/stage2-signing-preservation.json`.
- Both existing HTTP/persistence smokes passed, covering shared edits, financial totals, authorization, restart, encrypted restore and fresh login after restoration. Physical device OAuth and USAA reconciliation have not run.
- Verified live service: health/readiness 200, unauthenticated budget access 401, setup closed, bank linking still disabled. No live code/configuration migration or household mutation was performed. The fresh offsite archive is `work/offsite-backups/manual-offsite-20260912T185432Z-4fb407e3.ffbackup`; its disposable restore and download hash matched.
- Secret/junk scan: 100 repository candidates; no known private signing/SSH material, generated-file paths, or encoding issues. The only token-shaped regex match was the pre-existing synthetic Sandbox redaction fixture. `git diff --check` passed.
- Resolved verification issues included the legacy migration fixture's version count, a temporary Windows encoding error during Android edits, and stale account values on the reconciliation screen. No unresolved test failures. Existing Gradle/SDK deprecation notices remain.
- Daniel approved committing stage 2 and opening its PR on September 12, 2026; merge needs separate approval. Render Dashboard needs sign-in to independently check Blueprint Auto Sync and configure rollout.
