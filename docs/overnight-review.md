# Repository recovery review — 2026-09-11

Historical recovery record. Later deployment status is in [Stage 2](stage-2-usaa-plaid.md); the current Android changes and verification are in [the warmer interface update](ui-warmth.md). Approval boundaries below describe that earlier review.

## Review follow-up — 2026-09-11

Daniel reviewed the app, reported no detected errors, and approved committing this recovery batch. The synthetic review API was restarted for his walkthrough. The verification results below remain applicable; no implementation changes were made after those checks. The pre-commit whitespace and scoped secret/junk checks passed again. The overnight handoff below records the state before that approval; push, PR publication and merge remain unapproved.

## Starting point and boundaries

- Starting commit: `bcc8e042e4e1dc39e535ec1d20abe102faccd9f4`; branch `codex/milestone-14-android-polish`; clean working tree.
- Working branch: `codex/overnight-recovery-review`, created with approved local Git permission. No commits, push, PR, deployment, production access, or external communications authorized for this run.
- Evidence: root `AGENTS.md`, README, `docs/project-plan.md`, milestone history, all first-party backend and Android subsystems. README/history supersede the roadmap's old “upcoming” milestones; its financial principles remain applicable.
- Tests use disposable SQLite databases, loopback HTTP, mock coach, and fake Plaid transports. Existing `work/` databases and emulator data must be preserved. Runtime files/screenshots belong under ignored `work/`.

## Outcome

The local app builds and runs on the tested Windows/Android emulator environment. Final verification: **167 backend tests passed; 34 Android tests passed; APK assembly passed; Android lint: 0 errors, 16 warnings.** The HTTP persistence smoke and native core walkthrough passed. Changes are ready for Daniel's review, uncommitted on the local recovery branch. This is a recovery of the existing private MVP, not a production-readiness certification.

## Goals and evidence

| Source / intended behavior | Starting implementation | Result and verification | Remaining gap |
| --- | --- | --- | --- |
| AGENTS + plan / monthly planned budgeting, exact amounts, separate cash reality | Integer-cent engine; client could coerce fractions/overflow; copying retained received income | Strict cents on both sides, signed overdrafts, copy resets actual receipts, archive guards. Financial regression tests and native funding save reconcile totals | Refunds/transfers and account rollover need a product decision |
| AGENTS + plan / category AND cash/bills/payday safe-to-spend with required phrase | Core formula existed; expired payday broke ordinary reads | Planning reads now retain facts with an explicitly unavailable forecast; spending check remains blocked. Recovery tests, HTTP smoke, native $30 check and remove/add payday flow passed | Future bills/paydays still require user-maintained data |
| README M3/M8/M10 / preserve categorization and import exactly once | Assignments, splits, rules, cursor present; retries/updates could disturb overrides or disagree with allocations | Atomic batch/cursor, stale-cursor guard, pending replacement, modified-amount reconciliation, scoped removals, preserved audit history; 22 financial integrity regressions | Live Plaid linking/sync not exercised; no credentials used |
| README M7/M11 / private household access | PBKDF2 and bearer ownership checks; shared server dependencies, setup/session races | Isolated API instances; atomic setup/password changes; all 54 private method/routes reject missing auth; password revokes sessions; malformed input and cross-household tests pass | Local auth/network/storage limitations remain below |
| Plan + README M5 / advisory coach cannot own financial truth or mutate records | Mock default; optional model could substitute structured facts/decisions | Backend facts and draft identifiers/amounts retained, mismatch fallback, deterministic stop/discuss advice. Adversarial provider fixture tests pass; no coach mutation endpoint added | Optional remaining prose is not guaranteed grounded; no live model validation |
| README M14 / clear native household workflow | Existing warm theme; overlapping system bars, long summaries/navigation, transient form hints | Insets, persistent labels, clearer periods and category details, primary actions before streaks, two-column secondary navigation, lifecycle/session handling and full saved split-line preservation. Phone/wide screenshots, keyboard and native save/relaunch checks | Limited accessibility/device coverage; large display retains a simple single-column content layout |
| README / safe reproducible local demo | Fixed June dates; seed deleted existing file | Exclusive new-file creation, current dates or explicit date, year-end regression, documented smoke command | Choose a new path to create another demo; existing data is never reset automatically |

