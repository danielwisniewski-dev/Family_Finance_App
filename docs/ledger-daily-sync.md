# Ledger branding and daily bank sync

Android `0.7.1-ledger`, version code 7. Daniel authorized committing/publishing the branch, backend deployment and signed APK delivery on September 29, 2026. Implementation commit `96ce24f438a16d668775bc02209139dc545ca8bd` is deployed; the signed update is verified and ready to install. [PR #23](https://github.com/danielwisniewski-dev/Family_Finance_App/pull/23) is open and unmerged; merge still requires separate approval. The September 23 deployed Provision Funds release (PR #22, merged at `d5e524a`) is the baseline. No schema change or data migration was needed.

## Name and icon

- The launcher and app loading title use **Ledger**. Plaid Link's client display name also becomes Ledger.
- Gold embossed L coin on deep green, based on Daniel and Kara's selected concept 4. Adaptive foreground/background layers support launcher masks; a separate monochrome coin/L mark supports themed icons.
- Keep `com.familyfinance.app`, saved preferences, encrypted session storage, the bank connection and original signing key. Install the eventual signed release over the existing app.
- The transparent foreground was derived from the approved comparison sheet with the built-in image-generation tool. Final prompt: "Extract only concept 4, Ledger Coin; preserve the angled embossed gold serif L coin, remove all labels and backgrounds, center it on a square transparent canvas with Android safe-area padding." The generated PNG is bundled in `android/app/src/main/res/drawable-nodpi/ledger_coin.png`; the adaptive resource adds padding. The monochrome mark is a native vector resource.

## Set aside money

Provision Funds contributions now use their own bank-cash readiness check. They do not require next month's budget, clearing the transaction review queue, or monthly bank reconciliation. The current month's fund/category, current live budget month, upcoming payday, connected backing account, positive amount and recorded cash protections still apply.

Available cash must cover existing positive reserves and the proposed earmark. Included household cash must also cover recorded bills before the next payday, including any already entered in another month; a funded bill is not reserved twice. No contribution transfers bank cash or records an expense. Transaction categorization can subsequently change a fund balance; the form explains this and that unentered bills cannot be included.

The phone first submits the saved contribution request. A backend `400 bank_sync_required` confirms it was not applied. Android then syncs balances and transactions and retries once with the same idempotency key. A successful replay is returned before any freshness requirement, so confirming an already-applied request does not depend on bank availability. Lost responses retain the saved request. Releases and moves do not acquire a bank-sync prerequisite.

## Same-day sync

Balance checks, transaction downloads and individual backing/included-account balance timestamps must fall on the current household calendar day. `FF_TIMEZONE` determines that day; hosted mode defaults to America/New_York. UTC and offset timestamps are converted before comparison, SQLite's unzoned timestamps are interpreted as UTC, and future/missing/malformed timestamps are rejected. This is a calendar-day rule, not a rolling 24-hour download window.

The backend's `sync_required` bank-status flag lets Spending Check skip a redundant sync. Older backend responses without that flag retain automatic sync. Daily freshness does not skip sync errors, unknown available balances, incomplete history, or the existing limit of 24 hours since the bank's transaction update.

Spending Check still requires review, reconciliation and the next payday's budget/bills when crossing months. It still uses both category remaining and cash after bills/reserves, and includes the required after-bills/until-payday phrase. The relaxed review/planning prerequisites apply only to setting aside money.

## Login and first-time setup

Normal unauthenticated launches open a login screen with username/email, password and a First-time setup button. Backend URL and budget month ID are saved on the separate setup page. Existing saved settings and encrypted sessions remain compatible; Accounts / Settings retains its connection controls.

The setup page explains that **Save and check household setup** asks whether the server already has a household. An initialized server returns a message directing the user to login. A new server opens the existing private household-creation flow, with its setup code and authorization requirements intact. The check itself creates and resets nothing. Login no longer makes an automatic setup-status request, and connection errors direct users to the setup page without displaying the server URL.

## Demo mode

This same release adds **Demo mode** in Accounts / Settings, with a persistent **DEMO DATA** banner and a funded fictional household in the normal app screens. Sync uses a synthetic bank; financial actions use the shared backend rules. Leaving demo mode discards its changes, restores the real session/month, and makes the next entry fresh. There is no scenario selector or Reset demo button.

The existing service hosts a separate disposable SQLite context per demo session, with isolated tokens and a mock coach. No additional paid service or real bank/AI call is part of the feature. Sessions are bounded, expire and do not survive backend restart. See the [demo feature, lifecycle and maintenance contract](demo-mode-plan.md) for protocol details, parity obligations, release checks and current verification. Future app/API/schema/financial-rule changes must keep the sample household and its normal actions working too.

## Delivery and verification

The backend deployment and signed Android build completed under Daniel's September 29 authorization. Local verification below used synthetic data; rollout verification is recorded separately. The existing production database, encrypted recovery, Plaid connection and signing identity were preserved. Installing the signed APK on the household phones remains the final user step; physical-phone installation and household login/demo switching after deployment have not been observed.

Verification covers local-midnight/UTC/DST boundaries, stale and failed sync, unknown balances, unreviewed spending at month end, recorded next-month bills, reserve limits, authenticated sync/retry, identical request keys, and replay after rollover.

September 29 local results before the demo addition (historical; demo-mode final verification is tracked separately below):

- Full backend suite: 300 tests passed. Android: 107 tests passed; `assembleDebug` passed.
- Disposable emulator: a contribution with unreviewed spending, no reconciliation and no next-month budget automatically synced and saved once. A second contribution after app restart reused that same day's sync, with no additional bank calls. All amounts and bank responses were synthetic.
- The Ledger label and gold coin icon were inspected in the Android launcher; the contribution form and saved result were inspected on the emulator. Physical phone installation is unverified.
- Existing two-spouse HTTP provision smoke passed: contribution/retry, categorization, reserve protection, carryover and persistence.
- Initial test/helper failures were corrected: expected HTTP status and included-account setup in two synthetic cases, duplicate Android response-sequence helpers, and native smoke call-order/launcher-gesture assumptions. No unresolved app or test failure remains.
- Login follow-up: full backend suite again passed all 300 tests; Android passed all 107 tests and `assembleDebug`. The emulator verified a clean login without an automatic setup request, saving/restarting, invalid URL/month rejection, Back discarding edits, new/existing household checks without creating data, recovery from an unreachable setup server, incorrect credentials, successful login and an encrypted session surviving restart. Visual inspection caught duplicate setup labels; these were removed and Android verification passed again.
- Secret/junk scan covered all 26 changed/new candidates, including the intentional PNG asset; no findings. `git diff --check` passed. Runtime databases, screenshots, logs and build output remain ignored.

Demo addition final local verification: all 324 backend tests, 111 Android unit tests, 3 emulator session-storage tests, debug build and the demo API smoke passed. Native screens verified a contribution, Spending Check, Sync/review queue, restart persistence, real-account restoration, fresh data on reentry and expired-session recovery. Review added safe cleanup after server crashes and retryable deletion. The combined 42-file secret/junk scan and `git diff --check` passed. See the [demo verification record](demo-mode-plan.md#current-verification-record) for coverage and maintenance requirements.

## September 29 rollout record

- Signed APK ready: `work/releases/ledger-0.7.1.apk`, version `0.7.1-ledger` / code 7, 7,707,849 bytes. SHA-256: `97D62DEA6ED09B187115C7D78DB0EBBA9988B0DFD9FD6EC5E690D9DD8ACF104B`. This ignored artifact remains in the original `family-finance-app` project workspace, not the separate documentation closeout worktree.
- The APK matches the original signing certificate used by `0.6.2-warmth` and `0.7.0-provision`. Package, Ledger name/icon, live HTTPS backend and non-debuggable configuration passed inspection. Original signing materials and all six prior APKs are unchanged. Install as an update over the existing app; physical-phone installation remains unverified.
- Existing-host preflight at 20:20 UTC passed: one hosted process/instance, unchanged Starter service with 0.5 CPU and 512 MiB memory limit, about 111 MiB in use, about 48.6 GiB free writable temporary storage and 812 MiB free on the existing persistent disk. This is a capacity snapshot, not a load/scaling guarantee. The attached disk does not support adding instances; no service, disk or plan upgrade was made.
- Preflight verified schema 5/database integrity, the running process's encryption key, preserved Production/Trial settings and recoverable bank tokens. A fresh encrypted backup was created and restore-verified on Render at 20:21 UTC; no archive or key was exported. The saved dashboard recovery key was privately compared and matched the valid running-process key. Auto-Deploy is Off and Blueprint Sync is paused; no environment/resource configuration was changed.
- Implementation commit `96ce24f438a16d668775bc02209139dc545ca8bd` was pushed on `codex/ledger-daily-bank-sync`. [PR #23](https://github.com/danielwisniewski-dev/Family_Finance_App/pull/23) is open, mergeable and unmerged; no CI checks are configured. Local verification supplies the recorded test evidence. Merge requires separate approval.
- [Render deployment `dep-dau1ueflk1mc73dcbdrg`](https://dashboard.render.com/web/srv-dai4ksu1egvs73dfob4g/deploys/dep-dau1ueflk1mc73dcbdrg) deployed that exact implementation commit. It started at 20:27:37 UTC and became Live at 20:28:19 UTC on September 29 (42.5 seconds). The existing configured branch, service, disk and environment were unchanged; no additional hosted resource or paid-plan upgrade was made.
- Post-deployment verification at 20:37 UTC confirmed the exact commit, schema 5/integrity, unchanged original encryption key and provider configuration, recoverable bank tokens and Production/Trial settings. Every database table matched the fresh startup backup (`changed_tables=[]`), including household and authentication data. `/health` and `/ready` returned 200 with `ok=true`; unauthenticated `/budget-months`, `/demo/start` and `/demo/budget-months` returned 401.
- The deployed Linux runtime passed `backend.smoke_demo` and both ownership/crash-orphan cleanup tests in an isolated child process using a disposable Application and synthetic data. Temporary data was removed; the check did not access the live household database or call providers. This supplements the actual HTTP health/authentication checks; it is not verification of a household login or demo-mode switch against the live service.
- Physical-phone installation and household login/demo switching after deployment remain unverified. Any subsequent documentation-only closeout commit does not change the deployed implementation and needs no additional backend deployment.
