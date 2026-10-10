# Web interface migration plan

Status: foundation work started; see [migration status](WEB_UI_MIGRATION_STATUS.md)
for completed work, inventory, and remaining acceptance gates.

## Intended result

Run the bot on Ubuntu and control it from a browser on the same network. Match
the approved minimal mockup closely, including its spacing and controls. Keep
the current desktop interface available throughout migration and rollback.
Closing a browser tab must not stop the bot. Stop must cancel both normal
operation and a manually started farm attack, while leaving Clash open.

The browser interface controls the existing Python engine. Waydroid continues
running on Ubuntu. A later optional game viewer streams its screen to the
browser and sends manual input back; it does not run Android inside the browser.
The migration does not change game recognition or require cloud hosting.

## Product decisions

- Five pages: Dashboard, Settings, Setup, Library, Diagnostics.
- Use the approved minimal mockup as the visual reference. Preserve a copy of
  its source and reference images before implementation; confirm which mockup
  version is authoritative rather than using the older redesign by accident.
- Page titles are enough. No breadcrumbs, decorative subheadings, permanent
  footnotes, or permanent game preview. Keep essential calibration directions,
  validation errors, connection warnings, and accessible help.
- Keep existing themes, basic/advanced settings, timing presets, and developer
  options. Avoid exposing more settings simply because the browser has room.
- Screenshots are requested on demand. Calibration uses screenshot editors.
- After the core migration, add an optional "Open game" view for live viewing
  and manual screen preparation/recovery. It is not a permanent Dashboard preview.
- One server, one controlled ADB device, and one local account initially.
- LAN access is explicit and authenticated. Internet exposure, multi-account
  automation, and a desktop web wrapper are outside this migration.

## Proposed architecture

Use FastAPI/Uvicorn for the Python server and React with TypeScript and Vite for
the browser interface. Serve the compiled frontend from the same server as the
API; do not require a separate frontend development server during normal use.
Bundle fonts and assets locally so the installed interface works offline.

Suggested ownership:

- `src/coc_bot/control/`: interface-independent lifecycle, status, job management,
  settings, calibration services, and bounded event streams.
- `src/coc_bot/web/`: authenticated API, browser sessions, file delivery, live
  updates, application startup/shutdown, and compiled frontend assets.
- `web/`: browser source, themes, pages, screenshot editors, and frontend tests.
- `src/coc_bot/gui/`: retained desktop interface, progressively using the shared
  services rather than owning bot lifecycle itself.

Run exactly one server worker initially. A process-level device lock must also
cover desktop and terminal entry points, preventing a second bot/controller from
controlling the same device. Multiple browser clients share the same controller.
Read-only recognition tests may run independently only when they need no ADB.

Keep game operations out of HTTP handlers and the server event loop. Managed
workers execute longer actions. Commands return job IDs; status and results are
observable. Stop bypasses the ordinary command queue and sets cancellation
immediately, including while the bot is still being constructed. An ADB command
already executing may still need to return; set timeouts and report Stopping
honestly rather than promising instantaneous cancellation.

Use normal HTTP requests for commands and authenticated WebSockets for status
and activity. Reconnection begins with a fresh authoritative snapshot. Give
events sequence IDs, bound retained logs and subscriber queues, and report gaps
when a slow client misses events. The core interface does not continuously stream
screenshots; the later game viewer uses a separate, on-demand video transport.

## Existing code to preserve and extract

`gui/app.py` currently owns worker threads, one-shot cancellation, Start/Stop,
practice settings, timers, settings saves, device actions, and calibration
orchestration. Extract these capabilities in small increments rather than
rewriting the donation or farming engine.

Reuse `bot.py`, runtime scheduling/persistence, configuration loading, calibration
definitions and instructions, backup transactions, collection services, and
existing regression tests. `gui/setup_calib.py` and the screenshot pickers need
their capture/validation/save operations separated from Tk dialogs. Reuse the
data operations from `gui/debug_actions.py`; replace its GUI-specific prompting
and editor calls. Preserve existing configuration keys and file formats.

