# Ledger Demo mode

Status: Implemented as part of Android `0.7.1-ledger` / code 7. Daniel authorized committing/publishing the branch, backend deployment and signed APK delivery on September 29, 2026. The signed APK and existing-host capacity preflight passed; branch publication and backend deployment are underway, with deployment results pending. Merge still requires separate approval. Current verification is recorded below; this document replaces the earlier proposal and is the ongoing feature and maintenance contract.

## Experience

**Accounts / Settings → Demo mode** opens a fresh, funded fictional household on the normal dashboard. A persistent **DEMO DATA** banner identifies every demo screen. Users navigate the same screens and use the same financial controls as real mode; normal backend prerequisites and calculations still apply. No scenario selector or Reset demo button is included.

Changes persist while that demo session is active. Switching Demo mode off discards its changes and returns to the real household's saved connection, selected month and encrypted session; an expired real session requires login. The next entry starts with a fresh fictional household and current dates. The toggle explains: **Demo changes are cleared when you leave demo mode.** Users do not enter another backend URL or household credentials.

Closing and reopening the app while still in demo mode is not an intentional exit. Resume the saved demo session if it is still available. Sessions expire after eight hours and on backend restart; an unavailable session must be explained to the user, without showing its data as current or silently switching a financial action to real mode. A new demo entry creates fresh data. Internet access is required, as for the current real app.

## Backend isolation and lifecycle

Reuse the existing hosted service and ordinary API/domain code, with a separate disposable SQLite database, synthetic bank provider and deterministic mock coach per demo session. The server selects a complete repository/provider context before dispatching each request. Never mutate shared production repository/provider objects, change process environment to enter demo mode, accept a client-supplied database path, or copy the real household's contents. Sharing one process relies on application routing and tested context isolation; it is not a separately deployed security boundary.

The protocol is:

| Request | Authentication and effect |
| --- | --- |
| `POST /demo/start` | Requires a valid real session. Creates a fresh isolated fictional household and returns the ordinary login response shape plus `demo: true`, its `budget_month_id` and `expires_at`. It does not issue real credentials to the demo context. |
| `/demo/...` | Requires that session's demo bearer token. Dispatches the corresponding ordinary app API into that session's repository and providers, with the same financial validation and response behavior. |
| `POST /demo/exit` | Discards the matching demo session/database and invalidates its token. It cannot delete real data or another demo session. |
| Real data routes | Reject demo tokens. Demo data routes reject real tokens and tokens from expired or unknown sessions. |

Each application instance permits at most eight active demo sessions, with an absolute eight-hour lifetime. Entry is limited to four requests per real user per minute. Expiration and exit release disposable storage; backend restart immediately invalidates the old sessions. This is intentionally not a durable demo workspace. One spouse/device leaving its demo cannot reset another active demo. A session lock coordinates dispatch and cleanup so an in-flight request cannot write into a replacement session. The session index uses token hashes, not raw tokens.

Temporary roots carry an ownership marker and an OS file lock. The next demo entry and minute cleanup sweeps reclaim unlocked roots left by a crashed process while preserving roots held by live managers and unrelated temporary files. A temporary deletion failure leaves an invalid tombstone that still consumes a capacity slot until cleanup succeeds; a failed seed is tracked the same way. Cleanup retries must not stop other sessions' expiration. No startup scan is required on a service that has not used demo mode since restarting.

Android keeps real/demo encrypted sessions, selected months, cached screen data and pending monetary request keys separate. Preserve the real login while demonstrating. Mode changes clear displayed data and fence callbacks from the old context; an uncertain real financial write must be resolved before entering demo mode. Demo session identity participates in request scoping even when both modes use the same host. An exit must stop using the demo token immediately. If server cleanup cannot be confirmed, abandon that session locally; its expiry provides eventual cleanup and the next entry must still be fresh.

Demo mode never calls production Plaid, opens real bank authorization, calls OpenAI, or disables real-bank protections. Private household creation and login/password administration are unavailable within demo routes; demo logout discards the session. Demo Settings hides the real backend URL/month-ID form, password change and logout controls and explains that password/server settings belong to the real account. Display-name editing, account inclusion and ordinary bank controls still operate on fictional data. The fixed banner includes **Exit demo**, including loading/error states. An expired session stays on **Demo session ended**, offering **Start a fresh demo** or **Return to my real account**; it never silently resets. Coach output remains advisory, and any supported budget mutation still requires the ordinary explicit user action.

## Hosting and maintenance cost

This change adds no hosted service, database subscription, paid bank product, AI usage or plan upgrade. Disposable SQLite databases use the existing service's capacity. No additional monthly hosting charge is expected within that capacity and its usage allowances. The September 29 preflight found the unchanged single Starter instance using about 111 MiB of its 512 MiB memory limit, with about 48.6 GiB free writable temporary storage and 812 MiB free on the existing persistent disk. This snapshot establishes available headroom, not a load/scaling guarantee; the attached disk does not support adding instances. Monitor usage if the demo workload grows rather than assuming unlimited capacity.

