# Web interface migration status

Updated: October 10, 2026. The opt-in browser implementation is available locally.
The live Ubuntu deployment has not been changed. A separate Ubuntu/LAN pilot was
tested without interrupting it. No commit, push, or production deployment was performed.

## Implemented

- Shared services/controller for normal, queued and one-shot farming, priority
  cancellation, diagnostics, captures, settings, bounded events and timer reads.
  Desktop normal operation and one-shot farming use the lifecycle controller.
- Local-first FastAPI server, salted password verifier, expiring sessions,
  login throttling, CSRF/origin/host checks, authenticated WebSockets, payload
  limits and cross-process device ownership.
- Responsive React interface following the approved minimal layout: Dashboard,
  Settings, Setup, Library, Diagnostics. Seven themes, common/advanced settings,
  timing presets, raw developer timings, dirty guards and revision conflicts.
- All 32 calibration parts: direct selection, missing/all flow, instructions,
  immutable captures, original-pixel selections, templates/colors/grids, ordered
  farm taps, farm-only jitter, skip/cancel, stale capture guards and journaled
  calibration/template restore transactions.
- Backup, safety restore, rename/delete, validated ZIP sharing, profile saves,
  paged collection gallery/status and diagnostic/report downloads.
- First-launch test profile with isolated data and inherited worker context.
  Normal/test profiles cannot simultaneously control Android.
- Optional one-frame-per-second viewer: taps/swipes, explicit Back/Home,
  exclusive control, cancellation/disconnect cleanup and no auto-resume.
- Installer web option, launcher, compiled package assets and installation/
  developer instructions in WEB_UI.md. Desktop launch remains the default.

## Retained locally

- Classic terminal calibrator stays local rather than exposing a remote shell.
- Desktop shortcut installation stays in the desktop app; its shortcut still
  launches that app. Browser users use the documented web command.
- Collection labeling/review decisions remain in the local review tool. The
  browser gallery currently displays images and collection status.
- Waydroid startup remains manual. Browser tools can close the current user's
  session, but do not install/start Android or alter host privileges.

## Verification

- 42 offline tests passed: lifecycle races/errors, engine reliability, auth/CSRF/
  origins, settings conflicts, all calibration parts, stale capture protection,
  archive boundaries, viewer ownership, test-profile isolation/reset/context and
  frozen stopped clocks.
- Desktop smoke checks passed across five pages and seven themes with isolated
  data and live ADB forbidden. TypeScript checks and production build passed.
- Linux launcher syntax checks and inclusion of compiled browser assets in a
  locally built wheel passed. A clean Linux package installation is still pending.
- Browser checks used a disposable fake device: authentication, Start/Stop,
  pan/capture/sequence saving, phone-width settings, viewer open/close, and
  first-launch setup/capture/save/exit. Preview images are in `design/web-ui/`.

## Remaining acceptance gates

The isolated Ubuntu/LAN checks are recorded in
[Ubuntu acceptance](WEB_UI_UBUNTU_ACCEPTANCE.md): 42 tests, Linux package/assets,
cross-computer browser operation, request protections, conflicts, reconnects and
existing-profile compatibility passed.
The follow-up live pilot also passed capture/viewer input, practice Stop,
standalone-farm cancellation, copied-profile calibration save/cancel/restore,
and one full farm returning to confirmed clan chat via the timer fallback.
Actual donation was not tested because no request was available. Production
was not updated; the original desktop GUI was reopened with automation stopped.

These need the real Ubuntu/Waydroid deployment; offline tests do not replace them:

1. Record live startup, screenshot and Stop timing baselines; validate existing
   calibration/settings without rewriting them.
2. Supervised donation/farm/calibration/restart checks; long-running cancellation,
   device failures, multiple tabs, second LAN device, network loss and sustained run.
3. Validate source and packaged installs in a clean Linux environment. Optional
   user-service startup requires confirming the Waydroid desktop/session environment.
4. Evaluate the planned scrcpy browser bridge on actual Waydroid. The current
   screenshot viewer is a preparation prototype, not the planned video transport.
   Measure rotation/input mapping, bandwidth, latency and game/Stop load; consider
   noVNC only if necessary. Concurrent read-only viewers remain deferred.

Keep the desktop fallback and do not declare full acceptance or cut over before
these gates pass. The approved plan is preserved in WEB_UI_MIGRATION_PLAN.md.