## Phase 0 — Record the baseline and visual target

Deliverables:

- Feature inventory of every existing page, callback, calibration part, and
  debug action; mark each as ported, retained desktop-only, or deliberately
  deferred with a reason.
- Archived approved mockup source and desktop/mobile reference screenshots.
- Isolated test data directory with synthetic settings, calibration, screenshots,
  and runtime state. Tests must never overwrite production calibration.
- Baseline regression results and measured startup, screenshot, and Stop timings.

Acceptance: the inventory accounts for existing functions, the design reference
is agreed, and tests can run without controlling a live device.

## Phase 1 — Separate control from presentation

Deliverables:

- Shared controller for Start, Stop, queued/manual farm, practice mode, lifecycle
  errors, device ownership, and structured status.
- Move timer reporting into a shared scheduling/status layer. Preserve stopped
  timer behavior, randomized intervals, mandatory breaks, and saved state.
- One job coordinator for diagnostics, calibration, capture, and device actions.
  Block conflicting operations on the server, not just by disabling buttons.
- Settings service with typed validation, revision checks, atomic saves, and
  explicit indication of changes requiring restart. UI drafts stay client-side.
- Desktop adapter uses the controller; desktop regression checks still pass.

Acceptance: simultaneous Start calls cannot create two bots; Stop interrupts
normal and one-shot actions; calibration cannot overlap farming; starting during
shutdown is rejected; canceled workers retain ownership until actually finished.

## Phase 2 — Server and local access

Deliverables:

- Opt-in web launch command; preserve the current GUI and no-GUI commands.
- API for status, start/stop, farm, settings schema/save, jobs, bounded logs, and
  on-demand screenshots. Structured errors replace desktop dialogs.
- Account setup, hashed password, expiring sessions, login throttling, logout,
  request-origin/CSRF protections, and authenticated WebSocket connections.
- File routes use controlled IDs and approved directories. Do not accept shell
  commands, arbitrary paths, or arbitrary debug function names from clients.
- One worker with graceful shutdown and exclusive device ownership. Server
  restart leaves automation stopped unless a separately documented resume option
  is enabled later. Tab closure and connection loss leave automation running.
- Default bind to localhost; enable LAN access only after authentication is set
  up. Protect transport with HTTPS or an encrypted private-network tunnel for
  remote access; document certificate trust and firewall steps in plain language.

Acceptance: unauthorized clients cannot read logs/screenshots or issue commands;
disconnect/reconnect cannot replay commands; failed login and invalid requests
do not interfere with Stop; shutdown releases the device lock cleanly.

## Phase 3 — Dashboard and Settings

Deliverables:

- Minimal responsive shell matching the mockup, existing theme palettes,
  keyboard navigation, visible focus, and sufficient contrast.
- Dashboard: equal-size Start/Stop, red Stop, Farm now, practice toggle, status,
  farm/break timers, and one activity window with debug filter/copy/export.
- Settings: clear basic controls, dropdowns for fixed choices, advanced options,
  developer raw timing fields, Save/Discard, and unsaved-change protection.
- Show a disconnected state rather than stale status implying the bot is
  stopped. Disable commands while disconnected and offer reconnection.
- Display server-owned countdown deadlines with frozen stopped snapshots;
  reconcile on reconnect and avoid trusting browser wall-clock differences.
- Multiple clients see shared changes. Saving a stale settings revision prompts
  a reload/merge rather than silently replacing another client's edits.

Acceptance: match reference layouts at desktop and narrow widths; no clipped
descriptions; no timer jumps after Stop/Start; repeated clicks are harmless;
closing the tab does not affect operation.

## Phase 4 — Browser calibration and deploy editor

Deliverables:

