# How CoC Bot works

This is the architecture guide for the current browser/CasaOS app and shared
Python engine. Use the [README](../README.md) to install it and
[CONTRIBUTING](CONTRIBUTING.md) when changing it. Account/game risks remain as
stated in the README.

## Components and ownership

The browser is a controller for a Linux process. Clash runs in Waydroid; screenshots
and input travel through ADB. No official Clash API or game-memory access is used.

- `web/src/` contains the React/TypeScript interface and editors. Built assets
  ship under `src/coc_bot/web/static/` and are served with the API.
- `src/coc_bot/web/` supplies FastAPI routes, sessions, WebSockets, image delivery,
  WebRTC streaming, and manual-input endpoints.
- `control/` provides shared lifecycle, status/events, settings, calibration,
  backup, diagnostics, upgrade jobs, and attack-planner services.
- `bot.py` orchestrates normal donation operation, optional farming/upgrades,
  breaks, and recovery. `runtime/` tracks clocks, device leases, persistence,
  diagnostic retention, and high-level transition logging.
- `donation/`, `attack/`, `upgrades/`, and `vision/` implement game-specific reading
  and actions. `adb/` owns command execution, capture, ordinary input, app launch,
  and the pinned multitouch transport.
- `calibration/` contains shared definitions, directions, profiles, and restore
  transactions. `gui/` retains the Tkinter presentation and local pickers.
- `packaging/casaos/` contains image/Compose setup, host installation, and the
  narrow runtime helper. `host_bridge.py` connects the app to that helper.

One controller worker owns a normal bot or standalone operation. Stop goes directly
to its cancellation event rather than waiting behind other jobs. A process-level
device lease also excludes other browser/desktop/terminal controllers. Manual
control and calibration/device jobs cannot overlap normal automation. A read-only
video stream is separate; it does not become another automation owner.

The web server uses one Uvicorn worker. Multiple browser clients share that server's
status and configuration. Request bodies, origins, sessions, CSRF, revisions,
controlled file IDs, and device ownership are checked server-side. Default LAN
startup is password-free; optional source-launch password protection exists.
See [browser setup](WEB_UI.md) for the trust boundary.

## Profiles and configuration

`load_config()` in `config.py` merges:

1. `config/default.yaml` for shipped defaults.
2. `data/user_settings.yaml` for saved personal settings.
3. Calibration fields from `data/calibrated.yaml`: dimensions, tap points, screen
   areas, template paths, colors, grids, and the legacy farm sequence.
4. Supported process overrides such as `ADB_DEVICE`.

`COC_BOT_HOME` or web `--home` selects a profile root. `COC_BOT_CONFIG` selects a
calibration file only; it does not isolate other profile data. First-launch tests
use propagated context-scoped roots rather than changing global paths mid-job.

Source runs use the checkout by default. CasaOS mounts the persistent host profile
as `/profile`; image defaults are seeded only when absent. Container replacement
does not overwrite existing calibration/settings. Device/runtime state is not
part of the immutable application image.

Normal Start checks required calibration. Farming needs navigation targets;
sequence mode also needs recorded taps. Automatic mode needs its supported army,
artwork, gesture server, and fresh map, not a saved routine. Custom planner
scheduling additionally checks the routine's supervised approval.

## Screens and action evidence

`vision/screens.py` scopes broad classification with `BotMode.HOME`, `DONATE`,
`ATTACK`, or `ANY`. Similar colors across home, donation, and results are a known
source of ambiguity. Flow context narrows candidates but does not prove a screen.

Action-specific readers provide stronger evidence:

- `battle_menu.py`: Build/home controls, Multiplayer/Find a Match, My Army
  confirmation, independent combat controls, and supported reward Continue pages.
- `battle_completion.py`: paired Return Home/Troops expended text anchors.
- `auxiliary.py`: Shop/Clash Pass headers plus a separate visible close X.
- `idle_dialog.py`: Anyone there? title/message and Reload game control.
- Donation readers: calibrated panel/grid evidence, Donate text, resource mode,
  and global-to-clan chat recovery.

A generic BATTLE label cannot authorize deployment or end a fight. A learned
screen model is an observer only. Annotation categories such as army confirmation
or upgrade confirmation need not be values of the broad runtime ScreenType enum;
the specialized readers verify those pages directly.

Live-defense interpretation is armed after relaunch, not considered on arbitrary
screens. Recognized overlays are handled before background controls; obscured
buttons must not authorize input. White transition clouds are not used to confirm
a return home. See [UI compatibility](UI_COMPATIBILITY.md).

