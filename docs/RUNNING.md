# Running, updating, and moving the app

Start with the [README](../README.md) for installation. The browser dashboard is
the main interface; desktop/terminal remain available. Use [CasaOS setup](CASAOS_PACKAGE.md)
for the managed installation and [browser controls](WEB_UI.md) for page behavior.

## Source installation

From a Git clone or extracted source folder:

```bash
bash scripts/setup_linux.sh --web
source .venv/bin/activate
python -m pip install -e '.[web,web-live]'
python scripts/setup_live_view.py
python -m coc_bot.web
```

Open localhost port 8765. Waydroid and Clash must already work and be opened
manually for this route. The source installer does not install Android.
Git update commands require a clone, not an extracted ZIP.

Later, `bash scripts/run_web.sh` launches the installed server. LAN access needs
an explicit private `--host` and matching `--origin`; no password is required by
default. Anyone who can reach it can control the app. See [network access](WEB_UI.md#open-from-another-device).

`bash scripts/setup_linux.sh --force --web` refreshes dependencies/assets.
Python 3.14 installations can opt into tested direct dependency versions with
`bash scripts/setup_linux.sh --tested-deps --web`. Other Python versions use
normal setup. Keep the checkout: standalone wheels omit some defaults/scripts.

## Desktop and terminal alternatives

Activate `.venv`, then choose one controller:

```bash
python -m coc_bot.main
```

This opens the retained Tkinter GUI. `bash scripts/get_started.sh` performs its
setup check and opens that GUI too; it does not select the browser interface.

```bash
python -m coc_bot.main --no-gui
```

This starts normal automation directly in Terminal. Android/the game still need
to be running. Ctrl+C stops it. Do not run this alongside a CasaOS/browser bot.

```bash
python -m coc_bot.main --dry-run --debug-save-frames
```

Practice/dry-run skips donation taps, not every game input. Navigation, farm,
and separate tools can still act. For offline recognition or UI work instead:

```bash
python scripts/replay_frame.py path/to/screenshot.png --annotate
PYTHONPATH=src python scripts/preview_web_offline.py
```

The classic local calibrator is `python scripts/calibrate.py`; it shares the
calibration schema with browser Setup. Refresh downloaded unit data/icons with
`python scripts/sync_game_data.py --force` when needed.

## Profile roots and environment

A source run uses the checkout's configuration/data by default. CasaOS uses
`/DATA/AppData/coc-bot/profile` on the host, mounted as `/profile` inside its bot
container. The profile contains:

- `config/default.yaml`: shipped base configuration.
- `data/user_settings.yaml`: personal overrides saved through Settings.
- `data/calibrated.yaml` and `data/templates/`: calibration and reference images.
- `data/calibration_backups/`: saved calibrations and named interface profiles.
- `data/attack-planner/`: routines, reviewed unit artwork, and attack/camera recovery.
- `data/upgrades/`: spending intent/history.
- `data/runtime_state.json`: farm/session clocks and completed attack identity.
- `data/collection/`: optional selected screenshot dataset.
- `data/debug/`: generated diagnostic evidence.
- `data/live/`: pinned video/gesture server; reproducible with its installer.

Prefer Settings over editing tracked defaults. `ADB_DEVICE` overrides the selected
device in a source process. `COC_BOT_HOME` or the web launcher's `--home` selects
a complete profile root; populate its `config/` and writable `data/` first.
`COC_BOT_CONFIG` selects an alternate calibration YAML only, not every data path.
First-launch testing uses its own context-scoped profile and shared device lease.

## Stop, settings, and recovery

Stop interrupts normal and one-shot operations, leaving Clash open. Wait for
Stopped before transferring ownership or updating. Closing a browser tab does
not stop automation. Closing the game/Waydroid is an explicit Diagnostics action.

Browser settings are always editable. Save while stopped applies without starting;
Save & restart while running validates, waits for the current action, and restarts.
Stop cancels the queued save/restart. Conflicting browser revisions require Reload.
Farm/session countdowns pause while stopped; an already-started break expires in
real time. Saving settings is not a way to reset an uncertain attack or purchase.

After a crash or interrupted attack, Start reconciles pending work before normal
operation. It never replays deployments or purchases just because the process
restarted. If it cannot verify home/results/camera or a purchase outcome, inspect
the game and logs. Keep pending journals intact. See [attack recovery](ATTACK_REBUILD.md#interrupted-attacks-and-diagnostic-storage)
and [upgrade recovery](UPGRADES.md#stops-interruptions-and-uncertain-results).

## Backups and migration

Stop the bot and release manual control before taking a consistent backup.

**Library → Back up calibration** saves YAML and template images. Export downloads
a portable ZIP; Import calibration stores an archive, and Restore applies it with
a safety backup. Save profile creates a named calibration snapshot. Rename/Delete
apply to stored backups, not Android account data.

These Library archives do not include personal settings, planner routines/learned
artwork, upgrade journals, or the game account. For migration, separately copy the
full `config/` and `data/` profile while idle, including pending recovery markers.
Keep sensitive copies private and preserve permissions. Use a separate destination;
do not merge a live profile with another running controller.

For CasaOS, also retain the profile's private `.android/` identity when making a
complete profile backup. It authorizes the app's Android connection, not a game
account. Setup can create/enroll an identity for newly managed Android images;
it does not overwrite an existing complete key pair.

On the new host, install dependencies rather than copying `.venv`. Update the ADB
address, check resolution/layout/language, and test calibration. Planner approval
is device-specific; a saved routine may need another supervised run. Transferring
a profile does not transfer Waydroid's Android app data or sign-in.

CasaOS host installation snapshots include configuration, calibration/templates,
user settings, runtime state, planner routines/artwork/recovery files, and upgrade
journals with checksum verification. They exclude screenshot collections, caches,
and Android account data. See [backup scope](CASAOS_PACKAGE.md#data-protection).

## Updates

For source installation, Stop, close manual control, stop the server, then:

```bash
git pull --ff-only
bash scripts/setup_linux.sh --web
source .venv/bin/activate
python -m pip install -e '.[web,web-live]'
python scripts/setup_live_view.py
python -m coc_bot.web
```

Reuse your host/origin arguments for LAN access. Refresh the browser. Preserve
local edits if Git reports a conflict; do not reset private calibration/defaults.

For CasaOS, pull and build the image, then recreate the bot service using the
installed Compose configuration, environment, and mounts. A checkout update alone
does not replace container code. Keep the old image and a consistent profile
backup for rollback. Host-helper updates are separate; routine code updates do
not require rerunning privileged setup. Follow [CasaOS updates](CASAOS_PACKAGE.md#updating-the-bot-and-helper).

After a Clash update, APK installation and calibration compatibility are separate
checks. Inspect changed menus and test affected operations before enabling them.

## Screenshot and log storage

Enable Screenshot collection in Settings and Save / Save & restart. Browser
Library shows the paged gallery and status. The full review HTML can be opened
on the host or copied batch; see [collection](SMART_COLLECTION.md).

Collection pauses at its configured storage cap and does not prune reviewed data.
Generated attack diagnostics have a separate bounded cleanup policy. Logs rotate
at 10 MB with seven-day retention. See [storage safeguards](RELIABILITY.md#storage-and-private-data).

## Optional user service

CasaOS already manages its web container; do not also enable a competing user
service. For a source installation, copy `systemd/coc-donation-bot.service` into
`~/.config/systemd/user/`, create the directory if necessary, and edit the copy.
The supplied template still launches the desktop GUI. For a browser service use:

```ini
WorkingDirectory=%h/Projects/coc-donation-bot
ExecStart=%h/Projects/coc-donation-bot/.venv/bin/python -m coc_bot.web
```

Adjust paths and `ADB_DEVICE`; remove or update `COC_BOT_CONFIG` if needed. Add
explicit private `--host` / `--origin` arguments for LAN access. To run automation
directly instead, use `python -m coc_bot.main --no-gui` in ExecStart. The web server
starts stopped; the terminal command starts automation.

```bash
systemctl --user daemon-reload
systemctl --user enable --now coc-donation-bot.service
journalctl --user -u coc-donation-bot.service -f
```

Ctrl+C stops log watching, not the service. Stop it with
`systemctl --user stop coc-donation-bot.service`; disable future starts with
`systemctl --user disable coc-donation-bot.service`.

A user service does not create a Waydroid display/session or guarantee Android
availability before login. `sudo loginctl enable-linger "$USER"` keeps user
services alive after logout but does not solve display prerequisites. Managed
CasaOS startup is a separate route with explicit host setup.