- Setup checklist with required/optional status, direct step/part selection,
  exact plain-language preparation instructions, Skip/Cancel, and refresh capture.
- Editors for tap points, rectangular areas, templates, colors, grid row/column
  counts, frame size, and the ordered farm deploy sequence.
- Sequence editor supports numbered circles, farm-only jitter radius preview,
  existing sequence parameters, editing/removal/reordering, and a save preview.
  Navigation and donation jitter remain unaffected.
- Each capture includes immutable ID, original dimensions, timestamp, and
  calibration revision. Map displayed coordinates back to original pixels under
  zoom, resize, letterboxing, and touch input; reject out-of-bounds selections.
- Save crops from the server's original captured frame. Detect resolution or
  calibration changes before saving and require recapture when inconsistent.
- Reuse calibration validation and transactions. Draft edits never overwrite
  saved calibration until Save; Cancel preserves existing files.
- Keep preparing the game manually supported. Automated battle preparation
  remains an explicit device-action job with Stop available throughout.

Acceptance: every calibration part works without a desktop picker; identical
points/areas round-trip correctly at several display sizes; canceled sessions
leave files intact; prepared farm captures open the editor reliably.

## Phase 5 — Library and Diagnostics parity

Deliverables:

- Library: paginated screenshots, collection summaries/pause, saved calibrations,
  backup/restore/rename/delete, existing profile support, and calibration checks.
- Diagnostics: existing supported actions, recovery recipes, device connection,
  screenshot viewer, debug export, and explicit close-game/Waydroid action.
- Destructive actions require clear confirmation. Safe downloads stay available
  while running; file mutations and device actions obey controller locks.
- Port first-launch simulation as a server-side isolated test profile, or mark
  it desktop-only until isolation is verified. Never rename production files
  opportunistically because a browser session disconnected.
- Handle large libraries without loading every image or log line into memory.

Acceptance: inventory shows feature parity or explicitly agreed deferrals;
backup/restore rollback works; simulated first launch preserves real settings;
large collections remain responsive and exports exclude credentials.

## Phase 6 — Installation, pilot, and rollback

Deliverables:

- Installer option for web dependencies and reproducible frontend assets. Normal
  users should not need Node.js; provide compiled assets through a release bundle
  or another documented build/distribution path. Verify source-checkout and
  package-data installation paths separately.
- Simple launcher and optional service setup with the required Waydroid session
  environment. Starting the web server does not imply Android/game is ready.
- README instructions: install, set password, open local/network URL, complete
  Setup, start/stop, update, and return to desktop mode.
- Pilot on Ubuntu with existing settings/calibration backed up. Start with
  read-only operations, then explicitly supervised device actions. Practice mode
  skips donations but is not a guarantee of no game interaction.
- Check a second LAN device, several browser sizes, multiple tabs, Wi-Fi loss,
  server restart, ADB failure, cancellation, and a sustained operation run.

Acceptance: user can operate and calibrate without RustDesk; frontend cannot
spawn duplicate device workers; settings survive upgrades; rollback requires
stopping the web service and launching the retained desktop GUI, not restoring
rewritten game logic. No automatic production cutover before these gates pass.

## Phase 7 — Optional browser game viewer

Begin after the core web interface passes its pilot. Streaming compatibility must
not delay the migration or become a requirement for normal bot operation.

Deliverables:

- "Open game" opens an optional panel or separate browser view with a live
  Android screen, useful for preparing calibration screens and recovering from
  unexpected menus. Keep the normal Dashboard free of a permanent video feed.
- Test an Android-only scrcpy browser bridge against the actual Waydroid device
  first. Measure latency, CPU/GPU load, bandwidth, and behavior during game play.
  Evaluate a compatible noVNC desktop setup as a fallback only if the Android
  bridge is unsuitable. Choose the transport after testing, not by assumption.