## Donation flow

`DonationBot` scans and scrolls clan chat, opens an eligible request, fills it, and
returns to scanning. A farm or upgrade check is not inserted mid-donation.

- `chat_monitor.py` finds button candidates and verifies Donate lettering,
  rejecting Trade and ambiguous reads.
- `request_parser.py` distinguishes specific, open, and hybrid requests. Specific
  requests are eligible; open/hybrid depend on `donate_open_requests`.
- `navigator.py` opens/closes chat and donation panels, recovers recognized
  interruptions, and switches back from global chat using verified evidence.
- `resource_mode.py` and `executor.py` verify selected elixir before donating.
  A precise elixir tap, if needed, must be confirmed on a fresh image.
- The executor taps colored slots across both visible troop/siege and spell grids
  before scrolling either. It supports inspected low-capacity panel variants and
  stops/refreshes as the panel or available slots change.

The live donation path is colored-slot filling. Optional capacity OCR and older
budget/inventory/fill-planner modules are not the default execution method.
Periodic anti-idle nudges and a state watchdog help the loop recover, but do not
replace screen-specific checks or prove a donation happened.

## Attack methods

`attack/farmer.py` selects the configured engine. Scheduled farming defaults off;
`sequence` remains the default method. Farm now follows the selected method;
Attacks → Automatic attack explicitly invokes automatic mode without saving it.

All methods navigate home → Multiplayer unranked → My Army → verified battlefield.
The current UI's final Attack button is a distinct step. The legacy second-search
calibration remains for older layouts and must not cause an extra blind tap on
the current menu.

### Sequence

`deployer.py` replays `farm_deploy_sequence` from calibration after its recorded
camera pan. The sequence editor displays numbered tap/variation regions. The
farm-only jitter setting applies here, not to navigation/donations or map-planner
verification. This method depends on the matching army bar and camera setup.

### Planner and automatic

`planned_farmer.py` integrates both with normal scheduling. `camera.py` saves the
home reference and sends bounded measured zoom gestures. `survey.py`, `mapping.py`,
and `projection.py` combine registered views and require sufficient evidence for
four deployment-boundary sides before producing map coordinates.

`army.py` reads current card artwork/counts. `automatic.py` checks matching army
pages and builds the supported mass Electro Dragon plan without `routine.json`.
The pattern deploys dragons, spreads Rage, then deploys one supported siege and
recognizable available heroes, each followed by its ability. Unsupported units
and unknown cards are left unused. Missing verified dragons, inconsistent counts
for used cards, and incomplete maps stop deployment. Nearby steps in the red
boundary contribute measured coverage without moving its outer deployment line.

The custom planner in `control/attack_planner.py` supports human-corrected army
review, map/corner review, editable steps, saved routines, and supervised runs.
An exact saved routine/device must pass before scheduling; editing invalidates
approval. Opponent maps and screenshots cannot authorize later opponents.

`executor.py` rechecks battle/camera/card state. Selection gets bounded fresh
observations and at most one safe recognized-card retry. Before map input it
persists intent; after input it verifies a count decrease or deployed card state.
It never retries an uncertain map tap or whole plan. Ability logs prove a tap was
sent, not that its gameplay effect succeeded.

### Completion and interruptions

Normal completion in `navigator.py` observes both results labels on two fresh
frames, then taps the detected Return Home button. `farm.battle_timeout_seconds`
remains a fallback. Planner/automatic anchor it to the first verified deployment
or first uncertain attempt; the legacy sequence records its replay start.
Home and clan chat must then be confirmed, with camera restoration for mapped
attacks. No blind Android Back is used in a live battle.

`attack/recovery.py` persists `attack-pending.json` before attack input. On Start,
after an unexpected error, or before another farm, it inspects unfinished work
without replaying deployment/abilities. Recovery waits through a verified battle,
requires two visual results frames to leave, and has no timer-based Return Home
tap. It confirms home/camera/chat and records interval completion once by attack ID.
Corrupt/foreign state or unresolved scenes remain blocked for inspection.

Home camera restoration normally requires a measured scale within 3%, with bounded
gestures. An automatic-only near-zoom-limit recovery path can preserve the old
reference and block legacy pixel sequences while fresh mapped automatic attacks
remain possible. This is not a relaxed opponent/deployment check. Details and
storage policies are in [the attack guide](ATTACK_REBUILD.md).

## Suggested upgrades