The roadmap's early "upcoming" statuses are superseded by README/history through Milestone 14; its budget principles remain authoritative. Existing source contained no unfinished feature with sufficiently clear requirements to justify adding a new product subsystem. Optional coaching remains draft/advisory only. Refund attribution, cross-month banking and production access were deliberately deferred as decisions, not silently invented.

## Repository coverage

| Area | Reviewed evidence and exercised scope |
| --- | --- |
| Backend HTTP + auth | `api.py`, `auth.py`, all 58 method/routes (54 private), request parsing, exception handling, authentication, actor/household checks, setup/settings and API tests |
| Financial engine + persistence | `domain.py`, `db.py`, `schema.sql`; planning, cash, paydays/bills, category history, manual spending, splits, ignores, rules, notifications/read state, diagnostics, additive initialization and SQL parameterization; full backend suite |
| Providers | `plaid.py`, `coach.py`; configuration, Sandbox enforcement, token/public data boundaries, sync/cursor behavior, provider errors, structured coach output; fake transports and dependency review |
| Android | `MainActivity`, API transport/client/exceptions, every model/state helper, manifest/styles/backup rules, Gradle scripts/wrapper and all tests. UI inventory covers setup/login, dashboard, budgets/categories, income, bills/paydays, transactions/review/splits, accounts/settings, notifications and diagnostics. Native execution focused on the core journeys below; other forms received source/unit/integration coverage |
| Documentation/configuration | Root instructions, README, project plan, original milestone deliverable, `.gitignore`, recent local milestone/merge history. No unavailable conversations or remote issue history were assumed |
| Absent surfaces | No browser frontend, hosted deployment files, first-party CI, uploads/exports, webhooks, background job scheduler, or extra application service. Plaid sync is the implemented import path; notifications are stored local API events, not cloud push |
| Limits | Generated output/vendor source excluded from exhaustive reading. Public dependency versions/advisories checked separately. This review is neither exhaustive interleaving analysis nor a real-device/assistive-technology certification |

## Baseline

- Backend: bundled Python `-m unittest discover -s backend\tests`: **118 tests, 1 failure, 3 errors** (79.128s). All four are summary/detail calls without a future payday after fixed June fixtures expire. These are pre-existing failures.
- Android: installed Android Studio JBR + SDK; unit tests and APK assembly **passed**. Offline lint initially lacked `lint-gradle:31.7.3`; an approved official-repository download resolved it. Baseline lint completed with **0 errors, 18 warnings**.
- Normal sandbox could not access SDK/cache; approved elevated build uses installed dependencies. No project PATH workaround. Baseline APK retained locally at `work/review-before.apk`.
- No separate backend lint/type-check configuration or third-party Python dependency manifest exists. Android lint is the applicable static check.

## Prioritized work

1. Fix provable financial integrity, authorization/session, request-validation and isolated-server defects with focused regressions.
2. Restore budget reads without a future payday; represent unknown forecasts explicitly. Keep safe-to-spend blocked until sufficient facts exist.
3. Repair Android exact amounts, session/endpoint transitions and split preservation; improve labels, navigation and summary hierarchy within current branding.
4. Make demo creation non-destructive/current; inspect a disposable Android instance if feasible; perform HTTP persistence smoke and final broad checks.
5. Reconcile this log with final diff, security/dependency findings, screenshots and precise limitations.

## Decisions / open questions

- Refund/income/transfer accounting is not specified beyond an expense-category model. Do not invent credit-card or refund budgeting; prevent credits from becoming positive spending, preserve imports for explicit review.
- No schema redesign or production migration framework. Test any storage change on disposable data and preserve existing records.
- Local cleartext HTTP, local token storage and unencrypted Sandbox token vault remain explicit MVP deployment limitations.

