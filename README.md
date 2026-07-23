# CoC Donation Bot

A helper program for **Clash of Clans on Waydroid (Ubuntu)** that:

1. Watches clan chat and **donates** troops, spells, and siege machines
2. Optionally runs **unranked Battle** attacks to farm elixir (electro dragons)

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

### Step 2 — Run the installer

Still inside the bot folder, run:

```bash
chmod +x scripts/setup_linux.sh
./scripts/setup_linux.sh
```

What this does (in plain language):

- Installs tools your computer needs (ADB, Python, window toolkit, etc.)
- Creates a private Python environment for the bot (a “venv”)
- Downloads troop/spell icons the bot uses

It may ask for your **password** (sudo). That is normal. Wait until it finishes.

If something went wrong halfway, you can run it again. To force a full redo:

```bash
./scripts/setup_linux.sh --force
```

---

### Step 3 — Connect Waydroid to the bot

The bot talks to the Android session through **ADB**. Think of ADB as a cable between your PC and Waydroid.

1. Start Waydroid and open Clash of Clans so the game is visible.
2. In a terminal, check that ADB sees the device:

```bash
adb devices
```

You want a line that looks like `192.168.240.112:5555` or `127.0.0.1:5555` with the word **device** (not “offline”).

If the list is empty, try connecting (common Waydroid address):

```bash
adb connect 192.168.240.112:5555
adb devices
```

If that address does not work, look up your Waydroid IP with:

```bash
waydroid status
```

or check Waydroid docs for your setup, then:

```bash
adb connect YOUR_IP:5555
```

3. Tell the bot which address to use (pick one):

- **In the app later:** open **Settings**, set **ADB device**, Save  
- **Or in a terminal for this session:**

```bash
export ADB_DEVICE=192.168.240.112:5555
```

(Replace with your real address from `adb devices`.)

---

### Step 4 — Teach the bot your screen (calibration)

Every screen size is a bit different. Calibration is a guided “click this button on the screenshot” process so the bot knows where Attack, Donate, chat, and so on are.

1. Open Waydroid and Clash of Clans (home village or clan chat as the wizard asks).
2. In a terminal:

```bash
cd ~/Projects/coc-donation-bot   # or your folder
source .venv/bin/activate
python scripts/calibrate.py
```

3. Follow the on-screen prompts. Click where it asks. Finish all required steps.
4. When done, files are saved under `data/calibrated.yaml` and `data/templates/`.

You can also start calibration later from the app: sidebar **Setup** → **Recalibrate All** (or select one step).

If you move to another PC with the **same** screen resolution, you can copy those `data/` files. If the resolution is different, calibrate again.

---

### Step 5 — Start the bot

1. Open Waydroid and Clash of Clans yourself.
2. In a terminal:

```bash
cd ~/Projects/coc-donation-bot
source .venv/bin/activate
python -m coc_bot.main
```

3. A dark control window opens (Steam-style layout):

| Sidebar | What it does |
|---------|----------------|
| **Home** | **Start** / **Stop**, farm attack, screenshot, activity log |
| **Settings** | How often to scan, donations, farm, breaks |
| **Setup** | Calibration status; recalibrate steps |
| **Tools** | One-shot tests (ADB check, open chat, etc.) |

4. Click **Start** on Home. The bot begins watching for donations (and farm, if enabled).

**Stop** leaves Clash open. **Close Waydroid + Clash** shuts the game and Waydroid session.

#### Optional desktop shortcut

```bash
cd ~/Projects/coc-donation-bot
chmod +x scripts/install_run_shortcut.sh
./scripts/install_run_shortcut.sh
```

Then use the **CoC Donation Bot** icon on your desktop (choose **Allow Launching** if Ubuntu asks).

---

## Optional — Farm attacks (elixir)

Farming runs **unranked Battle** (not ranked multiplayer): leave chat → Attack → Battle → deploy electro dragons along the village edge → wait → Return Home → reopen chat.

1. In **Setup**, run the **Farm** calibration step (Attack button, unranked Battle, Return Home, army slots as needed).
2. In game, leave your **electro dragon** army as the active preset.
3. In **Settings**, turn on farm and set the interval if you want.
4. Save Settings, then **Stop** and **Start** the bot so it reloads.
5. Or press **Farm attack now** on Home for a single attack.

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
| `adb devices` is empty or “offline” | Start Waydroid, then `adb connect YOUR_IP:5555` |
| Bot says not calibrated | Run Step 4 again, or use **Setup** → Recalibrate |
| Taps miss buttons | Recalibrate that step; check Settings → ADB device matches `adb devices` |
| No donation slots found | Recalibrate **slot colors** and **grid** |
| Screencap / screenshot fails | Restart Waydroid, wait ~15 seconds, try again |
| New computer | Re-run `./scripts/setup_linux.sh`, then calibrate if the screen size differs |
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
| `ADB_DEVICE` | Override device address (e.g. `192.168.240.112:5555`) |
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
  setup_linux.sh   # First-time install on Ubuntu
  calibrate.py     # Setup wizard from the terminal
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
- Optional unranked elixir farm with electro dragons
- Dry-run and offline replay for testing