Automatic building/research/pet checks are off by default. They run between donation
rounds after the farm-priority check, and a visible donation request has priority.
Manual preview/start jobs use the same ownership and cancellation rules.

`upgrades/vision.py` reads verified tabs, Suggested rows, availability, and
confirmation controls. `digits.py` uses strict bundled numeric references.
Pet rows use the verified Hero Pets tab and its own 0/1 or 1/1 counter. Assignment
comes from the Assigned/Unassigned headings; a currently observed empty hero-slot
reference can verify unassigned rows after scrolling. Unknown assignment blocks
the upgrade. Equipped pets require a separate opt-in. Pet upgrades use dark
elixir and never upgrade the Pet House building or change hero assignments.
`policy.py` applies supported-name exclusions, reserves, and slot requirements.
`runner.py` checks fresh balances and matching name/price/currency confirmations,
persists intent, sends one resource press, then checks progress and slot changes.

Uncertain spending blocks another purchase. A restart may reconcile pending work
in its own category even when automation for that category is disabled; it does
not repeat or enable the purchase. Gem/Finish Now/magic-item controls are not
spending targets. See [upgrades](UPGRADES.md).

## Scheduling and persisted state

`runtime/tracker.py` tracks active session time and farm intervals, including
separate plus/minus variance. Stop freezes scheduling; resume accounts for paused
time. An already-started break retains its real-time end. Break handling closes
Clash, waits, relaunches, and reopens verified chat.

A fought or entered-skipped automatic match advances its interval to avoid tight
retry loops. Failures before entering a battle use the configured retry cooldown.
Recovery persists completed attack identity to prevent a crash rolling a second
interval. Invalid runtime JSON can be preserved/recovered to defaults; that does
not mean uncertain attack or spending journals may be silently discarded.

`runtime/game_state.py` logs allowed/unexpected high-level transitions. It is a
sanity checker alongside the actual engine state, not an authorization graph.

## Video, data, and operations

`web/live.py` passes pinned scrcpy H.264 through WebRTC without host re-encoding.
Viewing is distinct from manual control and does not feed every video frame into
the recognition engine. Manual taps/swipes have their own exclusive lease;
calibration uses immutable captures, not moving video. Video startup/cleanup,
frame-rate/freeze feedback, and LAN restrictions are documented in [WEB_UI](WEB_UI.md).

Managed CasaOS capture recovery is coordinated by `control/capture_recovery.py`.
Three consecutive screenshot failures, or a failed Android video source, request
a check. Successful screenshots/video packets reset the failure streak. Owner
contention, optional observation misses, Stop, and ICE negotiation alone do not
establish a renderer hang. Recovery stops the bot, acquires its device lease,
retries capture, verifies a responding shell and a timed-out SurfaceFlinger, and
keeps the lease until the managed session stops. It releases ownership before
ordinary startup rechecks Android, launches Clash, and verifies capture. APK
updates are skipped during this recovery. The previous bot options are resumed
only if recovery succeeds and Stop has not been requested. Attack deployments
and upgrade purchases remain governed by their existing durable journals.

`data/runtime/renderer-recovery.json` reserves restart attempts before shutdown:
at most two per hour across app restarts. An in-process five-minute cooldown
also bounds transient probes. Bad history, competing owners, an unconfirmed
fault, or exhausted limits leaves an error for manual inspection. This recovery
is enabled only for the managed dashboard, not arbitrary desktop ADB devices.

Normal screenshots are transient/cached unless diagnostics or recording retain
them. `vision/recorder.py` and `collection.py` optionally select diverse images and
failure context without issuing extra exploratory input. Collection hints are not
verified labels. Review/training/model observer tools remain separate, explicit
steps. [Annotation workflow](ANNOTATION_WORKFLOW.md) preserves UI versions and
partial-box provenance; [perception](PERCEPTION.md) explains model evaluation.

Generated attack diagnostics have age/size/count cleanup with protected recent
evidence and pending-recovery guards. Reviewed datasets, calibration, routines,
and backups are excluded. See [reliability](RELIABILITY.md) for exact limits.

Calibration/template saves and restores use shared locks, staging, revisions,
and recovery journals. Library exports cover calibration/images, not the full
profile or Android account. Source/CasaOS profile roots and migration steps are
in [RUNNING](RUNNING.md).

CasaOS uses `control/platform.py` for staged Android/game preparation and updates.
Its helper accepts allowlisted runtime actions over a local Unix socket; it does
not accept browser-supplied shell commands. App/image updates and helper/host
updates are separate. See [CasaOS](CASAOS_PACKAGE.md).
