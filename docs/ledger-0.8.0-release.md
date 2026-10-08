# Ledger 0.8.0 release handoff

## Status

Daniel approved preparing the signed APK and publishing the branch/PR on October 8, 2026. Release candidate: **`0.8.0-ledger` / version code 8**, backend schema **7**, branch **`codex/ledger-budget-workflow`**, based on `main` at `9dffab8` (merged PR #23). Publication details will be recorded below after the commit and PR are created.

**Backend deployment and PR merge are pending. Deploy the matching backend before installing this APK.** This handoff records a prepared release, not a production deployment. Do not archive away the APK or signing materials when closing the chat; they remain in the original project workspace.

## User-visible changes

- Dashboard month/year is prominent with previous/next arrows. An absent next month offers copying the current plan or cancelling; last sync remains beside the month. Income, budget, transactions, bills, funds and other cards with destinations open their related pages. Budget-month IDs stay internal.
- Spending Check is removed from Android, calculations, coach explanations and new check alerts. Authenticated retired routes return HTTP 410. Existing historical records remain. Dashboard cash after upcoming bills/reserves, days until payday and category balances remain backend-calculated.
- Transaction Detail can move an item to another budget month while retaining its bank date and cash effect. A preview explains category/income changes; the choice survives later bank sync. Missing ordinary mappings return activity to review; unsupported Provision Fund mappings are blocked to preserve reserve accounting.
- Deposits apply to existing or newly created planned income, adding to received amounts once. Relinking, unlinking, ignoring, refunds and bank corrections update the linked totals without replacing existing manual receipts. Deposits do not offer Split; spending shows Split after Assign category and before Ignore/exclude.
- The approved gold coin is enlarged/recentered in Android's adaptive foreground so the circular icon contains gold and the complete L, without the green sliver. The original bitmap and themed icon are retained.
- Opening or returning to the app checks whether either balance or transaction downloads are three hours old or from an earlier household calendar day. The shared backend serializes normal imports and avoids duplicate spouse requests. There is no background timer or automatic fresh-bank-data request. Failed automatic attempts pause for one minute; an explicit Retry can run immediately.
- The regular Sync button is removed. Progress and a failure Retry appear beside Last sync while the dashboard stays usable. A failure retains the previous successful timestamp, and completion does not replace an unsaved form. Reconnect USAA and Request fresh bank data remain in Accounts / Settings.
- The same screens, API contracts and financial logic operate in isolated demo mode. The banner, discard on exit and fresh data on reentry remain intact.

## Prepared Android artifact

- File: `work/releases/ledger-0.8.0.apk` in the original `family-finance-app` workspace.
- SHA-256: `44A05B28E7AF266E00056A6C3C6A1268BBB4EAF8510B8A9F40F80270BDD43D26`
- Size: **7,713,585 bytes**.
- Companion checksum: `work/releases/ledger-0.8.0.apk.sha256`.
- Package: `com.familyfinance.app`; version `0.8.0-ledger`, code 8; display name Ledger.
- Backend: `https://family-finance-beta.onrender.com`.
- Signing certificate SHA-256: `bd14a956d7ee70ce700ad10ec8b1ddbdeceb92d34a1987e0dba3e41b044ca648` (matches 0.7.1 and the original update key).
- Verified: signature, production URL in the packaged code, non-debuggable release, disabled cleartext/backup, adaptive/themed icon references and packaged coin. The original signing materials and all seven previous APKs are unchanged.
- Build and verification evidence is retained under ignored `work/ledger-080-*`. APKs, signing material, runtime databases, logs and attachments are excluded from Git. The APK is delivered as a local file, not committed to the repository.

The existing signing material lives under ignored `work/private-beta-signing`. Never regenerate or share it with the APK. The task's `work/build-ledger-080-release.ps1` and `work/verify-ledger-080-release.ps1` reuse it, refuse overwriting the versioned APK, and verify preservation. Their release build invokes `android/gradlew.bat --offline assembleRelease -PbetaBackendUrl=https://family-finance-beta.onrender.com` with the existing key/password supplied privately through the established `FF_ANDROID_*` environment variables. Preserve the signing directory in the existing encrypted backup process.

## Verification

- Full backend suite: **336 passed**. This includes schema upgrades, transaction accounting and duplicate prevention, access boundaries, automatic-sync timing/concurrency/failure recovery, real/demo isolation and the maintained `backend.smoke_demo` workflow.
- Android: **106 unit tests passed**, debug/instrumentation APKs built, and **4 native session-storage tests passed**. Unit tests and builds were repeated after changing the release version to code 8; the backend source is unchanged from its passing full run.
- Native synthetic walkthroughs: dashboard month navigation/copy cancellation/card destinations; transaction move/cancel/round trip; linked deposit existing/new income; no deposit Split; circular launcher render; automatic cold-open sync; recent foreground return skipping provider work; failure retaining dashboard/timestamp; successful Retry; unsaved income form retained through delayed sync.
- Real → demo → real → fresh demo passed. Settings recovery controls and synthetic fresh-bank-data requests work. The maintained backend smoke covers Provision Funds, rejected cross-environment tokens, unchanged real data and zero outbound provider calls. Seed data remains compatible with schema 7 and real domain operations.
- Verification fixes included the Android resumed lifecycle for quick app switches, historical migration fixtures, null import-hint handling and preserving pending-spending review state. Temporary test helpers were corrected for actual labels/HTTP status and do not ship in the app.
- Source diff/secret/junk checks are required again on the staged release candidate before publication. The unchanged fake Plaid-shaped token in the existing redaction test is a reviewed test fixture.
- Signed-release smoke passed on a disposable Pixel emulator: installed signed 0.7.1, updated in place to signed 0.8.0, verified code 8 and the login screen, and checked for fatal crashes (none). Wi-Fi and mobile data were disabled; no physical phone or live household was used. Physical-phone installation and live USAA transaction correctness remain unverified.

## Backend migration and rollout

This release uses the existing service and database; it must not reset the household, rotate the encryption key, replace the USAA connection, enable products or upgrade any paid plan.

1. With deployment authorization, inspect the existing Render service `family-finance-beta` (`srv-dai4ksu1egvs73dfob4g`) and its deployed commit. The last recorded deployment is `96ce24f438a16d668775bc02209139dc545ca8bd`, schema 5, on September 29. Reverify rather than treating that dated snapshot as current. Preserve its production/Trial settings, original encryption key, database/disk, paused Blueprint Sync and manual deployment configuration.
2. Create and restore-verify an encrypted backup on the existing host before upgrading. `backend.app.hosted.prepare_application` also creates and validates its own pre-upgrade archive before migrations. Keep credentials and archives private; use the existing [recovery runbook](stage-1-private-beta.md).
3. Deploy the reviewed implementation commit from this PR to the existing service. Schema 6 adds transaction budget-month overrides, unique income links and the received-income view; old received amounts remain manual receipts. Schema 7 adds successful-sync/automatic-attempt timestamps and backfills completed checks from the older balance/download timestamp. Existing bank cursors, tokens, cash and budget records are preserved. Migrations are transactional and idempotent.
4. Verify the deployed commit, schema 7, database/foreign-key integrity, household counts, budget/account/transaction totals, preserved manual receipts, original key and recoverable bank tokens. Check `/health` and `/ready`, plus unauthenticated guards. Do not trigger a live bank request as a substitute for the data-preservation check.
5. Run isolated synthetic demo smoke on the deployed code without accessing the live household database/providers. Then install this APK as an **update** over the prior signed Ledger app. Do not uninstall the household's app or clear its data. Confirm normal login, month navigation, automatic sync/status, transaction planning, and real/demo switching on the phones.
6. Record the deployment ID/commit, timestamp, verification result and any unverified phone/live-bank checks in this document. PR merge requires Daniel's explicit approval; publishing a PR does not authorize merging it.

Do not roll a schema-5-only backend back onto a schema-7 database. If recovery is needed, use compatible code or restore a validated pre-upgrade archive to a separate file through the runbook, preserve the current database and reconcile any activity created after that backup before switching. Never overwrite the live database blindly.

## Publication and remaining work

- Signed APK prepared and verified; release commit/PR publication in progress.
- Backend deployment, production migration verification and physical-phone installation: pending.
- PR merge: pending explicit approval.
- Prior PR #23 is already merged into `main`; its old open-PR wording in the current docs has been corrected.
