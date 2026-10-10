# Browser interface

The browser interface is an opt-in replacement for the control window. The bot
and Waydroid still run on Linux. Closing a tab leaves the bot running; **Stop**
cancels normal operation and a standalone farm attack. Offline checks have passed;
live Ubuntu/LAN acceptance remains a rollout gate. Keep the desktop fallback.

## Install and open locally

In the project folder, for an existing installation:

```bash
source .venv/bin/activate
python -m pip install -e '.[web]'
python -m coc_bot.web
```

No password or sign-in is required. For a new installation,
run `bash scripts/setup_linux.sh --web` first.
Normal users do not need Node.js; compiled assets are included in the checkout
and Python package.

Keep the source checkout: a standalone wheel includes the browser assets but not
all project defaults/scripts. Advanced package installations need `--home` pointing
to a separate directory with the project's `config/` files and a writable `data/`.

Open **http://127.0.0.1:8765** on Linux to go directly to the dashboard. After installation,
`bash scripts/run_web.sh` or `python -m coc_bot.main --web` also launch the local
server. The existing `python -m coc_bot.main` still opens the desktop interface.

Open Waydroid and Clash manually. In **Settings**, enable **Advanced**, enter
the ADB device address, and save. **Diagnostics → Check device** attempts that
connection and verifies dimensions. Run the server as the user who owns the
Waydroid desktop session.

## Open from another device

Find Linux's local IP in network settings. If it is `192.168.1.50`, run:

```bash
python -m coc_bot.web --host 192.168.1.50 --origin http://192.168.1.50:8765
```

Open **http://192.168.1.50:8765** on your other device. Substitute your address.
Origins include scheme, host, and port, with no trailing slash. Repeat `--origin`
for additional allowed addresses. Allow the port only from your trusted LAN.

HTTP does not encrypt passwords, screenshots or commands. For secure access,
use an HTTPS reverse proxy in front of the loopback server, its exact HTTPS
origin, and `--secure-cookie`. Alternatively, leave the server on localhost and
use an SSH tunnel from the connecting computer:

```bash
ssh -L 8765:127.0.0.1:8765 YOUR_USER@YOUR_LINUX_ADDRESS
```

Then open localhost on that computer. Do not forward the port from your router
to the internet. Public hosting and automatic HTTPS installation are outside scope.

The dashboard opens directly and there is no Sign out button. Anyone who can reach this address can
control the bot, view the game, and edit its setup. Use this only on a trusted
LAN or localhost; this mode rejects public or wildcard bind addresses.
Origin, host, session-cookie and CSRF checks remain enabled. Password-free
sessions reconnect automatically after a service restart. No password file is needed,
and previously saved passwords are ignored during normal startup.

Password protection is optional for installations that need it: run
`python -m coc_bot.web --set-password` once, then launch with `--require-password`.
This is never required for normal local or LAN use.

## Use the pages

- **Dashboard:** Start/Stop, Farm now, practice mode, countdowns, one activity log.
  Stopped scheduling clocks freeze. An already-started mandatory break expires
  by real time.
- **Settings:** common controls first; **Advanced** reveals the rest. Timing
  presets simplify delays; **Dev options** exposes raw timings. Save while stopped,
  then Start. Another browser's save causes a conflict: Reload before retrying.
- **Setup:** select a part directly or follow missing/all calibration. Prepare
  the game as instructed, capture, click a point or draw a box, then Save. Grid
  parts ask for rows/columns. Skip and Cancel preserve existing calibration.
  Stale screenshots cannot overwrite newer calibration.
- **Library:** backup, restore with safety backup, rename/delete, ZIP import/export,
  profile saves, and a paged collection gallery/status. Import creates a stored
  backup; Restore applies it. Label/review decisions remain in the local review tool.
- **Diagnostics:** screenshots, navigation tests, deployment preview, game/session
  close, readiness checks, and report/activity downloads. These tools can interact
  with the game; practice mode only governs normal bot donation taps.

For **Deploy tap sequence**, prepare an opponent screen and use **Pan and capture**,
or capture an already-positioned view. Click army slots and deployment locations
in execution order. Variation is the maximum offset on each axis, in original
Android pixels; numbered circles enclose every possible offset, including diagonal
ones. It affects farm taps only. Undo/Clear edit the draft; Save applies it. Browser resizing never
changes Android resolution.

## Prepare screens from the browser

**Diagnostics → Open game** opens an optional screenshot viewer capped at one
frame per second. Stop and wait until fully stopped first. Click to tap or drag
to swipe; Android Back/Home are explicit buttons. Close before capturing calibration.

One browser owns manual control. While open, Start, farming, other device tools
and calibration writes are rejected. Closing, disconnecting, signing out or Stop
releases control after any executing command returns. Automation never resumes
automatically. This is a preparation prototype, not a scrcpy video stream. Live
Waydroid latency, rotation and resource use still need validation.

## Test first-time setup safely

Enable **Dev options**, Save, then **Diagnostics → Simulate first launch**.
It opens Setup with a disposable profile containing no calibration, settings or
runtime history. Entering from the normal interface resets this profile.
**Exit first-launch test** returns to your saved setup. Temporary files are removed
on clean server shutdown. Both modes share exclusive device ownership.

This isolates files, not the game: pan, capture and navigation use the real device.
Use the offline preview below if you want no live game interaction.

## Stop, update, and switch back

Press Stop and wait for **Stopped** before updating or switching interfaces.
**Stopping** means an executing command has not returned yet. Stop the web server
with Ctrl+C, update the checkout, reinstall web extras if dependencies changed,
then restart. Settings/calibration/runtime persist; browser sessions do not survive
server restarts. To switch back, stop the server and run `python -m coc_bot.main`.
No calibration conversion is needed.

## Development and checks

Shared services live in `control/` and `calibration/`; routes/authentication in
`src/coc_bot/web/`; React/TypeScript source in top-level `web/`. Desktop compatibility
imports preserve existing callers. Game recognition and donation/farming methods
are retained.

One cancelable worker owns each bot/tool operation. Stop bypasses queues. Existing
process-level leases prevent desktop/terminal competition. HTTP mutations check
session, CSRF, origin, payload size and idle ownership. Authenticated WebSockets
carry status and bounded, numbered events. At most eight immutable screenshot IDs
are retained. Saves validate coordinates/revisions and use journaled calibration/
template restore transactions. First-launch paths use propagated context rather
than changing the process-wide profile.

After editing frontend source:

```bash
cd web
corepack pnpm install --frozen-lockfile
corepack pnpm run build
cd ..
```

Include rebuilt `src/coc_bot/web/static` files with the change. Vite development
proxies to localhost:8765; explicitly allow `http://localhost:5173` as an API origin
when using Vite. Run one server worker; the supplied launcher enforces this.

```bash
python -m pip install -e '.[web,web-test]'
python -m unittest discover -s tests
python scripts/verify_gui_offline.py
PYTHONPATH=src python scripts/preview_web_offline.py
```

The preview uses disposable data and a fake device; it opens without a password.
Real ADB is forbidden. On headless Linux, run desktop checks through `xvfb-run -a`.

Before cutover, back up settings/calibration and test on Ubuntu: capture/readiness,
supervised Start/Stop and farming, original-pixel calibration, a second LAN device,
multiple tabs, network/server/device loss, and a sustained run. Measure startup,
capture and cancellation timings. See [migration status](WEB_UI_MIGRATION_STATUS.md).
