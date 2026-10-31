# CoC Bot

> **THIS CAN GET YOUR ACCOUNT PERMANENTLY BANNED.**
> Supercell prohibits bots and gameplay automation under its
> [Safe and Fair Play policy](https://supercell.com/en/safe-and-fair-play/).
> Educational intent and practice mode do not make live use permitted.
> This project is not affiliated with or endorsed by Supercell.

CoC Bot is a self-hosted Clash of Clans automation and computer-vision project.
It runs the game in Waydroid on Linux, reads Android screenshots, and sends
inputs through ADB. A browser dashboard controls donations, unranked attacks,
optional upgrades, calibration, and diagnostics.

Open the dashboard from another computer or phone on the same network. The game
and bot stay on the Linux host; ordinary use needs no remote desktop app.
Live view streams the game into the browser and offers manual control while
automation is stopped.

## What it does

- **Donations:** finds Donate buttons in clan chat, distinguishes them from event
  Trade buttons, and handles specific requests plus optional open/hybrid requests.
  It verifies elixir mode before donating and supports panels with different
  troop, spell, and siege capacities.
- **Unranked attacks:** automatic mass Electro Dragon attacks, editable map-based
  routines, or the original programmed tap sequence. Automatic/planner attacks
  map the opponent and verify individual deployments.
- **Upgrades:** follows the game's Suggested building upgrades and laboratory
  research, subject to availability, supported names, exclusions, and resource
  reserves. Pet upgrades use a separate slot and prefer unassigned pets.
  Previewing and starting an upgrade are separate actions.
- **Browser controls:** Start/Stop, resource refill status, activity logs,
  responsive settings, the Harbor interface, guided calibration, and calibration backups.
- **Builder Base (experimental):** account-visit checks for an equipped
  six-Night-Witch/Battle-Machine army, resource collection, supported Suggested
  building upgrades, and Night Witch research. Handles both battle stages,
  checks results, and returns to clan chat. Collection, attacks, building upgrades,
  and research have independent switches in Settings; all default to off.
  See [Builder Base setup and limitations](docs/BUILDER_BASE.md).
- **Recovery:** records unfinished attack and upgrade actions so a restart can
  inspect the game instead of blindly repeating them.
- **Automatic defensive layouts:** optional resource-only obstacle clearing,
  native layout imports, remaining-inventory placement, and verified activation
  in a spare Home Village slot. Current support requires a compatible native
  copy link and default-terrain recognition; TH2/3 have no automatic copy path.
  See [automatic layouts](docs/AUTOMATIC_LAYOUTS.md).
- **Development tools:** optional screenshot collection, labeling/export tools,
  offline checks, and an experimental screen-recognition observer.

This is an actively developed project, tested live on an Ubuntu/Waydroid host
with LAN browser clients. Recognition targets the English, landscape game
interface. Different layouts, resolutions, languages, hero skins, and sceneries
can require calibration or cause an operation to be skipped. The experimental
learned screen model logs predictions; it does not control taps.

## Installation

Use the **Linux browser installation** if Waydroid and Clash already work on
your computer. Use the **CasaOS package** to let CasaOS manage the app and a host
helper start Waydroid and the game. Both keep Android on the Linux host; the
browser displays video from that instance.

### Linux browser installation

You need an Ubuntu/Debian-based Linux computer, working Waydroid and Clash of
Clans, administrator access to install dependencies, and internet access for
the initial downloads. Sign into the game yourself before calibration.

Open Terminal and run:

```bash
sudo apt update
sudo apt install git
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/MonkeyStud-lab/coc-donation-bot.git
cd coc-donation-bot
bash scripts/setup_linux.sh --web
source .venv/bin/activate
python -m pip install -e '.[web,web-live]'
python scripts/setup_live_view.py
python -m coc_bot.web
```

Setup installs system packages, creates the private `.venv` Python environment,
and downloads recognition dependencies and unit icons. This can take several
minutes. This script does **not** install Waydroid or Clash; managed host setup
belongs to the CasaOS route below.

The Live view installer downloads a pinned, checksum-verified scrcpy Android
server. Automatic/planner camera gestures need that component too, even without
Live view open. Android root is not required.

Open **http://127.0.0.1:8765** on the Linux computer. Leave Terminal running;
closing the browser tab does not stop the server or bot. To reopen the dashboard
after stopping its server:

```bash
cd ~/Projects/coc-donation-bot
bash scripts/run_web.sh
```

For this installation, start Waydroid and Clash manually before connecting the
bot. The [browser guide](docs/WEB_UI.md) covers additional launch options.

### Access from another device

Find the Linux computer's local IP address in its network settings. Stop the
local server with Ctrl+C, then launch it with your address and matching URL:

```bash
source .venv/bin/activate
python -m coc_bot.web --host YOUR_LINUX_IP --origin http://YOUR_LINUX_IP:8765
```

Replace both occurrences of `YOUR_LINUX_IP`. Open that same URL in the other
device's browser. Use a specific private network address; password-free startup
does not accept a wildcard bind address such as `0.0.0.0`.

**There is no password by default. Anyone who can reach the dashboard can control
the game and edit its configuration.** Keep access on a trusted network; do not
expose the port directly to the internet. Optional password protection, SSH
tunneling, and HTTPS are covered in the
[browser guide](docs/WEB_UI.md#open-from-another-device).

### CasaOS package

The package runs the browser app in Docker and uses a Linux host helper to manage
Waydroid. App startup prepares Android, connects ADB, and launches Clash.
Gameplay automation stays stopped until you press **Start**.

The initial target is an x86-64 Ubuntu/Debian host with systemd, compatible binder
support, and working graphics, initially AMD/Intel. CasaOS and Docker must already
be installed. An isolated VM passed clean-host provisioning, APK installation,
and unattended headless service recovery after reboot, but Clash still exits
during startup there. Fresh-game and other hardware combinations still need
acceptance testing; this is not a universally tested one-click package. See the
[test record](docs/CASAOS_FRESH_INSTALL_TEST.md) and
[headless operation guide](docs/CASAOS_PACKAGE.md#headless-operation).

1. Download this repository on the CasaOS host using the clone commands above.
2. In its project folder, build the local image:

   ```bash
   bash packaging/casaos/build.sh
   ```

   The build downloads the public recognition artwork and gesture assets. It
   fails if required automatic-attack artwork is unavailable; you do not need
   another user's profile or icon cache. See the [offline image check](docs/CASAOS_PACKAGE.md#build-and-install).

3. In CasaOS, install a custom app by importing
   [`packaging/casaos/compose.yaml`](packaging/casaos/compose.yaml).
4. Review its setup service before installing. It has administrator-level host
   access to install Waydroid, Android images, display prerequisites, and the
   helper. The ordinary bot container runs without those privileges.
5. Open the CasaOS app tile. The default dashboard address is
   `http://YOUR_LINUX_IP:8767`. Follow its startup status and installation prompts.
   The first Android startup can take several minutes; keep the status page open.
6. For a fresh game installation, import your own trusted Clash APK archive,
   then sign in through **Live view → Take control**. Game APKs and account
   credentials are not included in the repository or container image.

To create an APK archive from an Android instance where Clash is already
installed, run this on a computer with Python 3, ADB, and access to that instance:

```bash
python3 scripts/export_clash_apks.py --device ANDROID_IP:5555 --output clash-apks.zip
```

Replace `ANDROID_IP` with the Android device's address. The archive contains
installation files, including split APKs, **not** your account or game data.

For an existing Waydroid installation, configure adoption/import before setup
rather than creating a competing controller. The
[CasaOS guide](docs/CASAOS_PACKAGE.md) explains session adoption, profile import,
compatibility checks, privileges, and startup recovery. A local image build is
the documented installation route; a published registry release is not assumed.

## First-time setup

1. **Get the game ready.** Sign in and open your home village. For manual Linux
   installations, run `waydroid status` to find its IP address. In
   **Settings → Advanced**, set **ADB device** to that address followed by
   `:5555`, then save. CasaOS manages its device address during startup.
2. **Check the connection.** Use **Tools → Device → Check device**. For a manual
   installation, these Terminal commands also help:

   ```bash
   adb connect ANDROID_IP:5555
   adb devices
   ```

   Replace `ANDROID_IP`. A working connection appears with the word `device`.
3. **Calibrate the interface.** Stop automation and release manual control.
   Choose **Setup → Set up missing**. Each part tells you which game screen
   to open. Capture it, click the requested button or draw its screen area, and
   save. Select a single part directly when needed; Skip/Cancel preserves its
   existing calibration. No separate image editor is needed.
4. **Verify donation resource selection.** Open a real donation request and
   select elixir. Calibrate both the elixir button position and **Selected elixir
   indicator**, including the selected button's border/background. Donations
   are refused if this mode cannot be verified.
5. **Back up calibration.** In **Library**, choose **Back up calibration**, then
   **Export** to keep a copy on another device. Restore creates a safety backup
   before applying a saved calibration.
6. **Watch the first run.** Press **Start** and observe a real request. Confirm
   it opens, donation quantities change, and the bot returns to clan chat. Check
   attack and upgrade flows separately before enabling their schedules.

Keep Android's resolution/layout consistent with calibration. Resizing the
browser does not resize Android. After a game UI update, back up the profile and
recalibrate changed parts.

## Everyday controls

- **Overview:** Start, Stop, Farm now, practice mode, resource readings,
  and one activity log. Live view is available on every page.
- **Accounts:** save the current village, add another Supercell ID, switch saved
  accounts, and choose each account's roles. See [Accounts](docs/ACCOUNTS.md).
- **Settings:** categorized donations, resource refill targets, upgrades,
  timing presets, and collection limits. Field help opens on demand;
  Advanced and Dev options retain their existing controls.
- **Setup:** guided calibration or direct access to one calibration part.
  Advanced reveals older-UI and fallback controls. The programmed deploy
  sequence is shown normally only for the sequence attack method.
- **Library:** separate Calibrations and Screenshots tabs, with backups/profiles,
  ZIP import/export, rename/delete, and the screenshot collection gallery.
- **Tools:** device/screen checks, current screenshot, navigation tests,
  upgrade previews, reports, and game/session controls. **Tools → Attacks** holds
  opponent mapping, army inspection, custom routines, and supervised execution.

**Stop** interrupts normal operation, standalone attacks, and tools. It leaves
Clash open and does not finish a battle for you. **Close Waydroid and Clash** is
a separate Tools action. Closing a browser tab leaves automation running.

Settings remain editable while the bot runs. **Save & restart** validates changes,
waits for the current donation/attack to finish, then restarts with the new settings.
**Stop** cancels a pending restart. While stopped, **Save** applies settings without
starting automation. Release manual control before saving.
The browser uses **Harbor**, a black, cobalt, and brass interface with a local
abstract wallpaper and WebGL refraction on its navigation and main panels. Page switching
is immediate, with no page animation. Reduced transparency and GPU limitations
receive an opaque fallback. See [Harbor](docs/UI_INTERFACES.md).

Automatic farming follows resource levels rather than a countdown. The bot does
not schedule session breaks or close Clash because of elapsed runtime. Old break
settings and saved break deadlines are ignored. Stop and recovery controls remain available.

**Practice mode is not a simulator.** It skips normal donation taps but still
allows navigation, and tools or attack actions can affect the real game. Use
the offline preview below for tests without a game connection.

### Live view

Overview's **Live view** uses WebRTC video rather than screenshot polling.
Watch during automation; to tap or swipe, stop the bot and choose **Take control**.
Release control before starting the bot, calibrating, or running another tool.
Releasing control does not restart automation.

Only one live stream/manual controller is supported at a time. Video requires
a working Android encoder and a permitted local WebRTC connection.
**Tools → Device → Current screenshot** or **Open game** provides a screenshot-based
alternative. See [Live view setup](docs/WEB_UI.md#experimental-live-video).

## Attacks

Automatic resource refill is **off by default**. The default attack method remains
**Programmed tap sequence**; explicitly choose another method in Settings.
**Farm now** on Overview uses that selection. Advanced mapping and custom-routine
tools are available under **Tools → Attacks**.

### Automatic Electro Dragon attacks

This mode needs no saved tap routine or hand-drawn map. It follows one built-in
mass Electro Dragon pattern rather than inventing a strategy for every base:

1. Return home, open unranked Battle, and pass the army confirmation.
2. Verify independent battle controls before treating the opponent as ready.
3. Zoom out and survey overlapping views to map the deployment boundary.
4. Read army identities/quantities from matching fresh screenshots.
5. Deploy Electro Dragons along a mapped edge, spread Rage spells inward, then
   deploy the siege machine and available heroes. Each hero ability tap follows
   its verified deployment.
6. Verify deployments from count decreases or deployed-card states. Never blindly
   repeat an uncertain map tap.
7. Recognize results, return home, restore the camera, and confirm clan chat.

Supported armies use Electro Dragons with optional Rage spells, one supported
siege machine, and up to four recognizable heroes. Unknown cards, unsupported
spells such as Recall, inconsistent counts, or an incomplete map stop deployment.
An entered but skipped match is cleaned up and gets a retry cooldown, rather
than repeatedly retrying the same unsupported army.

Connection, navigation calibration, unit artwork, and the pinned gesture server
are still required. This is not universal army/scenery support. Test one attack
before enabling its schedule.

For automatic refill attacks, select **automatic** under **Settings → Attack
method**, enable **Refill Home Village resources**, and save. Release manual
control and press **Start**. **Start refill below (%)** and **Refill to (%)**
default to 75% and 95%. Resources and actual storage capacities must be verified;
the bot rechecks after each battle. This works with one account or many.
Repeated unproductive attacks or unreadable counters defer refill while other
visit tasks continue. Old farm-interval settings no longer schedule attacks.

### Custom routines and the original sequence

**Planner** lets you review/correct the army, inspect the opponent map, and edit
ordered deployment, spell, ability, and wait steps. A saved routine must complete
a supervised test before it can be scheduled; editing it removes that approval.
Preparing an opponent enters a real match, so its scouting timer keeps running
while you edit.

**Programmed tap sequence** replays army-slot and map taps recorded under
**Setup → Farm → Deploy tap sequence**. Camera-pan and farm-only tap variation
settings belong to that fixed sequence. It needs a matching army bar, camera
position, and calibration.

All three methods watch for **Return Home** and **Troops expended** together on
two fresh results screenshots. Normal completion retains a calibrated timer
fallback if recognition fails; it does not normally wait out that timer when
results are recognized. See the [attack guide](docs/ATTACK_REBUILD.md) and
[battle completion checks](docs/BATTLE_COMPLETION.md).

## Optional upgrades

For a new village, **Settings → Upgrades → Village progression** adds construction
before upgrades, army preparation from verified unlocks/camp space, farming-unit
research priority, and a complete-building gate before Town Hall upgrades.
This opt-in pilot is being validated from TH2; later halls and automatic spell
editing are not fully validated. See [Home Village progression](docs/HOME_PROGRESSION.md)
before enabling it on an account.

Building/research/pet automation is **off by default**. First stop the bot and use
**Tools → Upgrades → Building upgrades / Army research / Pet upgrades → Check upgrades**. This reads
eligible entries without spending. **Start recommended upgrade** is a separate
action with confirmation and fresh checks.

Enable desired categories in **Settings → Upgrades** for automatic operation.
The bot checks builder/laboratory/pet availability, supported recommendations, price,
currency, and balance. Reserves are minimum balances to keep **after** paying.
You can also reserve builders and exclude names.
Builder and resource reserves default to zero; their optional overrides are in
Advanced. Visits check builders before long refill runs and return to chat after
each verified upgrade. Unfinished secondary visits resume later rather than
keeping the main donor away from requests indefinitely. Accounts shows each
category's last result, check time, and any reason for a deferred upgrade.

Pet upgrades use their own free slot and the dark-elixir reserve. Only unassigned
pets are eligible by default. **Allow upgrades of equipped pets** is a separate
setting because an upgrading pet may be unavailable for attacks.

Without Village progression, walls, heroes, the Town Hall, new building purchases,
equipment, and several army-production buildings are excluded. Village progression
can bulk-upgrade verified walls while keeping resource reserves. Buildings and research must be in the
Suggested list; pets must have a verified name, assignment, and price.
This path does not authorize gems, magic items, or buying missing
resources. An uncertain spending result blocks another purchase until the
pending action can be reconciled. See [upgrade rules and exclusions](docs/UPGRADES.md).

## Recovery, backups, and storage

Attack progress is recorded before game input. After an interruption, recovery
inspects the current screen instead of replaying deployments or abilities.
It waits through a verified battle, requires visual results to leave, and checks
home/camera/clan chat before clearing the interrupted operation. Recovery does
not use the ordinary timer-based Return Home fallback; it pauses if confirmation
cannot be obtained. Upgrade spending has a separate pending-action journal.

On CasaOS, three failed screenshot captures trigger a managed recovery check.
The app pauses inputs and verifies that Android's shell responds while its
graphics service times out before restarting the Waydroid session. A failed
video capture can request the same check. It verifies capture again before
resuming a previously running bot through its existing recovery journals.
Stop cancels recovery and prevents automatic resume. Restarts are limited to
two per hour, with a five-minute cooldown. Unconfirmed faults require manual
inspection; recovery never reinstalls Android or resets calibration/game data.

If recovery is pending, inspect the game and logs. Do not delete recovery files
just to force another attack or purchase. **Stop** leaves unfinished recovery
information intact. See [attack recovery](docs/ATTACK_REBUILD.md#interrupted-attacks-and-diagnostic-storage).

Persistent files live in the checkout for source installations, or inside
`/DATA/AppData/coc-bot/profile` for CasaOS:

- `data/calibrated.yaml` and `data/templates/`: calibration and reference images.
- `data/user_settings.yaml`: saved settings, separate from tracked defaults.
- `data/attack-planner/`: saved routines, reviewed artwork, and recovery state.
- `data/upgrades/` and `data/runtime_state.json`: upgrade and scheduling history.
- `data/collection/`: optional development screenshot collection.
- `data/debug/`: generated diagnostics, survey images, and execution journals.

Library calibration exports are **not** complete game/account backups. Back up
the full profile separately when migrating settings and routines. CasaOS host
setup creates verified installation backups under `/DATA/AppData/coc-bot/backups`.
Waydroid's Android/account data remains on the host and is not included in those
bot backups.

Logs rotate at 10 MB with seven-day retention. Generated attack diagnostics are
pruned between operations using seven-day, 1 GiB, and 40-group limits, preserving
the newest three groups per diagnostic family. Those protections can leave
storage above the target. Cleanup pauses during pending attack/camera recovery
and excludes calibration, backups, and reviewed datasets.

Screenshot collection is separate and opt-in. Defaults are 200 images per UTC
day and 5 GB; it skips duplicates and pauses at the storage cap rather than
deleting reviewed data. Screenshots, labels, learned artwork, and account data
are not automatically uploaded to GitHub. Review exports for player names, chat,
and device details before sharing. See [collection](docs/SMART_COLLECTION.md) and
[labeling](docs/ANNOTATION_WORKFLOW.md).

## Updating

### Bot updates

Stop automation, release manual control, and export a calibration backup first.
For the Linux source installation, stop the web server with Ctrl+C, then run:

```bash
cd ~/Projects/coc-donation-bot
git pull --ff-only
bash scripts/setup_linux.sh --web
source .venv/bin/activate
python -m pip install -e '.[web,web-live]'
python scripts/setup_live_view.py
python -m coc_bot.web
```

Use your existing `--host`/`--origin` arguments for LAN access. Refresh the browser
after startup. Normal updates preserve private settings/calibration. If Git
reports conflicting local edits, back those files up and resolve the conflict
rather than resetting them.

For CasaOS, Git pull alone does not update the running image. Pull the source,
rebuild with `bash packaging/casaos/build.sh`, then recreate the **bot** service
using the installed Compose configuration and new image. Preserve its environment,
profile mounts, and host-session settings. Code-only updates do not require
rerunning privileged host setup. Keep the previous image for rollback; rebuilding
the app does not update the separately installed host helper. See the
[CasaOS guide](docs/CASAOS_PACKAGE.md) for helper updates.

### Clash of Clans updates

After an initially trusted installation, CasaOS checks for newer Clash APKs when
its managed runtime starts. You can also stop the bot and choose
**Tools → System → Update Clash**. The updater uses a third-party APK source and
checks the package, newer version, and signing certificate before installing.
It does not uninstall Clash or clear account data. Initial installation still
requires your trusted APK archive; import remains the fallback.

After a game update, inspect the interface and preview affected actions before
restarting automation. Updating the APK does not update calibration or guarantee
recognition compatibility. See [updater details](docs/CASAOS_PACKAGE.md#updating-clash)
and [UI compatibility](docs/UI_COMPATIBILITY.md).

## Troubleshooting

- **No Android connection:** check `waydroid status`, reconnect the correct
  address, and confirm `adb devices` reports `device`. Use **Check device**.
- **CasaOS startup fails:** read runtime status and use Retry after resolving its
  cause. Stale Waydroid container state may need a host administrator to restart
  `waydroid-container.service`; do not reset Android or uninstall Clash.
- **Start is blocked:** check missing calibration, manual control, another bot
  process, or pending recovery. Only one operation can control Android at a time.
- **Donations are skipped:** check selected-elixir verification, Donate text,
  request eligibility, and the actual panel's grid calibration. Do not bypass
  resource checks to make it tap.
- **Attacks skip or stop early:** inspect the army/map report and activity.
  Unknown cards or missing boundary evidence deliberately block deployment.
- **Return Home misses:** recalibrate it on a real results screen. A longer timer
  does not correct coordinates.
- **Live view freezes:** check its frame-rate/error status and retry. A current
  screenshot helps distinguish a video problem from a stopped game.
- **Settings do not apply:** click Save or Save & restart. Resolve conflicts by
  reloading before editing again, and release manual control before saving.
- **Reporting a problem:** export activity and download the Tools report.
  Include the visible screen, intended action, and actual result. Remove private
  account/chat details before sharing screenshots or logs.

## Development

Python code lives under `src/coc_bot/`. Game behavior is in `donation/`, `attack/`,
`upgrades/`, and `vision/`; `runtime/` handles scheduling, ownership, and retention.
`control/` and `calibration/` provide shared services. FastAPI routes live in
`src/coc_bot/web/`; React/TypeScript source lives in `web/`.

Compiled browser assets are committed under `src/coc_bot/web/static/`, so normal
installation does not require Node.js. After editing frontend source:

```bash
cd web
corepack pnpm install --frozen-lockfile
corepack pnpm run build
cd ..
```

Commit rebuilt assets with the frontend change.

The default install uses Tesseract/OpenCV without EasyOCR/Torch. Enhanced capacity
OCR is optional; `bash scripts/setup_linux.sh --web --ocr` installs and preloads
it. See [Contributing](docs/CONTRIBUTING.md) for the optional CasaOS image build.

For offline Python checks:

```bash
source .venv/bin/activate
python -m pip install -e '.[web,web-test]'
python -m unittest discover -s tests -v
python scripts/verify_farm_offline.py
python scripts/verify_smart_collection.py
python scripts/verify_battle_completion.py
```

Use disposable profiles for tests, never live calibration. To explore the browser
with a fake device and no real ADB input:

```bash
PYTHONPATH=src python scripts/preview_web_offline.py
```

The original Tkinter interface remains available with `python -m coc_bot.main`;
terminal-only operation uses `python -m coc_bot.main --no-gui`. They share the
engine/profile formats, but newer planner and upgrade-preview controls are in
the browser. Stop the active controller before switching interfaces.

Further documentation:

- [Browser setup and controls](docs/WEB_UI.md)
- [CasaOS package and host integration](docs/CASAOS_PACKAGE.md)
- [Attack planner, automatic farming, and recovery](docs/ATTACK_REBUILD.md)
- [Battle completion recognition](docs/BATTLE_COMPLETION.md)
- [Suggested upgrades and safeguards](docs/UPGRADES.md)
- [Architecture](docs/HOW_IT_WORKS.md) and [reliability checks](docs/RELIABILITY.md)
- [Screenshot collection](docs/SMART_COLLECTION.md), [annotation workflow](docs/ANNOTATION_WORKFLOW.md),
  and [perception research](docs/PERCEPTION.md)
- [Advanced running options](docs/RUNNING.md) and [contributing](docs/CONTRIBUTING.md)

## License and contribution policy

The code uses the [MIT License](LICENSE). Maintainers do not provide help with
detection evasion, paid botting, or account farming/selling. Contributions that
improve reliability, usability, documentation, and computer-vision research are
welcome under the [contribution policy](docs/CONTRIBUTING.md).
