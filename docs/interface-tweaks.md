# Interface update — September 2026

Android version `0.6.1-interface` (code 4) builds on Stage 2. This update requires no database migration or household reset. Preserve the existing production database, Plaid connection, encryption key, and Android signing key. The existing Stage 2 documentation closeout belongs in this change set.

## Dashboard

- Check-in streak at the top, with a personal best and 40 original daily encouragement messages.
- Existing saved streak seeds the personal best; older historical peaks were not stored and cannot be recovered. Streaks remain scoped to the person, household, server, and device.
- Compact month and local-time bank-sync timestamp; removed redundant identity, balance, and warning boxes.
- Cash cushion status heads the cash card. The Transaction Review card opens the review queue.

## Transaction review

- Category choices start with an empty prompt and list active categories alphabetically.
- Explicit manual assignment also marks the transaction reviewed. Existing rule assignments, splits, and incoming transactions can still be confirmed when review is needed.
- Select transactions opens a checkbox list and a shared category picker. Each selected transaction is reloaded before assignment; processing stops on a detected change or failed save. Completed saves are reported; this is not an atomic batch or an automatic retry after an uncertain response.

## Merchant rules and notifications

- Transactions and Transaction Review link to Merchant rules, listed alphabetically with Edit and Delete controls. Deleted rules can be displayed separately.
- Edit changes merchant text/category for future matches, preserving priority. No existing transactions are changed. Deletion disables the rule and retains history, including rules whose original category has since been archived.
- Initial category assignments, re-saving the same category, and ordinary splits no longer create household notifications. Categorization audit history and financial effects remain intact. Recategorization and other existing significant events still notify. Previously stored notifications are retained.

## Safe-to-spend

- Check safe to spend reads current bank connection status, syncs balances and transactions for each linked connection once, then requests the backend calculation. It uses existing bank-sync APIs and products; it does not reconnect or create another Plaid Item.
- Failed/incomplete sync responses stop the check, with retry, review, and settings actions. Manual budgets with bank linking disabled retain their normal calculation flow.
- Backend freshness, imported-transaction review, explicit reconciliation, active-month, payday, category, and cash checks remain authoritative. Sync cannot force USAA to publish newer transactions or complete initial history. A successful sync can therefore still leave a review/reconciliation/data-availability issue to resolve.

## Delivery

The notification change requires a backend deployment, and the interface changes require an Android update using the original signing key. Verification uses disposable synthetic data; no live financial changes are part of this milestone. Commit, merge, deployment, and phone installation are separate from local verification.

Daniel reviewed the local preview and authorized documentation updates, commit, push, and a GitHub PR on September 17. Merge and production rollout remain pending. Only the debug APK has been built for this update; no new signed release or phone installation is claimed.

The existing release script still writes `work/releases/family-finance-stage2.apk`. Before an authorized release build, preserve that historical Stage 2 APK; verify the new artifact is `0.6.1-interface` / code 4 and matches the original certificate. Do not regenerate signing files, reinstall by uninstalling, relink the existing bank, or reset/reseed the hosted database. Consult the Stage 2 operational handoff before deployment because its SSH/runtime key-environment caveat remains unresolved.

## Verification and local preview

- Full backend suite: **211 passed**. The first run lacked Waitress on its Python path; both affected HTTP tests passed individually after using the existing local dependencies, then the full suite passed.
- Android: **62 unit tests passed**, `assembleDebug` passed. The synthetic API tests cover sync order, duplicate connection IDs, failed/unknown bank status, failed sync, authentication, manual budgets, and backend readiness rejection.
- Native emulator walkthroughs passed for the dashboard, blank/alphabetical category picker, assignment with review, multi-select, merchant-rule edit/delete/cancel with unchanged transaction history, automatic bank sync, and failed-sync retry retaining the request.
- `git diff --check` and secret/junk/encoding scans passed. No live financial data, keys, APKs, databases, screenshots, or runtime helpers belong in the commit. Previous pending documentation changes are retained.

The local review server uses `work/ui_preview_server.py` with a separate synthetic `work/ui-preview.sqlite` database, a fake bank, and a mock coach. These machine-local helpers are intentionally ignored. Its emulator URL is `http://10.0.2.2:8083`; the household is labeled **UI Preview (synthetic)**. Existing preview edits survive a server restart. A fresh checkout can use the README's normal demo seed/API flow; that manual demo does not simulate the live-bank sync path.

An emulator can modify live data if its saved Backend URL points at the hosted service. Check the URL before experimenting; the debug build's default local URL does not override a previously saved address. The supplied local preview never calls the real bank. Review its sample transactions before testing the reconciliation-dependent spending result.
