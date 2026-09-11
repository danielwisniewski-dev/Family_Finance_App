# Stage 1 private beta

Stage 1 prepares secure hosting and Android installation for Daniel and Kara. It does **not** enable live financial imports. USAA linking, sync freshness, account/month rollover, transfer/refund treatment, and reconciliation remain stage 2 launch requirements. Do not treat a fresh stage 1 database as a complete picture of household cash.

## Deployment shape and cost

One Render paid Web Service on a free Hobby workspace, with one 1 GB persistent disk. SQLite runs in the backend; there is no separate database service. The reviewed base price is $7/month compute plus $0.25/month disk, before taxes/usage. The Blueprint creates no AI service, paid workspace, managed Postgres database, or separate worker. Provider billing is ultimately controlled by Render.

- `render.yaml`: one instance, Virginia region, automatic deploys off, `/ready` health check.
- `requirements.txt`: pinned production HTTP server, cryptography, and timezone dependencies.
- Start command: `python -m backend.app.hosted` (Waitress). The old `backend.app.api` server is for local development and refuses hosted mode.
- All durable files live under `/var/data`. Migrations run during startup because Render's pre-deploy job cannot access an attached disk.
- Render terminates HTTPS. The release Android client requires HTTPS and refuses redirects with credentials. Development HTTP is enabled only in debug builds.

