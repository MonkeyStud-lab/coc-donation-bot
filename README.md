# CoC Donation Bot

A helper program for **Clash of Clans on Waydroid (Ubuntu)** that:

1. Watches clan chat and **donates** troops, spells, and siege machines
2. Optionally runs **unranked Battle** attacks to farm elixir using a programmed deploy sequence

It works by looking at the game screen through ADB (Android Debug Bridge) and tapping buttons — the same idea as controlling a phone from your computer.

**Educational use only.** Automating live gameplay may violate Supercell’s Terms of Service. Use at your own risk.

---

## Documentation for builders

| Doc | Who it’s for |
|-----|----------------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | How the bot thinks: architecture, donation + farm flows, vision modes, leave safeguards |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Where to change code to add screens, farm behavior, donation rules, settings |

The rest of this README is the **install and use** guide for Ubuntu + Waydroid.

---

## What you need before starting

- A computer running **Ubuntu** (or similar Debian Linux)
- **Waydroid** already installed and working
- **Clash of Clans** installed inside Waydroid, and you can log in and play normally
- An internet connection the **first time** you install (to download packages and icons)

You do **not** need to be a programmer. You will copy and paste a few commands into a terminal.

---

## Step-by-step installation

### Step 1 — Get the bot files

Open a terminal (search for “Terminal” in your apps).

**Option A — with Git (recommended):**

```bash
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/MonkeyStud-lab/coc-donation-bot.git
cd coc-donation-bot
```

**Option B — ZIP download:**

1. Download the project ZIP from GitHub and unzip it
2. In the terminal, go into that folder, for example:

```bash
cd ~/Downloads/coc-donation-bot
```

(Use the real path where you unzipped it.)

---

### Step 2 — Install and open the app

Still inside the bot folder, run:

```bash
chmod +x scripts/get_started.sh
./scripts/get_started.sh
```

That script runs the Linux installer the first time (if needed), then opens the control window. The installer:

- Installs tools your computer needs (ADB, Python, window toolkit, `notify-send`, etc.)
- Creates a private Python environment for the bot (a “venv”)
- Downloads troop/spell icons the bot uses
- Offers an optional desktop shortcut at the end

It may ask for your **password** (sudo). That is normal.

To re-run setup only (or force a full redo):

```bash
./scripts/setup_linux.sh
./scripts/setup_linux.sh --force
```

---

### Step 3 — Connect Waydroid to the bot

The bot talks to the Android session through **ADB**. Think of ADB as a cable between your PC and Waydroid.

1. Start Waydroid and open Clash of Clans so the game is visible.
2. In the app on **Home**, use **Connect ADB** (also on the offline banner / Get started card).
3. Or in a terminal:

```bash
adb devices
```

You want a line that looks like `127.0.0.1:5555` or `HOST:5555` with the word **device** (not “offline”).

If the list is empty:

```bash
adb connect 127.0.0.1:5555
adb devices
```

If that address does not work, check `waydroid status` (or your emulator docs), then `adb connect YOUR_IP:5555`.

4. Tell the bot which address to use (pick one):

- **In the app:** **Settings** → **ADB device** → Save  
- **Or for this terminal session:** `export ADB_DEVICE=YOUR_IP:5555`

---

### Step 4 — Teach the bot your screen (calibration)

Every screen size is a bit different. Calibration shows a screenshot so you can mark Attack, Donate, chat regions, and so on.

1. Open Waydroid and Clash of Clans (home village or clan chat as needed).
2. In the app, open **Setup**.
3. Select a step or part → **Recalibrate Selected**, or use **Recalibrate All** for a full walkthrough. Everything uses an **in-app picker** (taps, ROIs, templates, slot colors, grid). **Classic terminal calibrator** is optional.
4. Finish all required steps (Home Get started checklist turns green when ADB + required calibration are OK). Tip: **Backup calibration** before experimenting.

Files land under `data/calibrated.yaml` and `data/templates/`.

Optional terminal wizard:

```bash
source .venv/bin/activate
python scripts/calibrate.py
```

If you move to another PC with the **same** screen resolution, you can copy those `data/` files. If the resolution is different, calibrate again.

---

### Step 5 — Start the bot

1. Open Waydroid and Clash of Clans yourself.
2. Launch the app (again with `./scripts/get_started.sh`, or `source .venv/bin/activate && python -m coc_bot.main`).
3. Control window pages:

| Sidebar | What it does |
|---------|----------------|
| **Home** | **Start** / **Stop**, Connect/Pick ADB, Get started, practice mode, farm readiness, live status, activity feed |
| **Settings** | Timing presets, practice mode, donations, farm, breaks; Dev options; Apply & restart when running |
| **Setup** | Full in-app calibration; Calibrate what’s missing; backup/restore; classic fallback |
| **Tools** | Fix-it recipes, ADB health, desktop shortcut, other one-shot tests |

