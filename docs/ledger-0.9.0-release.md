# Ledger 0.9.0 release

Android `0.9.0-ledger` (version code 9) targets the matching backend at schema 9. This candidate is based on `main` at `02ca1a6`, the merge of PR #24.

## What changed

- **Daily reminder** in Accounts / Settings is off by default. When enabled, it starts at 7:00 PM and can be set to another local time. The device can display one reminder on a day without a signed-in visit, around the chosen time. Grant Android's notification permission when prompted. Each device tracks its own visits and demo uses temporary settings.
- **Payday schedules** in Accounts / Settings are shared by the household. Add one or several weekly, every-two-weeks, twice-monthly, or monthly schedules. Choose a start date and move individual occurrences for exceptions. Existing one-time paydays still count. Both the dashboard and Provision Funds use the earliest upcoming date. Income Planning still governs monthly dollar amounts.
- **Match bill budget to an expense** starts with editing a bill and choosing its dedicated budget category. When you assign or confirm a single posted expense in that category, Ledger offers to match both the expected bill and the planned category amount to the payment. Keep current amounts saves the expense without changing either plan. Ledger skips the prompt for regular categories, pending payments, splits, and categories with multiple expenses. Provision Fund contributions and bill paid status use their existing controls.
- **Bills and Paydays** shows bold names and dates, dividers between entries, and side-by-side Edit and Delete controls with confirmation for deletion. **Transaction Review** shows Choose multiple transactions at the top when there are eligible entries. The **dashboard** lists an overdrawn fund category once while keeping separate reserve warnings.

## Upgrade and installation

1. After review and deployment approval, verify the existing Render service, its running commit and schema, and the original recovery key. Make a fresh encrypted backup and verify its restoration and bank-token recovery into a disposable database. Keep the current service, disk, provider configuration and existing household.
2. Deploy the reviewed backend. Schema 8 adds household schedules and date overrides while preserving manual payday rows. Schema 9 adds an optional bill-to-category link. Existing bill amounts and category plans are preserved and existing bills start unlinked. The app carries explicit links forward when it copies budget months.
3. Verify the running commit, schema 9, SQLite integrity, foreign keys, and pre-existing financial rows against the backup. Check service health and protected routes. Synthetic smoke can exercise banking and budget workflows without calling the live provider.
4. Install `work/releases/ledger-0.9.0.apk` from the original project workspace as an update to Ledger after the backend is ready. Preserve the original signing key and existing installation so the app can retain device state.

Do not run an older backend against a database with a newer schema. To recover, preserve the current database first. Use a schema-compatible repair, or restore the verified pre-upgrade archive to a separate file and reconcile any intervening activity before switching.

## Verification

- All 343 backend tests and 109 Android unit tests passed. Debug, instrumentation, and signed release builds passed, as did five native reminder and session-storage tests.
- The standalone synthetic demo smoke checked dashboard cash and category balances, fresh bank data, Provision Funds, household payday changes, bill budget matching, rejected cross-environment tokens, and fresh demo data. It verified that demo edits left the synthetic real database unchanged and made no live provider calls.
- On the disposable emulator, the real household's Transaction Review put bulk selection at the top and Android Back returned from the picker. Its lower bill payment showed the expected amounts. Dismissing the prompt preserved the existing amounts. The new Edit and Delete buttons were side by side and cancelling Delete preserved the bill.
- The Android demo accepted a higher payment and updated the bill and category amounts together. One loopback connection error on exit recovered through Retry dashboard. The real household's bill was unchanged and fresh demo entry restored the original expected amount.
- Earlier disposable-device checks covered reminder permission denial and recovery, changing time, demo settings isolation, schedule creation, and one occurrence moved and restored on fresh demo entry. Physical-phone reminder timing, reboot delivery, and live household and bank behavior remain unverified.

## Signed APK

- File: `work/releases/ledger-0.9.0.apk`. SHA-256: `d59bf29aa535560072bf446cc5b44739dbd82919b1b6c800d8101c09be9ea201`.
- Package `com.familyfinance.app`, display name Ledger. The verified signing certificate matches 0.8.0. The release embeds the existing HTTPS origin, disables debugging, cleartext traffic and backup, and includes the Ledger launcher resources. Original signing materials and previous APKs passed preservation checks.
- A disposable offline emulator accepted the signed 0.8.0-to-0.9.0 in-place update, reported code 9 and launched without a recorded crash.
- Diff and source secret and generated-file checks passed across the 34 staged files.

Production deployment and physical-phone verification are pending separate approval and acceptance. The APK, signing files, databases and runtime evidence are kept outside Git.
