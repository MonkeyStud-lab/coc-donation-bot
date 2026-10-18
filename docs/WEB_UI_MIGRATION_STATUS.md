# Current interface and deployment status

Updated **October 18, 2026**. This is the current status summary; the
[original migration plan](WEB_UI_MIGRATION_PLAN.md) and
[October 10 pilot report](WEB_UI_UBUNTU_ACCEPTANCE.md) are historical records.
Their old passwords, rollout gates, and default-interface statements are not
current operating instructions. Start with the [README](../README.md).

## Available now

The browser dashboard is deployed through CasaOS on an existing Ubuntu/Waydroid
installation. The default CasaOS port is 8767; source launches use localhost 8765.
No dashboard password is required by default. Explicit LAN binding, host/origin,
session/CSRF, WebSocket, and ownership protections remain in place.

The six current pages are Dashboard, Attacks, Settings, Setup, Library, and
Diagnostics. They include:

- Shared Start/Stop, queued and standalone farming, status/events, paused
  farm/session countdowns, practice mode, and runtime readiness/errors.
- Always-editable settings with validation, revision conflicts, safe Save &
  restart, common/advanced/developer controls, themes, and timing presets.
- Direct/guided calibration with original-pixel screenshot editors, ordered
  legacy deploy taps, skip/cancel, backups/profiles, and transactional restores.
- Calibration ZIP import/export, rename/delete, collection gallery/status,
  diagnostic actions, screenshots, activity and report downloads.
- Real WebRTC Live view with optional exclusive taps/swipes and Android controls;
  the separate slower screenshot viewer remains available.
- Automatic supported-army Electro Dragon attacks, custom map-based routines,
  and the original programmed sequence. Scheduled farming defaults off and
  sequence remains the default method for a new profile.
- Optional Suggested upgrades/research, availability and resource-reserve checks,
  non-spending previews, and durable uncertain-spending reconciliation.
- Interrupted-attack recovery without deployment replay and bounded generated
  attack diagnostic retention.
- CasaOS managed Android/game startup, trusted initial APK import, and verified
  in-place game updates. Host preparation/helper installation is separate from
  normal bot-container privileges.

Desktop/terminal entry points and the classic local calibrator remain. The
browser has newer planner/upgrade controls; the interfaces share engine/profile
formats but must not compete for Android ownership. Screenshot labeling/training
is a separate workflow, not automatic online learning or action authority.

## Recent verified evidence

These are dated completed checks, not promises for every installation and not
checks rerun by a documentation edit:

- The October 10 Ubuntu/LAN pilot exercised browser transport, session/origin
  protections, copied-profile calibration, Start/Stop, and a complete legacy farm.
- Subsequent existing-host CasaOS integration exercised managed session
  close/reopen, app management, profile preservation, APK import/update, LAN
  video, and manual browser controls. Clean-host/headless acceptance remains
  separate; see [CasaOS status](CASAOS_PACKAGE.md#verification-and-remaining-limits).
- The October 14 game-UI pass verified the new army confirmation/battle gate,
  recovered a reward overlay, and completed a real specific donation including
  troops and a Recall spell. See [UI evidence](UI_COMPATIBILITY.md#live-validation-october-14-2026).
- The October 17 reviewed current-UI screen model remained observation-only;
  its held-out coverage/weak classes are in [PERCEPTION](PERCEPTION.md).
- October 18 crash testing interrupted an attack after eleven verified dragons.
  Recovery sent no further deployment inputs, returned through visual results,
  reconciled the interval once, and reopened chat with protected profile data
  intact. See [attack recovery evidence](ATTACK_REBUILD.md#interrupted-attacks-and-diagnostic-storage).
- Source snapshot `7d01eba` completed 302 Linux tests with one skipped before
  deployment. Its installed package matched the source snapshot.
- The October 18 deployment of `7d01eba` completed a fresh automatic attack:
  eleven dragons, five Rage spells, one siege, and two available heroes were
  verified, with both hero ability taps sent. Two fresh results frames triggered
  Return Home before the fallback. Home/chat were confirmed, recovery markers
  cleared, and the bot resumed checking requests. All 37 protected files and
  settings matched the pre-deploy checks. No active donation request was available
  in that deployment check, so it did not re-verify donation fulfillment.

Test counts describe those exact runs. Follow [RELIABILITY](RELIABILITY.md) for
reproducible current checks, rather than treating old counts as new results.

## Remaining limits

- Fresh host installation from no Waydroid/calibration, unattended headless reboot,
  and broader kernel/GPU/CPU combinations need dedicated acceptance.
- Live video depends on Android encoding, browser/network paths, and permitted
  UDP traffic. One stream/controller is supported; multi-viewer service is not.
- Recognition targets the inspected English landscape layouts. New UI versions,
  small displays, unfamiliar skins/sceneries, and ambiguous OCR can block actions.
- Automatic attacks support a fixed army/strategy family, not arbitrary strategies.
  Some opponents/maps or card readings can conservatively stop deployment.
- Recovery can require manual inspection. Restarting a container does not mean
  the app will automatically press Start or replay unfinished actions.
- Source-wheel-only installation is incomplete without profile defaults/scripts;
  normal installation uses the checkout or the built CasaOS image.
- UI screenshots/mockups and one successful live run do not establish universal
  phone/browser accessibility, soak performance, power-loss recovery, or upgrade
  compatibility. Keep measuring these against the affected release.

## Before another release

Use the installed configuration and a verified private profile backup. Build/test
an exact source snapshot; preserve the prior image. Deploy the bot without
rerunning privileged setup for code-only updates. Check installed assets/imports,
runtime readiness, actual affected game outcomes, Stop, and home/chat recovery.
Compare protected data/settings and leave only the intended controller active.
Record skipped checks and remaining risks explicitly.
