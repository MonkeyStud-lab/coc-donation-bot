# Running and advanced setup

Start with the [README](../README.md) for installation and guided calibration.
These instructions use the current app’s Dashboard, Settings, Setup, Library, and Diagnostics pages.

## Installation options

If you downloaded a ZIP, extract it and open Terminal in the extracted folder.
Run `bash scripts/get_started.sh`. Git update commands only work with a Git clone.

To install without opening the app:

```bash
bash scripts/setup_linux.sh
```

To reinstall dependencies and refresh downloaded assets:

```bash
bash scripts/setup_linux.sh --force
```

On Python 3.14, you can request the direct dependency versions tested on Linux:

```bash
bash scripts/setup_linux.sh --tested-deps
bash scripts/run_bot.sh
```

Other Python versions should use normal setup. The tested-dependency mode is
opt-in; the normal get-started launcher uses the normal setup mode.

The installer configures this source checkout. Keep the project folder:
installing a standalone Python wheel does not include all scripts and defaults.

## Terminal operation

For the opt-in browser interface, use [browser setup](WEB_UI.md). It covers
password setup, localhost/LAN access, browser calibration, and returning to the
desktop app. The web server still needs the same running Waydroid session.

From the project folder, activate the installed environment:

```bash
source .venv/bin/activate
```

Open the GUI:

```bash
python -m coc_bot.main
```

Run without the bot control window:

```bash
python -m coc_bot.main --no-gui
```

This hides only the bot’s GUI. Waydroid, Android, and the game still need to be
running. Press Ctrl+C to stop terminal operation.

Practice mode skips donation taps but still performs navigation. It does not
make live use permitted, and should not be treated as a blanket block on all
other game actions:

```bash
python -m coc_bot.main --dry-run --debug-save-frames
```

For testing recognition without controlling a device:

```bash
python scripts/replay_frame.py path/to/screenshot.png --annotate
```

The classic calibration wizard remains available:

```bash
python scripts/calibrate.py
```

Refresh game data and icons with `python scripts/sync_game_data.py --force`.

## Settings and local files

- `config/default.yaml`: defaults shipped with the project. Prefer the GUI for
  personal changes, so updates do not conflict with edited defaults.
- `data/user_settings.yaml`: settings saved by the GUI.
- `data/calibrated.yaml` and `data/templates/`: calibration and reference images.
- `data/calibration_backups/`: stored calibration snapshots and interface profiles.
- `data/runtime_state.json`: saved session and farm scheduling state.
- `data/collection/`: screenshots saved by smart collection.
- `data/debug/`: debug exports and diagnostic images.

`ADB_DEVICE` overrides the configured device address for the current process.
For example, `export ADB_DEVICE=YOUR_IP:5555` before launching.
`COC_BOT_CONFIG` selects an alternate calibrated YAML file; it is not a shortcut
for moving every other data file to a different folder.

## Backups and another computer

Use **Library → Saved calibrations → Save calibration backup** before recalibration. Restore, rename, or delete
snapshots from the same section. Backups include calibration and template images;
they do not replace a separate backup of your user settings.

**Library → Saved calibrations → Save interface profile** creates
a named calibration snapshot for a particular interface. Stop the bot before
switching profiles. After a game update, save the previous profile, recalibrate
changed parts, then save a new profile.

To move to another computer, install the project there and transfer your
calibration YAML and template images together, plus user settings if wanted.
Update the device address. A matching resolution alone does not guarantee a
matching game layout; check calibration and verify it before operation. Do not
copy the old `.venv` folder—run setup on the new machine.

## Screenshot collection

Enable **Settings → Screenshot collection**, choose daily and storage limits,
and Save, then Stop/Start. **Library → Screenshots** shows
collection status and opens the local review gallery. Collection does not
upload screenshots or automatically delete them. Images can contain player
names and chat; review them before sharing.

See [SMART_COLLECTION.md](SMART_COLLECTION.md) for selection rules and
[RELIABILITY.md](RELIABILITY.md) for calibration checks and verification.

## Background service

This is an advanced option. First confirm terminal operation with `--no-gui`
works. Starting the service does not start a Waydroid user session or open the
game. Avoid running the GUI bot and service simultaneously.

The supplied service needs editing before use: its current command opens the
GUI and its sample device address may not match your setup.

1. Copy `systemd/coc-donation-bot.service` to
   `~/.config/systemd/user/coc-donation-bot.service` (create that folder if needed).
2. Open your copied file in a text editor. Keep `WorkingDirectory` pointed at
   your checkout. Set the launch command to:

   ```ini
   ExecStart=%h/Projects/coc-donation-bot/.venv/bin/python -m coc_bot.main --no-gui
   ```

3. Replace the `ADB_DEVICE` value with your actual address. If the checkout is
   elsewhere, also adjust the command and `COC_BOT_CONFIG` path.
4. Enable the edited service:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now coc-donation-bot.service
   journalctl --user -u coc-donation-bot.service -f
   ```

Ctrl+C stops watching the log, not the service. Stop the service with:

```bash
systemctl --user stop coc-donation-bot.service
```

Disable automatic starts with `systemctl --user disable coc-donation-bot.service`.
Keeping user services running after logout can be enabled with
`sudo loginctl enable-linger "$USER"`; this does not ensure the Android session
or game will remain available.
