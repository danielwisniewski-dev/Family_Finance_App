# Warmer interface — September 2026

Android `0.6.2-warmth` (code 5) implements Daniel and Kara's approved follow-up to the [September interface update](interface-tweaks.md): less white, more distinct typography, friendly graphics, and celebrations for confirmed accomplishments.

## Appearance

- Sage backgrounds, cream cards, deeper green headings and controls, and warm gold achievement accents. Warning and overspending states retain their own colors and written labels.
- Bundled Nunito headings distinguish titles from everyday text; merchant/category names and amounts have stronger emphasis, with dates and supporting details smaller. Nunito is sourced from [Google Fonts](https://github.com/google/fonts/tree/main/ofl/nunito) under SIL Open Font License 1.1; the license is included in `android/app/src/main/assets/licenses/Nunito-OFL.txt`. The font requires no network download.
- Decorative household illustrations, category and navigation icons, and one illustrated “All caught up!” card replace the repeated empty-queue messages. Controls retain descriptive accessibility labels. Decorative graphics do not add accessibility stops, and the dashboard gives text more room at larger font sizes.
- The dashboard's unread-notifications card opens Notifications directly; its separate button was removed. “Categories needing attention” shows only active categories below $0; zero and positive remaining amounts are excluded. The empty-state message now describes overspending only.
- Dashboard metadata uses “Budget:” and “Last sync:” with a shorter sync date, for example “Budget: Sept 2026 · Last sync: Sept 19, 9:45 AM”. The sync year and time-zone label are omitted; local-time conversion is preserved. Balance-only sync remains clearly labeled, and larger text can wrap without truncation.

## Celebrations

- Confirmed category assignments, review confirmations, and saved splits earn brief checkmarks and sparkles after refreshed backend data confirms the result. A completed batch can also earn a reward. Failed or incomplete batches do not celebrate.
- Fireworks/confetti mark an action that clears the review queue, with the acted-on transaction included in the previous pending queue. Opening or refreshing an already empty queue does not replay fireworks. Ignoring transactions does not earn a review reward.
- A new day's actual check-in progression celebrates 7, 14, and 30 days, then each additional 30-day milestone, or an established personal best being beaten. Same-day redraws, missed days, invalid/future dates, and seeding an old unstored record do not create new record rewards.
- Settings includes “Celebrate my progress,” enabled by default and saved locally for each person, household, and backend. Turning it off keeps the confirmation message without the animation. Animations also follow the phone's system animation setting, do not intercept touches, and use no sound or vibration.
- Safe-to-spend results include encouragement for checking first. The financial answer itself does not trigger purchase-encouraging fireworks.

## Preservation and delivery

This change adds no backend or financial behavior, database migration, bank connection change, or signing-key change. Existing household data, Plaid connection, financial API calls, saved streak keys, and the Android signing key are preserved. The backend remains authoritative for all money and safe-to-spend results.

Daniel approved documentation updates, GitHub publication, and signed phone delivery on September 19. Source is published through the milestone branch `codex/ui-warmth-celebrations` and a PR against `main`; merging still requires his explicit approval. The signed APK is `work/releases/family-finance-0.6.2-warmth.apk`, version code 5, package `com.familyfinance.app`, using the original signing certificate and the existing HTTPS backend. It is not debuggable; cleartext traffic and app-data backup remain disabled. Signing files and both earlier release APKs were verified unchanged.

APK SHA-256: `C4A1820FD57E3470FFC0B6AA6A80E798F8D7C023A9787EE0D6203827675BDBF0`.

To install on each phone:

1. Transfer the signed APK to the phone and open it in Files. Allow that file source to install apps if Android prompts.
2. Choose **Update/Install** over the existing Family Finance app. Keep the installed app and its data; do not uninstall or clear storage. If Android refuses the update, stop and check the installed version/signature before proceeding.
3. Open Family Finance and confirm the usual household and bank connection are present, the dashboard has the new appearance, and the unread-notifications card opens Notifications. Settings > **Celebrate my progress** controls animations.

No physical phone was connected during preparation, so actual phone installation and acceptance are not yet verified. The backend stays at the September 17 deployed release; this Android update requires no server deployment, database migration, setup, or bank reconnection. Runtime release helpers and evidence remain under ignored `work/`.

## Verification

- Full backend suite: **211 passed**. No backend source changed.
- Android: **72 unit tests passed**, including eight new celebration-policy tests and two dashboard attention boundary tests; `assembleDebug` passed. Targeted feature tests passed before final verification. The September 19 dashboard follow-up covers -1, 0, and +1 cents, archived negatives, and all-nonnegative categories without changing backend calculations.
- Native emulator smoke with isolated synthetic data passed: streak milestone/fireworks, stronger dashboard and transaction typography, successful assignment and review confirmation, failed save retaining its unreviewed state, illustrated queue completion, category/navigation controls, persistent celebration preference, 1.6× system text size, and confirmed review with system animations disabled.
- September 19 dashboard smoke passed: tapping the unread-notifications card opens Notifications, the separate button is absent, and only the active -$0.01 boundary category appears; $0.00, +$0.01, and archived categories are excluded. The unchanged backend retains the earlier 211-test verification; the full Android suite/build and secret/junk checks were rerun for this follow-up.
- The compact budget/sync line was verified on the Pixel 8 emulator at normal text size using a copy of the synthetic preview database. Existing date tests still verify UTC parsing, explicit offsets, local date changes, daylight saving, balance-only fallback, and missing timestamps. All 72 Android tests and the debug build passed again; no backend change required another backend run.
- Safe-to-spend smoke passed with the fake bank: required backend explanation remains intact; failed bank sync blocks calculation, and retry retains the request and succeeds. These tests did not use real Plaid or household data.
- Visual review corrected the bundled heading weight and category icon choices. A review found and fixed celebration attribution for unrelated transactions. Local smoke-helper field selection, navigation, and network waits were corrected; no outstanding app/test failures remain.
- Signed `assembleRelease` and its release lint checks passed. APK signatures verify and match both Stage 2 and the previous interface release; package/version, production HTTPS endpoint, non-debuggable manifest, and backup/cleartext guards were checked. The first verification helper looked for a separate network-security resource; it was corrected to read the existing manifest guard and passed without an app change.
- A disposable emulator accepted an in-place update from the previous signed `0.6.1-interface` APK to `0.6.2-warmth`; the saved synthetic backend URL and budget month survived, and the new release launched. This test used a reserved `.invalid` endpoint and no household credentials; it does not substitute for physical-phone acceptance.
- `git diff --check` and secret/junk/encoding scans passed. Runtime databases, screenshots, helpers, APKs, and logs remain ignored under `work/` or Android build output. No backend deployment or physical phone installation is claimed.