Bounded session count/lifetime limit storage and memory use. Demo databases are disposable and are not household recovery archives; preserve the real encrypted backups and never include synthetic sessions in an export presented as the household backup. Maintenance means keeping the fixtures, synthetic provider and normal workflows compatible with future app changes and testing that isolation remains intact.

## Fictional data and working actions

Seed with fictional people, merchants and account details only. Derive dates from the backend's household calendar day on each entry, including previous/current/next-month context, payday and bills. A session crossing midnight or month end follows the ordinary date rules; leaving and reentering seeds current dates again. Build records through repository/domain operations and validate the resulting arithmetic. Never introduce fake client balances or insert reserve totals without their ledger history.

The sample household must be useful immediately: a funded monthly budget, included checking cash and excluded savings, current simulated bank data and reconciliation, funded Provision Funds with plans, transactions and useful history. Initial outgoing transactions should be reviewed so the user can try a successful Spending Check immediately. Synthetic Sync then supplies transactions that can be reviewed through the normal workflow; after that, the real review/reconciliation requirements apply. User edits can create low cash or overspending outcomes naturally, without a scenario selector.

- **Sync** imports deterministic fictional bank activity, updates bank/balance timestamps through the normal pipeline, and avoids duplicate transactions on repeated sync. A fresh demo session restarts the simulated bank sequence.
- **Request fresh bank data** and **Reconnect** use only the synthetic provider and ordinary app flow. They must never consume a real connection or launch production Plaid Link.
- **Spending Check** uses category remaining, included cash, bills, payday and reserves exactly as real mode does, including the required after-bills/until-payday sentence. Retain daily freshness, review, reconciliation and cross-month prerequisites.
- **Provision Funds** begins with actual seeded contribution history. Contributions, releases, moves, purchases/refunds and planning edits use the shared accounting, cash protection and idempotency rules.
- Budget/month/category editing, transaction categorization/review/splits/ignore/refunds, merchant rules, account inclusion, notifications, diagnostics and mock-coach flows operate on the session's data through their ordinary APIs.

The older `backend.app.demo_seed` CLI creates a standalone local development database and remains separate from the in-app mode. Testing that CLI seed alone does not verify mode switching, token isolation or automatic discard.

## Feature parity and maintenance checklist

Treat demo mode as part of the definition of done for every app feature. `AGENTS.md`, the project plan and the README point here so future work cannot treat sample data as a one-time screenshot fixture. For each change, identify the affected rows, update fixtures/provider behavior with the implementation, add meaningful regression coverage and record the affected smoke result. An unchanged area does not require a new test that merely repeats its code.

| Changed area | Maintain and verify in demo mode |
| --- | --- |
| Schema, repository or API contracts | Apply the same schema to fresh disposable databases; add required fixture fields; verify all exposed normal screens can read/save their records and responses stay sanitized. |
| Financial rules and Spending Check | Run shared calculations against seeded/current synthetic data; compare category/cash/bills/payday/reserve behavior and required explanation. Include success and refusal, without a demo-only bypass. |
| Budgets, months, categories, income and bills | Keep the current budget useful and coherent; verify edit/copy-forward/archive behavior and previous/current/next-month data, including household midnight and month rollover. |
| Provision Funds | Maintain funded fixtures, plans/items/history and valid backing cash; verify contribution/retry, release/move, categorized purchase/refund, protected cash and carryover. |
| Transactions and merchant rules | Maintain realistic reviewed, split, ignored, incoming and refund history; Sync must supply reviewable rows. Verify categorization, review, exclusions, rule behavior and absence of double counting. |
| Bank/provider contracts and account controls | Update the synthetic provider whenever its interface changes. Verify Sync, repeat sync, fresh-data/reconnect behavior, inclusion and freshness through the shared service, with zero real bank calls. |
| Coach, summaries, notifications and diagnostics | Use fictional financial facts and mock responses; preserve advisory-only behavior, useful screen content, normal notifications and integrity checks. |
| Android screens/navigation | Keep the same actions available with the banner visible on every demo screen/loading/result state. Clear old screen data on switches and label any production-only administration action. |
| Authentication, storage and request lifecycle | Reject cross-environment/cross-session tokens; preserve real login/month; scope cached/pending state and callbacks; test exit, expiry, cold launch, restart, offline cleanup and interrupted writes. |
| New feature or action | Add its fictional data and synthetic dependencies in the same change. Exercise it through normal navigation. If inherently production administration, document the explicit demo explanation instead of routing to real data. |

Code ownership and regression locations:

- `backend/app/demo_data.py`: relative-date fictional household seed; `backend/app/demo_bank.py`: synthetic bank behavior (shared bank/domain services remain authoritative).
- `backend/app/demo_sessions.py`: bounded session lifecycle, isolated API contexts and cleanup; routing integration lives in `backend/app/api.py` and hosted initialization in `backend/app/hosted.py`.
- `backend/tests/test_demo_data.py`: usable seed, synthetic provider behavior and financial compatibility.
- `backend/tests/test_demo_sessions.py`: private entry, routing/token isolation, expiry/exit, concurrency and unchanged real data.
- `backend/smoke_demo.py` and `backend/tests/test_demo_smoke.py`: practical API workflow through fresh entry, ordinary financial actions and discard/reentry; the smoke is included in the normal unit-test discovery command.
- Android `DemoModeStore`, `SecureSessionStore` and `SessionGeneration`, with `JsonHttpClientTest`, `SessionGenerationTest` and instrumentation `DemoModeStoreTest`: prefix/token isolation, late-response fencing, encrypted state preservation, offline leave, fresh reentry and malformed entry responses. Include the relevant tests and a disposable emulator walkthrough whenever these contracts change.

## Release acceptance flow

Use disposable synthetic real/demo contexts for local acceptance, never the household's live money or providers. Run focused changed-feature tests first, then the repository's full final verification once after they pass. Demo tests supplement the real-mode test suite; synthetic checks do not establish live USAA correctness.

1. Log into a synthetic real household; record its financial rows and selected month. Enter Demo mode from Accounts / Settings. Confirm a different fictional household opens, with funded budgets/funds and a banner on all visited screens.
2. Before importing new transactions, complete a successful Spending Check and a Provision Funds contribution. Verify backend amounts and the required cash/payday explanation. Repeat a monetary request safely using its idempotency key.
3. Sync and inspect accounts, transactions and review queue. Categorize/review a new purchase, exercise a split/refund/ignore/rule as applicable, reconcile through the normal control, and run Spending Check again. Repeated Sync must not duplicate activity. Exercise fresh-data/reconnect without real Plaid Link or provider calls.
4. Edit a budget and fund, inspect history/notifications, then close/reopen the app. An available demo resumes with its banner and edits. Test expired sessions and backend restart: stale data must not be used and no action may fall through to real mode.
5. Switch out. Confirm the real household, saved month and valid session return unchanged. Reenter and confirm the sample data is fresh and prior demo edits are absent. Repeat exit with a lost cleanup response; no abandoned session may be reused.
6. Exercise rejected real-token/demo-route and demo-token/real-route requests, two concurrent independent demo sessions, pending/cancelled callbacks and interrupted writes. Verify real financial data is unchanged and real bank/AI clients received zero demo calls.
7. Verify fresh seeding around month end, year end and household midnight; normal date-based constraints remain intact. Run full backend tests, Android tests/build, diff checks and secret/junk checks. Keep databases, tokens, screenshots and build artifacts under ignored runtime storage.

## Current verification record

- Demo seed/provider targeted tests: 8 passed, including calendar boundaries and comparison with the normal bank balance/import behavior.
- Demo session/API isolation and lifecycle: 15 tests passed, including abrupt-process orphan cleanup, preservation of live/unowned temporary roots, deletion retries/capacity, expired database sessions and rate limits. Combined targeted run with existing API security, authentication and Stage 1 hosting tests: 68 passed. Two test-only assumptions were corrected (the new ownership marker remains in an otherwise empty root, and session expiry uses Unix seconds); their focused rerun passed before the final targeted run.
- Full backend suite: 324 tests passed, including the automated demo smoke. The standalone `python -m backend.smoke_demo` also passed. It covers fund contributions/replay/releases/moves, budget editing/month copy, spending, transaction review/splits/refunds/ignore/rules, advice, notifications, sync/reconnect, fresh reentry, unchanged real data and zero outbound provider calls.
- Android: 111 unit tests passed; debug and instrumentation APKs built. All 3 emulator session-storage tests passed, including encrypted token isolation, retained real state, cold launch, offline leave, discarded edits and stale scope protection.
- Disposable emulator walkthrough passed: Settings toggle, persistent banner, a $25 Car Repairs contribution ($590 to $615), restart retaining demo state, successful Spending Check, synthetic Sync and review queue, Exit restoring the real session, reentry resetting Car Repairs to $590, and expired-session recovery to real mode. Backend route smoke covers the remaining detailed edits/review/reconciliation/reconnect actions. All data was synthetic.
- Review fixes: abandoned-server temporary files now have safe ownership-based cleanup; failed deletions retain invalid session records for retry. A Java local-variable conflict and test-helper assumptions about response fields, button capitalization and scroll distance were corrected before final checks. No unresolved failure remains.
- Combined source diff and secret/junk scan: 42 changed/new files passed; runtime data, screenshots, logs and APKs remain ignored.
- September 29 rollout: signed `work/releases/ledger-0.7.1.apk` passed original-certificate, version/package, Ledger branding, live HTTPS and non-debuggable checks. Existing-host capacity, schema/integrity, running-process key, Production/Trial configuration and recoverable bank-token preflight passed. A fresh encrypted backup was created and restore-verified only on Render. Saved dashboard key comparison, branch publication, deployment and post-deployment preservation checks remain pending; see the [release rollout record](ledger-daily-sync.md#september-29-rollout-record). Physical-phone acceptance remains unverified; merging the new PR still requires separate approval.

Keep this record current for each release. Preserve earlier evidence as historical results, and explicitly name any workflow or deployment check that has not been verified.
