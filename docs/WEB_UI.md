# Browser interface

The browser dashboard is the main interface for the current app. It controls the
same Python engine as the retained desktop and terminal entry points. Waydroid
and Clash run on Linux; the browser can be on another device on the LAN.
Closing a tab leaves automation running. Server startup leaves automation stopped.

See the [README](../README.md) for installation and the
[current status](WEB_UI_MIGRATION_STATUS.md) for verification and remaining limits.
Historical migration reports are not current setup requirements.

## Install and open locally

For a new source installation, run `bash scripts/setup_linux.sh --web` first.
From the checkout, activate the environment and install browser/video components:

```bash
source .venv/bin/activate
python -m pip install -e '.[web,web-live]'
python scripts/setup_live_view.py
python -m coc_bot.web
```

Open **http://127.0.0.1:8765**. Later, `bash scripts/run_web.sh` launches the
installed server. `python -m coc_bot.main --web` is another localhost launcher;
`python -m coc_bot.main` still opens Tkinter rather than the browser.
Normal users do not need Node.js: compiled assets are included.

Keep the source checkout. A standalone wheel has browser assets but not every
project default or setup script. `--home /path/to/profile` selects a separate root
with `config/` and writable `data/`; it does not create a complete profile for you.

For ordinary source runs, open Waydroid and Clash manually as the desktop session
owner. In **Settings → Advanced**, set the ADB address and save, then run
**Diagnostics → Check device**. CasaOS instead uses its managed runtime and host
helper; its default dashboard port is **8767**. See [CasaOS](CASAOS_PACKAGE.md).

## Open from another device

Use the Linux host's specific private IP address and matching origin:

```bash
python -m coc_bot.web --host YOUR_LINUX_IP --origin http://YOUR_LINUX_IP:8765
```

Replace both placeholders, then open that URL on the other device. An origin
includes scheme, host, and port, without a trailing slash. Repeat `--origin` for
additional allowed addresses. Password-free mode rejects public, wildcard,
multicast, and link-local bind addresses.

No password or sign-in is required by default. Anyone who can reach the dashboard
can see the game and control its configuration. Host/origin, session, CSRF, and
WebSocket checks remain active; they are not a substitute for restricting network
access. Keep the port on a trusted LAN. Do not forward it directly to the internet.

Optional source-install password protection:

```bash
python -m coc_bot.web --set-password
python -m coc_bot.web --require-password
```