## Completed work log

- Investigation: three bounded financial, API security and Android reviews completed with separate file ownership; lead integrated their changes, reviewed the diff, and handled coach, demo, documentation and final checks.
- Implementation: targeted regressions passed before broad verification. The original four backend failures are fixed by missing-payday handling, not by changing fixed fixture dates or weakening assertions.
- Integration: the first final Android run passed 30 tests. Dependency review then justified a narrow Okio patch and four compatibility tests; final Android checks were repeated after that actual code change. An initial compatibility-test server used a JDK API absent from Android's compile path; it was corrected to the repository's socket-server pattern.
- Completion: final backend 167 tests, Android 34 tests/build/lint, repeated isolated HTTP smoke, actual native before/after walkthrough, dependency rescan and diff/secret/junk review completed. Commit and any later PR remain pending Daniel's authorization.

### Implementation checkpoint

- Financial regressions now cover atomic import/cursor rollback and retries, stale cursors, pending/posted replacement, modified amounts and split history, saved manual/rule choices, scoped removals, copied received income, signed overdrafts, strict whole cents, canonical months, archived groups and legacy schema initialization.
- Private access now serializes initial setup and password changes; changing a password revokes prior sessions. Ambiguous username/email matches fail closed. API instances own their dependencies separately, preventing one server from switching another server's database. All 54 private method/routes were exercised without authentication.
- API bodies have a 256 KiB limit, 15-second socket idle timeout, JSON content/type/shape and duplicate-field checks; dates, integers and flags are validated without coercing false strings or fractional cents. Financial responses use `Cache-Control: no-store`.
- Missing payday no longer blocks budget reads: forecast values are null, with `forecast_available=false`, while category/account/planning facts remain available. Safe-to-spend and coach budget drafts still reject insufficient payday data.
- Coach structured decisions, source facts and draft IDs/amounts are guarded. Stop/discuss purchase decisions use deterministic wording. The optional model's other prose is still advisory and not guaranteed factually grounded; default demo/tests remain mock.
- Demo creation now exclusively creates a new path and refuses existing files. Dates follow today or explicit `--today`; year-end rollover is tested.
- Repeatable smoke `python -m backend.smoke_review` passed, including login failures, cross-household denial, summary/detail totals, category/split/ignore persistence, invalid amounts/splits, archived categories, missing forecast and server restart. Uses a temporary database and fake providers only.
- Baseline Android lint completed after official dependency download: 0 errors, 18 warnings. Phone and wide baseline screenshots captured from `work/review-before.apk` on a fresh disposable emulator, using synthetic API data. Root inspected dashboard, login and budget; actions were below multiple scrolls and headings overlapped system bars.

### Security/dependency review scope

Architecture: local stdlib HTTP server, SQLite, native Android bearer client, backend-only Plaid Sandbox, mock coach by default. Assets include household financial records, local password/session hashes, provider keys and token vault. Trust boundaries are the device, local server/listener, selected backend URL, authenticated household membership and provider responses. Spouses have equal access within their household. No web frontend/cookies/CORS, upload/export, webhook handler, background scheduler or hosted deployment exists in this repository.

Reviewed source and tests for authentication/authorization, request handling, SQL parameterization, public serialization, token storage, provider errors, notification metadata, Android transport, local backup settings and UI session transitions. No attacks against external targets or live provider calls. This is not a penetration test or an exhaustive concurrency analysis.

Dependency checks used the resolved Gradle runtime graph, direct test dependencies, OSV's public coordinate query API and primary maintainer sources. Only public package coordinates were sent. The initial 87-package scan found one runtime advisory; the final 88-package scan returned no matches. OSV did not return the independently identified test-only JSON advisory below, so this is not a claim that every dependency is vulnerability-free.