4. Click **Start** on Home. The bot begins watching for donations (and farm, if enabled).

**Stop** leaves Clash open. **Close Waydroid + Clash** shuts the game and Waydroid session.

Desktop notifications (`notify-send`) fire when ADB drops while running, the bot stops, or Start is blocked for missing calibration.

#### Optional desktop shortcut

```bash
chmod +x scripts/install_run_shortcut.sh
./scripts/install_run_shortcut.sh
```

(`setup_linux.sh` can also offer this at the end.) Then use the **CoC Donation Bot** icon on your desktop (choose **Allow Launching** if Ubuntu asks).

---

## Optional — Farm attacks (elixir)

Farming runs **unranked Battle** (not ranked multiplayer): leave chat → Attack → Battle → run your programmed deploy taps → wait → Return Home → reopen chat.

1. In **Setup**, run the **Farm** calibration step (Attack button, unranked Battle, Return Home, army slots as needed).
2. In game, leave your **farm army** as the active preset.
3. In **Setup → Farm**, program a **deploy tap sequence** (army bar + map taps).
4. In **Settings**, turn on farm and set the interval if you want.
5. Save Settings, then **Stop** and **Start** the bot so it reloads.
6. Or press **Farm attack now** on Home for a single attack.

---

## Optional — Start automatically in the background

Only do this after the GUI works. Waydroid and Clash should already be able to run.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/coc-donation-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now coc-donation-bot.service
sudo loginctl enable-linger $USER
journalctl --user -u coc-donation-bot.service -f
```

That last command shows a live log. Press `Ctrl+C` to stop watching (the service keeps running).

---

## If something goes wrong

| Problem | What to try |
|---------|-------------|
| `adb devices` is empty or “offline” | Start Waydroid; Home → **Connect ADB**, or `adb connect YOUR_IP:5555` |
| Bot says not calibrated | Open **Setup** and finish required steps (Get started checklist) |
| Taps miss buttons | Recalibrate that part in Setup; check Settings → ADB device |
| No donation slots found | Recalibrate **slot colors** and **grid** in Setup (in-app) |
| Screencap / screenshot fails | Restart Waydroid, wait ~15 seconds, try again |
| Need logs for help | Home → **Copy logs** or **Export debug** (`data/debug/export_…`) |
| New computer | `./scripts/get_started.sh` (or `setup_linux.sh`), then calibrate if the screen size differs |
| Bot stuck | Use **Tools** → classify screen / open clan chat; or restart the bot |

---

## Advanced (power users)

Headless (no window):

```bash
python -m coc_bot.main --no-gui
```

Dry-run (detect only, no donation taps):

```bash
python -m coc_bot.main --dry-run --debug-save-frames
```

Offline vision test on a saved screenshot:

```bash
python scripts/replay_frame.py path/to/screenshot.png --annotate
```

Refresh unit icons:

```bash
python scripts/sync_game_data.py --force
```

### Config files

| File | Purpose |
|------|---------|
| `config/default.yaml` | Built-in defaults |
| `data/user_settings.yaml` | Your Settings from the GUI |
| `data/calibrated.yaml` | Points and regions from Setup |
| `data/runtime_state.json` | Session / farm timers |

Environment variables:

| Variable | Typical use |
|----------|-------------|
| `ADB_DEVICE` | Override device address (e.g. `127.0.0.1:5555`) |
| `COC_BOT_CONFIG` | Alternate calibrated YAML path |

### Project layout

```
src/coc_bot/
  gui/          # Control panel (Home / Settings / Setup / Tools)
  adb/          # Talks to Waydroid
  vision/       # Screen recognition
  donation/     # Clan chat donations
  attack/       # Unranked farm attacks
  runtime/      # Session limits and breaks
  calibration/  # Setup wizard
scripts/
  get_started.sh   # Setup if needed, then launch the GUI
  setup_linux.sh   # First-time install on Ubuntu
  calibrate.py     # Classic Setup wizard from the terminal
docs/
  HOW_IT_WORKS.md  # Architecture (read this to extend the bot)
  CONTRIBUTING.md  # Extension recipes
```

---

## Features (summary)

- ADB-only control (`screencap` + taps) — works under Wayland and remote desktop
- Troops, spells, and siege donations; partial fills when inventory is low
- Interactive setup wizard for unknown resolutions
- Session time limits with randomized breaks, then resume
- Optional unranked elixir farm with a programmed deploy sequence
- Dry-run and offline replay for testing