Provider references: [pricing](https://render.com/pricing), [persistent disks](https://render.com/docs/disks), [Blueprint specification](https://render.com/docs/blueprint-spec), [Waitress settings](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html).

## What the security changes do

- Hosted first-run setup requires a random private setup code and exactly two users with passwords of at least 12 characters. Setup closes atomically once the household exists.
- Passwords use salted PBKDF2-SHA256 with 600,000 iterations. Existing hashes remain verifiable. Session tokens are stored as hashes on the server, expire after seven days, and are revoked by logout or a password change.
- Login attempts are limited persistently: 10 per normalized login per five minutes, plus 60 total per minute. Setup and password-change attempts are limited too. Limits survive server restarts and do not rely on spoofable forwarded IP headers.
- The Android Keystore protects the AES-GCM session key; stored ciphertext is bound to the backend URL. Old plaintext tokens are discarded and require login. Backups/device transfer of app data are disabled. Release screenshots/recents previews are protected.
- If logout cannot reach the server, Android clears its local session and explicitly reports that server revocation was not confirmed. The server token still expires; changing the password revokes all sessions.
- Hosted mode fails closed without separate setup/encryption secrets. A stored encrypted key check detects a changed or missing encryption key even when no bank tokens exist.
- Plaid token values are encrypted when a key is configured. Existing plaintext tokens require the explicit offline upgrade command below. No raw tokens, references, keys, password hashes, or session hashes are added to API responses.
- Stage 1 hosted mode rejects production Plaid, bank secrets, and a live AI provider. Hosted Plaid endpoints are denied; the release build hides bank-linking buttons.
- Financial dates default to `America/New_York` in hosted mode. API responses are not cached. Production request bodies are capped at 256 KiB; request headers, idle connections, and worker concurrency are bounded.

## Render handoff

Account creation, Hobby workspace, payment method, GitHub connection, and account security are Daniel's completed preparation. No running service is implied by those steps.

1. Review the stage 1 diff and verification results. The repository requires Daniel's approval to commit; merge requires separate approval. The service must point to a branch containing the reviewed changes.
2. In Render, choose **New → Blueprint**, select this repository and the approved branch, and use `render.yaml`.
3. Verify the summary shows **one $7 service and one 1 GB disk**, the free Hobby workspace, and no additional services. Create the service after reviewing that concrete configuration.
4. Render generates `FF_SETUP_CODE` and `FF_ENCRYPTION_KEY` separately. Save the encryption key in a secure password manager outside Render before entering important data. Retain it with encrypted database backups; replacing it will not recover existing data.
5. Confirm `/health` and `/ready` return `{"ok": true}` over the assigned HTTPS address. `/budget-months` without login must return 401. No credentials are needed for those checks.
6. Install the signed APK on both phones. Enter the assigned HTTPS URL in the app. On one phone, use the private setup code to create both household users; choose the passwords directly in the app. The other phone then signs into the same household. The setup code is not saved on the phone.
7. Add a starter budget, categories, bills, and payday dates. Confirm changes made by either spouse appear after **Refresh household data** on the other phone. Test Wi-Fi and cellular. The stage 1 release does not yet have bank balances or live transactions.

Do not enter Plaid production credentials during stage 1. Neither spouse needs a second Render account. Use the assigned Render hostname initially; no domain purchase is required.

## Backups and recovery

The server takes an encrypted consistent SQLite backup on startup and every hour. Each backup is restored into a disposable database and integrity-checked before being marked successful. The SQLite backup API includes committed WAL changes while excluding uncommitted transactions. `/ready` reports a failure if backups fail or become stale.

Hourly backups are retained for up to seven days, subject to a 224 MiB archive budget; at least the latest two are retained. Databases larger than 64 MiB stop passing backup verification and need a revised storage/backup configuration. Existing databases receive a backup before startup upgrades; the last three pre-upgrade archives are retained after successful startup. These limits suit the initial 1 GB disk and must be revisited as data grows.

Archives are encrypted with a purpose-specific key derived from `FF_ENCRYPTION_KEY`. Tokens use a different derived key. Losing the original key prevents restoration. Recovery deliberately deletes old sessions so restored backups cannot revive a logged-out session.

The automatic archives are on the Render disk. Render also takes daily encrypted disk snapshots; those are **not a substitute for the application's validated database archives**. Independently export an encrypted `.ffbackup` file off Render and preserve the key outside Render before live-data testing. Automatic offsite export is not configured in this stage and no extra storage subscription is created. Render account/service deletion can remove access to on-platform copies.

Create an additional archive from a Render shell (the environment already has the key):

```bash
python -m backend.app.backup create --source /var/data/family-finance.sqlite --destination /var/data/backups/manual-recovery.ffbackup
```

Choose a new destination name each time. Export the encrypted archive over an authenticated SSH connection after [registering a public SSH key with Render](https://render.com/docs/ssh). The service-specific connection and export check remain part of the deployment handoff. There is intentionally no public or app-facing database-download endpoint.

Restore into a **new** file from the running service's shell. Ask both spouses to pause app use during recovery and take a final archive of the current database before switching paths:

```bash
python -m backend.app.backup restore --source /var/data/backups/manual-recovery.ffbackup --destination /var/data/recovered.sqlite
```

Point `FF_DB_PATH` to that recovered file, restart, check `/ready`, log in again, and reconcile saved totals. Restoring the new file does not modify the original running database; changes made to the original after the chosen archive are not automatically included in recovery. Never copy a live SQLite file alone or overwrite the running database. Restoring a disk snapshot directly into a database can produce inconsistent data; restore a validated `.ffbackup` archive instead. Keep the previous file until recovery is confirmed.

## Migrations and existing local databases

Schema version 1 establishes the known local MVP baseline with its legacy additive columns. Version 2 adds expiring sessions, persistent throttling, and the encryption-key check table. Every version runs in a transaction. Failed upgrades roll back; future schema versions and inconsistent migration history are refused. Legacy sessions with no expiry are invalidated.

The hosted beta starts fresh. No local personal/demo database is uploaded or modified by this work. For a later approved legacy import, stop the original server, set `FF_ENCRYPTION_KEY` privately, and run:

```bash
python -m backend.app.upgrade --source old.sqlite --destination upgraded.sqlite --backup before-upgrade.ffbackup
```

This preserves the original, creates an encrypted recovery copy, upgrades a new database, revokes old sessions, encrypts legacy token values, and vacuums the new file. Inspect the result before changing the server's database path. Arbitrary historic schemas are not supported; a refused upgrade needs investigation using a copy.

## Android release and signing

Run from PowerShell 7.2 or newer:

```powershell
.\scripts\build-private-beta.ps1 -BackendUrl https://YOUR-ASSIGNED-SERVICE.onrender.com
```

The script creates a signing key only if none exists, stores it under ignored `work/private-beta-signing`, restricts the key/password files to the current Windows user, and reuses that key for updates. Preserve the entire signing directory in an encrypted backup. Do not commit or share it with the APK.

Output: `work/releases/family-finance-stage1.apk`, version `0.5.0-stage1` / code 2. Without an assigned URL, the same script builds with a reserved `.invalid` placeholder; the owner must enter the real HTTPS address before use. This placeholder never supplies synthetic financial state.

A release APK cannot update an existing debug-signed installation with the same package name. On a phone with such a debug installation, preserve any needed configuration and uninstall the debug app first. Household records are held on the backend. Neither physical phone has been changed by this implementation.

## Verification commands

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s backend/tests
python -m backend.smoke_review
python -m backend.smoke_stage1
cd android
.\gradlew.bat testDebugUnitTest assembleDebug lintDebug assembleDebugAndroidTest
```

The instrumentation package contains a real Android Keystore test. Run it only on a disposable emulator/test device: it clears the test application's stored session. Backend tests and both smoke flows use synthetic disposable data, with no live provider calls.

## Local verification — September 11, 2026

- Full backend suite: **185 tests passed**, including 18 hosting/security/recovery tests.
- Android unit suite: **36 tests passed**. Debug APK, instrumentation APK, signed release APK, and lint completed successfully. Lint has 18 nonblocking warnings about preference writes, the launcher icon, and untranslated/concatenated text; Gradle also reports deprecation warnings.
- A real Android Keystore instrumentation test passed on a new disposable emulator. The signed release installed and launched there with no crash output. The pre-existing emulator and physical phones were not modified.
- APK signature verified. Packaged version is `0.5.0-stage1` / code 2, with cleartext traffic and app-data backup disabled; the release is not debuggable.
- Both `backend.smoke_review` and `backend.smoke_stage1` passed, including shared-household changes, financial totals, server restart, encrypted recovery, and fresh login after restoration.
- Fixed issues found by testing: WAL snapshot deserialization, instrumentation runner compatibility, repeated signing-file ACL updates on Windows, and a test-server shutdown race. Targeted checks passed before final verification.
- The five pinned Python dependencies returned no known OSV advisories at check time. This is a dependency database check, not a security certification.
- Secret/junk scan reviewed 96 repository candidates: no real credentials or generated junk found. One existing Plaid-shaped test fixture was reviewed as a redaction test. Signing materials, APKs, databases, logs, and backups remain ignored. `git diff --check` passed.
- Verification was completed on `codex/stage-1-private-beta` before Daniel approved committing the changes and opening a PR. Merge and deployment remain separate release gates.

## Remaining release gates

- Commit/review approval and a Render session accessible for deployment.
- Actual Render deployment, HTTPS/readiness checks, and preservation/export of recovery materials.
- Both physical Pixel installs and the shared-household Wi-Fi/cellular walkthrough.
- Stage 2 USAA access, synchronization and financial reconciliation before the real-data beta launch.

Passing local tests establishes readiness to review and deploy stage 1. It is not a claim of a completed hosted deployment, penetration test, or completed USAA beta.