- **Fixed:** [Okio GHSA-w33c-445m-f8w7 / CVE-2023-3635](https://github.com/advisories/GHSA-w33c-445m-f8w7), malformed gzip denial of service. Plaid 5.5.2 brought OkHttp 4.9.2 and Okio 2.8.0. A Gradle constraint now selects patched Okio 3.4.0 with `okio-jvm:3.4.0`; all other resolved coordinates, including Plaid, OkHttp and Kotlin 1.9.25, remain unchanged. The [Okio compatibility notes](https://github.com/square/okio/blob/master/CHANGELOG.md#version-300), cached caller bytecode inspection, normal/large/malformed gzip tests, and synthetic OkHttp gzip integration support this narrow change. Real Plaid linking remains untested.

- [AGP 8.7 compatibility](https://developer.android.com/build/releases/agp-8-7-0-release-notes): compile SDK 35, default/minimum Gradle 8.9, JDK 17. Existing installed JBR/Gradle 9.3.0 successfully built the app; deprecation warnings remain. No speculative build-tool migration.
- [Plaid SDK 5.5.3 release](https://github.com/plaid/plaid-link-android/releases/tag/v5.5.3): the patch addresses upload/camera-result delivery and Flutter metadata, outside this app's transactions-only flows. Keep current 5.5.2; 6.x is a breaking migration without a demonstrated need here.
- [JSON-java advisory GHSA-ghc9-756g-vrcv](https://github.com/stleary/JSON-java/security/advisories/GHSA-ghc9-756g-vrcv): unbounded numeric parsing affects the test-only `org.json:json:20240303` dependency; no fixed release was listed when checked. Its inputs here are repository-controlled test fixtures. Android uses the platform JSON implementation; the test-only jar is not packaged as an app dependency. No blind upgrade claimed as a fix.
- [JUnit security advisories](https://github.com/junit-team/junit4/security/advisories): checked maintainer page; direct JUnit version is 4.13.2. This lookup is not proof of an advisory-free transitive dependency graph.

### Remaining decisions / limitations

1. Keep the listener loopback/private. Cleartext HTTP, local bearer storage, an unencrypted Sandbox vault, first-initializer ownership and lack of login throttling/session expiry/server logout revocation prevent a production-readiness claim.
2. Accounts and transaction membership remain tied to a budget month. Cross-month relink now refuses to move history; proper account rollover needs a defined model. Calendar dates alone do not reassign imported/manual spending to months.
3. Refund/transfer attribution is undefined. Old incoming/zero expense assignments remain unchanged and are flagged by diagnostics. Active monthly totals exclude archived categories while history retains them; reconcile this product rule before changing historical financial interpretation.
4. Limited legacy additive upgrade is tested; arbitrary historic schema versions are not. Before testing a personal database upgrade, stop the server, retain a complete backup and run against a copy. Recovery is restoration of that untouched backup; no destructive migration is required by this change.
5. Live Plaid linking, live OpenAI wording, a real handset, full assistive-technology coverage and production deployment were not verified. Android large display checks simulate a wider native display; there is no desktop web app to test.
6. Android intentionally rejects values outside signed 32-bit cents (about $21.47 million) instead of wrapping. A future broader range would require a coordinated client model change. Server aggregate overflow/stress behavior was not exhaustively tested.
7. Remaining lint warnings are 15 localization/formatting warnings and a missing application icon. Gradle also reports future Gradle 10 deprecations and daemon metaspace pressure; the tested build succeeds. No warning was suppressed for this review. Account settings still have some technical MVP labels; layout and accessibility work is not exhaustive.

## Native walkthrough and reconciled numbers

All screenshots and manual operations used a **new disposable Android emulator** (`emulator-5560`, Android API 37 image) and `work/review-demo.sqlite`, seeded with synthetic data as of 2026-09-10 local time. No existing household database, physical phone or existing emulator data was changed. The baseline APK and final APK used the same synthetic backend data to compare UI behavior; subsequent saves intentionally changed the after-state amounts.

| Journey | Observed result |
| --- | --- |
| Login and dashboard | Local demo login succeeds; API-backed included checking $1,035.00 minus unpaid Electric $185.00 and Internet $80.00 gives $770.00 until September 16 (6 days). Savings $2,500.00 remains excluded. Logout returns to the labeled login form with empty credential fields |
| Spending check | Native $30.00 Groceries request returns category remaining $435.68 before later edits and exactly: "After upcoming bills, you would have about $740.00 left for 6 days until payday." No money or assignments change from this advice |
| Review and categorization | Corner Store $21.47 assigned to Groceries and reviewed; queue 3 to 2. Groceries spent $84.32 + $21.47 = $105.79; total spending $220.82 + $21.47 = $242.29. Queue shortcut advances to next item; ordinary category detail retains its context |
| Budget adjustment and persistence | Groceries plan $550.00 to $575.00. Assigned total $1,010.00 to $1,035.00; remaining to assign $4,200.00 - $1,035.00 = $3,165.00; Groceries remaining $575.00 - $105.79 = $469.21. These values survive force-stop, final APK update/relaunch and display resizing |
| Missing forecast and recovery | Remove the sole synthetic payday through a confirmation dialog. Dashboard keeps actual included balance $1,035.00, marks forecast unavailable and offers Add a payday. Restore September 16 through that action; bills $265.00 / cash $770.00 return |
| Forms/navigation/accessibility sample | Persistent labels visible on login/funding/payday/settings fields; keyboard dismissal and Back used during workflows. Tab focuses Add payday with visible focus styling; Enter saves. Native buttons use at least 48dp targets. No full TalkBack/large-font audit claimed |
| Diagnostics and runtime | Native settings report backend reachable and integrity OK. No app crash/FATAL EXCEPTION in the fresh emulator crash buffer. HTTP smoke separately verifies splits/ignore, invalid input rollback, archived category guards, cross-household denial and server-restart persistence |

Phone inspection used 1080x2400 pixels; the wider native display used 1600x1000 at 160dpi, then was restored. The wider layout remains a readable scrollable native column. There is no browser console or desktop web route; native XML, screenshots and crash logs provided the applicable checks. Loading screens, unavailable-backend login error, destructive confirmation, saved totals and missing-data recovery were observed. Account inclusion mutations, every split form length and all notifications were covered by source/tests rather than an exhaustive native walkthrough.

Local visual evidence (intentionally ignored by Git):

| View | Before | After |
| --- | --- | --- |
| Phone dashboard | [Before](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/before-dashboard.png) | [After](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-dashboard.png) |
| Phone budget | [Before](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/before-budget.png) | [Saved budget](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-funding-saved.png) |
| Wide dashboard | [Before](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/before-dashboard-wide.png) | [After](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-dashboard-wide.png) |
| Recovery and forms | — | [Missing payday](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-missing-payday.png), [keyboard focus](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-keyboard-focus.png), [login](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-login.png) |
| Spending and wide budget | — | [Spending result](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-safe-to-spend.png), [wide budget](C:/Users/Daniel/Documents/Projects/family-finance-app/work/review-screenshots/after-budget-wide.png) |

## Exact final verification

From the repository root, using the working bundled Python because sandbox PATH did not provide a usable interpreter:

```powershell
$env:COACH_PROVIDER = 'mock'
Remove-Item Env:PLAID_CLIENT_ID,Env:PLAID_SECRET,Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
& 'C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s backend\tests
& 'C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m backend.smoke_review
```

- Full suite: **167 passed**, 95.172 seconds, recorded in `work/review-backend-final.log`.
- Smoke: **passed**, including new-server persistence. Repeated after final integration; no live provider calls and temporary DB removed.

From `android`, with approved access to the installed SDK/cache:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME = 'C:\Users\Daniel\AppData\Local\Android\Sdk'
.\gradlew.bat --offline testDebugUnitTest assembleDebug lintDebug
```

- **34 tests, 0 failures/errors** from all 12 test-suite XML reports; **BUILD SUCCESSFUL**, 14 seconds.
- **Lint 0 errors, 16 warnings**. Log: `work/review-android-final.log`; lint report: `android/app/build/reports/lint-results-debug.html`.
- APK: `android/app/build/outputs/apk/debug/app-debug.apk`, installed and launched successfully on the disposable emulator after the final dependency change.
- Targeted Okio check before broad run: `.\gradlew.bat --offline testDebugUnitTest --tests com.familyfinance.app.api.OkioCompatibilityTest` — 4 passed.
- Runtime graph: `.\gradlew.bat --offline :app:dependencies --configuration debugRuntimeClasspath`; local public-coordinate scan helper `work/review_dependencies.py` — **88 checked, no OSV matches**, with the separate JSON caveat above.

Final repository checks from the root:

```powershell
git status --short
git diff --stat
git -c core.safecrlf=false diff --check
& 'C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' work/review_scan.py
```

The scoped scan covered 79 tracked/intended untracked files: **no junk candidates** and one deliberate fake Plaid token fixture in `test_financial_integrity.py`, reviewed as synthetic. No real credential exposure was found in the inspected files/diff; no rotation was identified. This is not a full Git-history or external-vault secret audit. Databases, screenshots, scan/build/emulator logs, APKs and scratch helpers remain in ignored `work/` or Android build directories. Whitespace check passed; no staged changes or commits.

## Changed areas and local handoff

- Backend implementation: `api.py`, `auth.py`, `db.py`, `plaid.py`, `domain.py`, `coach.py`, `demo_seed.py`; new repeatable `backend/smoke_review.py`.
- Backend tests: new API security, financial integrity and recovery workflow suites; six existing API test modules updated to obtain per-server dependencies and assert fresh login after password revocation.
- Android implementation: `MainActivity.java`, HTTP transport, money-bearing models, budget state/money formatting; new `JsonMoney.java`, `ConnectionSettings.java`, backup extraction rules and manifest flags; narrow dependency constraint.
- Android tests: new HTTP, money, connection and Okio tests; expanded summary, screen-state and formatting tests. No schema or broad framework rewrite.
- Documentation: README and this report. Full intended paths are visible in `git status --short`; new files are deliberately unstaged for review.

Branch: `codex/overnight-recovery-review`. Starting commit and current HEAD remain `bcc8e042e4e1dc39e535ec1d20abe102faccd9f4`. **No commits, push, PR, merge or deployment.** AGENTS requires Daniel's approval before committing; the overnight request also forbids publishing. Review the diff and remaining financial/security decisions before authorizing a commit.

The disposable emulator and review API were stopped after verification. Their new synthetic database, before/after APKs (`work/review-before.apk`, `work/review-after.apk`), screenshots and logs are retained locally. Existing user databases and emulator data were preserved. No further background work or automation is scheduled.

To run the retained synthetic walkthrough database from the repository root (do not seed over it):

```powershell
$env:COACH_PROVIDER = 'mock'
$env:PLAID_CLIENT_ID = ''
$env:PLAID_SECRET = ''
$env:OPENAI_API_KEY = ''
& 'C:\Users\Daniel\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m backend.app.api --db work\review-demo.sqlite --host 127.0.0.1 --port 8080
```

Open `android` in Android Studio and run the `app` configuration on an emulator. Backend URL: `http://10.0.2.2:8080`, budget month ID `1`; synthetic login `daniel` / `daniel-local-demo-only` (or Kara's documented demo login). Retained data contains the reviewed Corner Store assignment and $575 Groceries plan. Its payday is September 16; add a later payday if reopening after that date. To make a fresh current-date demo, run `python -m backend.app.demo_seed --db work\your-new-demo.sqlite` with a new path, then serve that path. Existing files are refused rather than overwritten.