- Separate viewing from control. Viewing may coexist with automation only after
  load testing; manual clicks/swipes require explicitly stopping automation and
  waiting for normal, one-shot, diagnostic, and calibration device workers to
  release ownership. "Stopping" is not sufficient permission to send input.
- Give one authenticated browser client an exclusive, short-lived manual-control
  lease. Enforce it on the server and block Start, queued automatic attacks, and
  other device actions until released. Other clients can view but cannot control.
- Provide an explicit End control action. Closing the view, disconnecting, logout,
  or lease expiry releases control and any held touches/keys. Automation remains
  stopped until the user explicitly presses Start; do not silently resume it.
- Authenticate video and input connections, validate their origins, and protect
  transport. Do not expose raw ADB, VNC, or bridge ports to browser clients or
  bypass the controller by granting unrestricted bridge access.
- Map pointer/touch positions to actual Android coordinates, accounting for
  resizing, aspect ratio, and rotation. Handle taps and swipes first; leave extra
  gestures out unless supported and tested. Never change Android resolution just
  because the browser window resized.
- Start streaming only while requested, cap quality/frame rate, and stop its
  capture/encoding resources when the last viewer leaves. Keep Stop responsive
  and show a clear disconnected state without replaying stale input on reconnect.
- When used with Setup, complete manual preparation, release manual control,
  then request a fresh calibration screenshot. Use that immutable screenshot
  for editing and saving; do not save selections from a changing video frame.

Acceptance: viewing and basic manual navigation work from a second network
device without RustDesk; simultaneous clients cannot compete for input; no bot
taps occur during manual control; disconnect releases input safely; viewer
failure does not stop the web controller or corrupt calibration; stream load
does not materially degrade game operation or Stop response against the measured
baseline. If compatibility fails, retain screenshot calibration and document the
viewer as unavailable rather than making the core interface depend on it.

## Test priorities

1. Controller lifecycle races, Stop precedence, ownership locks, and queued farms.
2. Scheduling parity: frozen stopped timers, restart behavior, farm/break variance.
3. Authentication, origins, session expiry, WebSocket access, and file boundaries.
4. Settings validation/revision conflicts and calibration transaction rollback.
5. Screenshot coordinate transforms and deploy sequence/jitter round trips.
6. Offline browser journeys using a fake device and a fresh data directory.
7. Existing donation/farming regression tests and desktop smoke tests.
8. Ubuntu LAN pilot, disconnect recovery, bounded memory, and responsive Stop
   while exports or screenshots are slow.
9. Optional viewer: input ownership, lease expiry, held-input cleanup, coordinate
   mapping, unauthorized access, stream shutdown, and resource/latency comparisons.

## Scope and effort

This is a substantial interface migration, especially calibration and lifecycle
separation. A working Dashboard can arrive before full feature parity. Treat the
first two phases as the foundation, then deliver one page group at a time. Give
calendar estimates after the extraction prototype establishes the actual coupling
and test coverage; do not promise a quick full replacement based on the mockup.

First implementation task: inventory GUI-owned operations, define the shared
controller's status/command contract, and migrate Start/Stop with fake-device tests.
Do not begin by rewriting the game recognition or replacing all GUI files.

## Technical references

- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/): live
  communication and connection handling.
- [FastAPI server workers](https://fastapi.tiangolo.com/deployment/server-workers/):
  deployment process configuration. This project's single-owner requirement is
  why the initial server must use one worker.
- [Vite production build](https://vite.dev/guide/build.html): compile browser
  assets for normal deployment rather than running the development server.
- [scrcpy](https://github.com/Genymobile/scrcpy) and
  [ws-scrcpy-web](https://github.com/bilbospocketses/ws-scrcpy-web): Android
  mirroring and a candidate third-party browser bridge; Waydroid compatibility
  remains to be tested.
- [noVNC](https://novnc.com/): browser VNC client for the optional desktop-streaming
  fallback; a compatible server/capture setup is also required.
