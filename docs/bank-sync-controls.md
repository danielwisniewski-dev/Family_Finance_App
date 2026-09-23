# Bank sync controls

Part of the provision funds release authorized for commit and deployment September 23; rollout is pending.

| Location | Action | Behavior |
| --- | --- | --- |
| Dashboard | Sync | Updates account balances and imports transactions Plaid already has, then returns to the dashboard. Does not request a new bank transaction extraction. |
| Accounts / Settings | Request fresh bank data | Explicitly asks Plaid to retrieve newer USAA transactions, then imports the available changes. |
| Accounts / Settings | Reconnect USAA | Opens Plaid Link in update mode to renew or repair the existing bank authorization. |

The existing Refresh household data action reads saved app data. Automatic checks before safe-to-spend continue to use normal balance/transaction sync. They never request Transactions Refresh.

All normal Sync entry points return to Dashboard after the import and screen-data reload succeed, including the follow-up sync after Reconnect USAA and the Sync shortcut on the fresh-data result.

## Transaction display and review

Transactions display newest date first, with descending transaction IDs breaking same-day ties. The review queue puts transactions with assigned categories first, including active splits and categorized refunds, then transactions without assigned categories. Both groups retain newest-first ordering. Suggested categories and superseded assignments do not count as assigned; uncategorized incoming transactions stay in the second group. Android applies the same ordering when connected to an older backend.

Confirming a transaction as reviewed saves its review status and audit history without creating a notification. Existing notifications are retained. Marking a transaction unreviewed and important changes such as recategorization still notify the household. The follow-up check exposed an Android display issue when a merchant name is explicitly null; those transactions now display their imported name.

## Refresh behavior

`POST /plaid/refresh` requires authentication and ownership of the existing Item. The enabled, encrypted production runtime is required. It uses that Item's stored token and never creates another Item, exchanges another public token, or enables another product.

The current Plaid Trial bundle includes Transactions Refresh. A refresh of an existing Item does not create a new connection. No paid-plan upgrade is part of this change. See [Plaid Trial documentation](https://plaid.com/docs/account/billing/#trial-plans).

The server records the request before contacting Plaid. Both spouses and restarted workers share a 60-second cooldown after the response; an unfinished request has a two-minute lease to cover the provider timeout. Uncertain responses keep the cooldown and show uncertainty. The phone never automatically repeats the actual refresh request.

After requesting fresh data, Android updates balances once and imports transactions. Empty imports are retried after 5, 10, and 20 seconds, using transaction sync only. If USAA is still updating, the result explains that later transactions may still arrive and offers Dashboard Sync. These are bounded foreground checks; no webhook, background worker, or periodic refresh is added.

A newer bank timestamp does not prove every transaction has reached Plaid's sync stream. The backend records `checked` only after observing an update at or after the request, newer than the previous bank timestamp, and successfully importing the available history. The app still retries empty imports and never claims all USAA transactions are present. Plaid's [refresh endpoint documentation](https://plaid.com/docs/api/products/transactions/#transactionsrefresh) distinguishes the refresh request from retrieving transactions.

Plaid currently documents a default per-Item limit of two refreshes per minute; limits can vary. The app's cooldown is deliberately lower. Refresh requests have a 90-second provider timeout because bank extraction can exceed 30 seconds. [Rate limits](https://plaid.com/docs/errors/rate-limit-exceeded/#transactions_refresh_limit)

## Persistence and compatibility

Schema 5 adds request timestamps and status to `bank_sync_state`; existing balances, transaction cursors, provision funds, authorizations, and encrypted tokens are preserved. No refresh is sent by the migration or app startup. Older backends retain normal Sync support; the fresh-data action fails safely when its endpoint is unavailable.

Provider errors remain sanitized. Authorization errors suggest Reconnect; temporary bank/network errors suggest trying later. The existing atomic cursor import handles changes, removals and duplicates. Pagination retries recognize Plaid's current `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` code.

## Verification

Verification uses synthetic provider responses and disposable data. It covers the explicit-request boundary, shared cooldown/restarts, concurrent requests, uncertain responses, timestamp/import ordering, pending versus checked status, rate limits, request redaction, ownership, migration preservation, and normal Sync/Reconnect compatibility. No live refresh or bank authorization was exercised while developing this update.

September 23, 2026, including the transaction-display follow-up: all 289 backend tests and 99 Android unit tests passed, and `assembleDebug` passed. A Windows localhost connection abort in an existing security test passed on its focused rerun, followed by a clean full backend run. Review caught repeated balance fetching during transaction polling; the final flow fetches balances once. The diff check and source secret/junk scan passed. Daniel subsequently authorized commit and deployment; the signed Android release passed certificate and configuration checks.

A disposable Pixel 8 emulator verified Dashboard Sync returns to the dashboard and performs one balance check plus one transaction import with zero refresh requests. Settings shows the two distinct controls and no old Sync button. A delayed synthetic bank update produced exactly one explicit refresh request, one balance check, four transaction imports, and the waiting result with a Dashboard Sync shortcut. Screenshots were inspected. No real bank calls or physical phone changes were made.

The follow-up emulator run verified newest-first history, assigned-category review priority, the imported-name fallback, and confirmation advancing to the next assigned transaction. Confirmation persisted the review flag without changing the household notification list. The disposable server and emulator were stopped after verification.