Normal startup ignores a previously saved password unless protection is enabled.
HTTP does not encrypt game images, commands, or passwords. For secure access,
use an HTTPS reverse proxy with its exact `--origin` and `--secure-cookie`, or
leave the server on localhost and connect through an SSH tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 YOUR_USER@YOUR_LINUX_ADDRESS
```

Open localhost on the connecting computer. This tunnels the dashboard's TCP
traffic; it does not by itself transport WebRTC's UDP video. Video may therefore
need a different permitted network path. No external STUN/TURN service is configured.

## Pages and ownership

- **Dashboard:** Start/Stop, Farm now, practice mode, Live view, timers, and activity.
- **Attacks:** Automatic attack, opponent preparation, army review, map editing,
  saved routines, supervised execution, and camera restoration.
- **Settings:** common/advanced controls, choices, timing presets, raw developer
  values, themes, upgrades, and collection limits.
- **Setup:** direct part selection or Calibrate missing/all. Follow instructions,
  capture, click/draw on the image, and save. Grid parts include row/column counts.
- **Library:** calibration backups, safety restores, named profiles, ZIP sharing,
  rename/delete, and a paged screenshot gallery/status.
- **Diagnostics:** device/screen checks, navigation tests, current screenshot,
  screenshot-based manual viewer, upgrades, activity/report downloads, and
  explicit close-game/Waydroid actions.

One device operation owns Android at a time. Calibration writes, tools, normal
operation, standalone attacks, and manual input cannot compete. Other browser
clients see the shared state; they cannot create a second controller. The device
lease also excludes desktop/terminal controllers targeting the same device.

**Stop** bypasses ordinary work and cancels active commands/waits, including a
standalone Farm now or Automatic attack. An input already delivered to Android
cannot be undone. Stopping remains visible until ownership is released. Clash
stays open; closing Waydroid is a separate action.

Practice mode skips normal donation taps. Navigation, manual tools, and attacks
can still affect the real game. It is not the offline preview.

## Settings and timers

Fields remain editable during normal bot operation. **Save** while stopped applies
without starting. **Save & restart** while running validates the draft, waits for
the current action to finish, and restarts with the same practice/run options.
**Stop** cancels the pending save/restart. Release manual control and finish
standalone tools before saving. A stale revision from another browser requires
Reload; edits made while applying remain unsaved drafts.

Stopped farm and session-limit countdowns freeze and resume without consuming the
paused duration. An already-started break expires by real time. Farm interval and
session-limit variance are separate settings. Farm now is an explicit request,
not a change to the saved schedule or selected attack method.

## Calibration and backups

For the donation title, elixir button, troop/spell areas and troop/spell grids,
the screenshot editor includes **Suggest area**. Open a donation panel first,
capture it, then press the button. Check the highlighted area and the numbered
grid; adjust them if needed, and press **Save** to apply that one part. A preview
does not change calibration or click anything in the game. Cancel discards it.

The initial helper supports the inspected English panel with seven columns,
two troop rows and one spell row. Other layouts can still be drawn manually.
Slot colors and the selected-elixir indicator remain manual steps: locating the
elixir button does not prove which resource mode is selected. See
[automatic calibration scope and evidence](PERCEPTION.md#donation-calibration-proposals).

Select a Setup part, prepare the game exactly as instructed, release manual
control, then **Capture screen**. Editors use immutable screenshots and original
Android dimensions; browser scaling/letterboxing does not change saved coordinates.
Stale captures or changed revisions cannot overwrite newer calibration. Skip and
Cancel preserve existing values.

For **Deploy tap sequence**, prepare an opponent and use **Pan and capture**, or
capture the already positioned view. Record army selections and map taps in order.
Numbered circles enclose the configured farm-only per-axis variation, including
diagonal offsets. This setting does not change donation/navigation jitter.
Automatic attacks do not require this sequence. See [attacks](ATTACK_REBUILD.md).

In Library, **Back up calibration** stores YAML and template images. **Export**
downloads a portable ZIP; **Import calibration** creates a stored backup and
**Restore** applies it, with a safety snapshot first. **Save profile** names an
interface calibration snapshot. These are not full-profile/game backups: settings,
planner artwork/routines, and Android account data need separate protection.
Use **Diagnostics → Check calibration** to inspect required fields/bounds; also
visually verify the actual game layout.

## Upgrades and game updates

**Diagnostics → Building upgrades / Army research → Check upgrades** reads
Suggested entries without spending. **Start recommended upgrade** is separate
and requires fresh checks. Automatic categories are disabled by default; enable
in Settings only after reviewing reserves and exclusions. See [upgrades](UPGRADES.md).

Managed CasaOS installations also expose **Update Clash**. Stop the bot and release
manual input before using it. It is an APK update, not a calibration repair. See
[game updates](CASAOS_PACKAGE.md#updating-clash).

## Prepare screens from the browser

**Diagnostics → Open game** is the slower screenshot viewer, capped at one frame
per second. Stop fully first. Click to tap, drag to swipe, and use explicit Android
Back/Home buttons. Close it before capturing calibration. It is distinct from video.

The viewer holds exclusive manual ownership. Closing/disconnecting/Stop releases
it after executing input returns. Automation does not resume automatically.

## Experimental live video

**Dashboard → Live view** streams the existing Android display using scrcpy and
WebRTC. Viewing can coexist with automation. Stop fully, then choose **Take control**
for taps/swipes and Android Back/Home. Releasing control, closing the view,
disconnecting, or Stop cancels manual control and queued gestures; it never
silently restarts automation. Clicks outside the displayed picture are ignored.

Only one live stream is supported. It does not change Android's resolution or
open another game instance. Closing it stops the encoder and its own ADB forward.
Audio is disabled; H.264 is passed through without host re-encoding, capped at
1280 pixels, 20 fps, and 2 Mbps. The pinned scrcpy server is checksum-verified and
stored privately under `data/live/`. Camera gestures use the same pinned server
without opening a stream or requiring Android root.

Capture starts after WebRTC negotiation to avoid a backlog of old frames. The
header reports decoded frame rate. A visible view with no newly decoded frames
for about twelve seconds reports an error and releases manual control. Hidden
tabs are excluded because browsers can suspend playback.

A working Android encoder and reachable local WebRTC UDP path are required.
Waydroid can freeze a background payload while ADB stays connected. Live view
can resume that existing payload when its IP matches the selected device and
check for re-freezing while open. On ordinary source installations it does not
start an absent session; CasaOS runtime startup is a separate managed operation.
Use the screenshot viewer when video is unavailable. LAN playback has been tested;
this is not a guarantee across Android encoders, firewalls, or browser versions.

## First-launch testing and updates

Enable Dev options and Save, then **Diagnostics → Simulate first launch**. This
opens Setup in a disposable profile without calibration/settings/runtime history.
Entering from the normal interface resets that test profile. **Exit first-launch
test** returns to normal. Temporary data is removed on clean shutdown. Both
profiles still share exclusive ownership of the real Android device.

For no game input, use `PYTHONPATH=src python scripts/preview_web_offline.py`.
First-launch simulation isolates files, not Android.

Before updates or switching to desktop, Stop, wait for Stopped, and release all
manual control. For source updates, stop the server, update dependencies/assets,
and restart with the same host/origin arguments. CasaOS needs a rebuilt/recreated
container. See [running and backups](RUNNING.md). Browser sessions reconnect after
server restart; automation remains stopped until Start.

## Development and verification

Serve exactly one Uvicorn worker. Shared `control/` services own lifecycle and jobs;
`web/` owns HTTP/WebSocket transport; top-level `web/` contains React/TypeScript.
Long game work runs in cancelable workers, not the server event loop. Events and
subscriber queues are bounded. Screenshot routes retain at most eight immutable
capture IDs and allowlisted files; never accept arbitrary host paths or commands.

After frontend edits:

```bash
cd web
corepack pnpm install --frozen-lockfile
corepack pnpm run build
cd ..
```

Commit rebuilt `src/coc_bot/web/static` assets. Vite development proxies to port
8765; add `http://localhost:5173` as an allowed API origin when using Vite.

```bash
python -m pip install -e '.[web,web-test]'
python -m unittest discover -s tests -v
PYTHONPATH=src python scripts/preview_web_offline.py
```

Desktop checks on headless Linux use `xvfb-run -a python scripts/verify_gui_offline.py`.
Offline checks do not establish fresh-host support or current-game compatibility.
