# How the CoC Donation Bot works

This document explains the architecture for anyone who wants to understand or extend the project. For install and day-to-day use, see the [README](../README.md). For contribution tips, see [CONTRIBUTING.md](CONTRIBUTING.md).

For Shop / Clash Pass recovery and the optional learned screen observer, see
[Screen recognition and recovery](PERCEPTION.md). The observer cannot control
actions; the existing navigation rules remain authoritative.

**Educational use only.** Supercell prohibits bots and gameplay automation. See the [README warning](../README.md) before using this project.

---

## Big picture

The bot never reads game memory or uses an official API. It:

1. Takes **screenshots** of Clash of Clans inside Waydroid over **ADB**
2. **Classifies** what is on screen (home, clan chat, battle, results, …)
3. Issues **taps and swipes** as if a human were touching the display

```text
┌─────────────┐     screenshot      ┌──────────────────┐
│  Waydroid   │ ──────────────────► │  ScreenCapture   │
│  Clash of   │                     │  (adb/capture)   │
│  Clans      │ ◄────────────────── │  InputController │
└─────────────┘     tap / swipe     └────────┬─────────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │ ScreenClassifier │
                                    │  (vision/)       │
                                    └────────┬─────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
             Donation flow            Farm attack flow           Breaks / recovery
             (donation/)              (attack/)                  (runtime/)
```

The orchestrator is `DonationBot` in [`src/coc_bot/bot.py`](../src/coc_bot/bot.py). `main.py` is the command-line entry point. By default the bot runs behind a Tkinter GUI ([`src/coc_bot/gui/app.py`](../src/coc_bot/gui/app.py)); page builders are separated into `gui/page_views.py` and collection/profile controls into `gui/data_tools.py`.

---

## Repository layout

| Path | Purpose |
|------|---------|
| `src/coc_bot/` | All runtime Python code |
| `src/coc_bot/adb/` | ADB client, screencap, taps/swipes, launch/stop CoC |
| `src/coc_bot/vision/` | Screen classification, templates, ROIs, colors, OCR helpers |
| `src/coc_bot/donation/` | Clan chat scan, navigation, donation executor |
| `src/coc_bot/attack/` | Unranked farm: navigate, deploy, return home |
| `src/coc_bot/runtime/` | Session timer, breaks, persisted state |
| `src/coc_bot/calibration/` | Interactive setup wizard |
| `src/coc_bot/gui/` | Control window (Dashboard / Settings / Setup / Library / Diagnostics) |
| `config/` | Defaults (`default.yaml`), clan perk limits |
| `data/` | Calibration, user settings, templates, collected screenshots, runtime state |
| `scripts/` | Calibrate, verify, dry-run, desktop install helpers |
| `docs/` | This documentation |

---

## Config layers

Loaded by [`src/coc_bot/config.py`](../src/coc_bot/config.py) → `load_config()`:

1. **`config/default.yaml`** — factory defaults (timing, donation, farm, gui, ADB package name, …)
2. **`data/user_settings.yaml`** — deep-merged overrides from the Settings UI
3. **`data/calibrated.yaml`** — only calibration fields override settings: frame size, screen areas (ROIs), tap points, template paths, colors, grid, and the programmed farm deploy sequence
4. **Environment** — e.g. `ADB_DEVICE` overrides the ADB address

`COC_BOT_CONFIG` can select another calibration file; it does not isolate the rest of the data folder. Clan limits in `config/clan_perks.yaml` support the optional fill planner. The live donation path follows the game's colored/grey slots instead of calculating a housing budget.

The GUI checks donation readiness before Start. Donations also require an elixir-button tap and a reference image of its selected state; the executor refuses donation taps if selection cannot be confirmed. Farm needs its navigation targets and a programmed deploy sequence. Setup shows missing parts; [RELIABILITY.md](RELIABILITY.md) describes the independent safeguards.

---

## Vision and modes

### Why modes exist

Many Clash screens share colors (green buttons, white cards, sky). A donation panel can look a bit like battle results; home can look a bit like a battlefield. To reduce mix-ups, classification is **mode-scoped**.

**`BotMode`** ([`src/coc_bot/vision/screens.py`](../src/coc_bot/vision/screens.py)):

| Mode | Used when | What classify may return |
|------|-----------|---------------------------|
| `DONATE` | Watching / filling clan chat | Chat, donation panel, drifted home, popups |
| `ATTACK` | Farm attack pipeline | Attack menu, matchmaking, battle, results, home after leave |
| `HOME` | Village-focused moments | Home, attack menu, popups |
| `ANY` | Boot, recovery, leave-chat | Full unrestricted set |

### Screen types

`HOME`, `CLAN_CHAT`, `DONATION_PANEL`, `LOADING`, `POPUP`, `ATTACK_MENU`, `MATCHMAKING`, `BATTLE`, `BATTLE_RESULTS`, `LIVE_REPLAY`, `SHOP`, `CLASH_PASS`, `UNKNOWN`.

Shop and Clash Pass recovery runs in every mode, but a separate verified close-X match is required before tapping. Mode constraints narrow the possibilities; they do not prove a screen is correct.

Important heuristics (simplified):

- **Live battle chrome** (red End Battle / orange Next) vetoes false “Return Home” green blobs mid-fight.
- **Battle-results side silhouettes** (black character cutouts) mark Defeat/Victory and beat donation-panel false positives.
- **Matchmaking** uses templates / upper sky heuristics while waiting for the battlefield; leave no longer depends on white loading clouds.
- **Live Replay** (someone attacking *you*) is only considered when armed after a Clash relaunch.

Templates and tap points from calibration back these heuristics when present.

---

## Donation loop

State machine inside `DonationBot._loop_tick()`:

```text
scan_chat ──(find Donate)──► open_donation ──► donate ──► scan_chat
    │                              │
    └──(none)──► scroll_chat ──────┘
```

### GameState logging (diagnostic only)

[`runtime/game_state.py`](../src/coc_bot/runtime/game_state.py) tracks a high-level phase (`clan_chat`, `donating`, `in_battle`, …) in parallel with the loop strings above. Every transition is logged as:

- `GameState [ok]: A → B` — allowed by the sanity graph
- `GameState [unexpected]: A → B` — should not normally happen (still allowed; nothing is blocked)

Farm expands into finer phases (`home` → `attack_menu` → `matchmaking` → `in_battle` → …). Use unexpected warnings to spot desync; they do not change taps.

| Piece | Location | Role |
|-------|----------|------|
| Ensure chat open | `donation/navigator.py` | Open chat, dismiss popups, recover from wrong screens |
| Find request | `donation/chat_monitor.py` | Find green candidates, then verify Donate text; reject Trade and ambiguous labels |
| Kind (specific / open / hybrid) | `donation/request_parser.py` | Icons vs capacity bars |
| Fill | `donation/executor.py` | Tap visible troop+spell slots first, then scroll bars |

**Gating:** specific requests are always handled. Open/hybrid depend on `donate_open_requests` in settings.

Before filling, `donation/resource_mode.py` verifies that elixir is selected. If needed, it taps the calibrated elixir button without jitter and checks a fresh image. Missing or mismatched references stop filling rather than permitting gem donations.

**Anti-idle:** periodic tiny chat swipe so CoC does not kick for inactivity (`anti_idle_seconds`).

**Watchdog:** if a donation state stalls too long, recover with a broad reclassify (`BotMode.ANY`) and reopen chat.

Farm is only started when the bot is **not** mid `open_donation` / `donate`.

---

## Farm attack loop

Orchestrator: [`src/coc_bot/attack/farmer.py`](../src/coc_bot/attack/farmer.py).

```text
leave clan chat → Attack! → unranked Battle → battlefield
    → pan + replay programmed deploy tap sequence
    → watch for confirmed results; otherwise use the configured timer fallback
    → confirm home (Attack! / clan chat) — no early surrender
    → reopen clan chat
```

| Piece | Location |
|-------|----------|
| Navigation | `attack/navigator.py` |
| Deploy taps | `attack/deployer.py` + `farm_deploy_sequence` in `calibrated.yaml` |
| Triggers | GUI **Farm attack now**, or auto when `farm.enabled` + interval elapsed |

### Farm deploy sequence (required)

Farm **only** uses a programmed tap sequence. Without taps in `farm_deploy_sequence`, attacks abort before deploy.

Program from **Setup → Farm → Deploy tap sequence** (Recalibrate Selected), or Diagnostics: be on the battlefield first; the bot pans, shows a screenshot, and you click taps in order (numbered circles; radius = **farm deploy jitter**). The sequence stores its own **side / pan_swipes**; Settings → Farm deploy side / pan swipes are defaults for new sequences. Jitter applies only to sequence taps — donations use Timing → Tap jitter.

### Leave / Return Home safeguards

Battle completion uses two independent text anchors and keeps the existing timer as a fallback:

1. **Timer** from the recorded deployment start, before pan/tap replay (`farm.battle_timeout_seconds`, default **210** = 3m30s). This timestamp does not prove the first troop deployed successfully
2. During the wait, two consecutive screenshots must match both **Return Home** and **Troops expended**, with an enabled green button. When confirmed, tap the detected button. If recognition fails, the timer still **always** taps calibrated **Return Home** coordinates.
3. Then only look for **home village** (Attack! / open chat / clan chat) and open chat. Do not re-check results/battle heuristics (they false-trigger on home)
4. Never press Android **BACK** mid-battle (opens Surrender). On the Surrender dialog, tap **Cancel**

False “battle results” during search are ignored unless real side silhouettes appear.

---

## ADB stack

| Module | Role |
|--------|------|
| `adb/client.py` | `adb -s <device>` shell / exec-out, reconnect |
| `adb/capture.py` | Screencap (PNG / raw / pull fallbacks) |
| `adb/input.py` | Tap, swipe, BACK; optional jitter and delays |
| `adb/app.py` | Force-stop / launch CoC; wait past loading |

Dry-run / Practice mode skips donation taps but still sends navigation input. It is not an offline simulator or a blanket guarantee that all game actions are disabled.

Capture requests share a per-device lock and latest-frame cache. Normal captures have a 12-second total command budget; battle observations have three seconds. A device lease prevents another bot instance using the same ADB serial. See [RELIABILITY.md](RELIABILITY.md) for limits, including device aliases.

---

## Runtime: stop, breaks, farm timing

- **Stop** sets a shared flag, interrupts settling/waits, and cancels active ADB subprocesses. New actions must check the flag before input. Long sleeps use `interrupted_sleep` ([`src/coc_bot/stop.py`](../src/coc_bot/stop.py)). Clash stays open unless you use **Close Waydroid + Clash**.
- **Breaks** ([`runtime/breaks.py`](../src/coc_bot/runtime/breaks.py)): after a rolled session limit (`session_limit_seconds` ± `session_limit_variance_seconds`), force-stop CoC, wait a random break window, relaunch, reopen chat. State lives in `data/runtime_state.json`.
- **Farm clock:** any fought battle (deploy happened) advances `last_farm_at` for the interval (± variance), even if leave/chat confirm fails. Failures *before* deploy use the shorter retry cooldown.

GUI one-shot farm (**Farm attack now** without Start) wires the same stop flag into the farmer/navigator/deployer.

Farm and session clocks pause when the bot stops; resuming shifts the deadlines by the paused duration. Runtime persistence recovers from invalid saved JSON instead of preventing startup. These timers are separate from the battle's completion deadline.

---

## GUI

[`src/coc_bot/gui/app.py`](../src/coc_bot/gui/app.py):

| Page | Role |
|------|------|
| Dashboard | Start / Stop, Connect ADB / Pick device, Get started, calibrate what’s missing, practice mode, farm readiness, status chip, activity log, copy/export debug |
| Settings | Routine, Breaks, Appearance and Advanced tabs; contextual field help; unsaved-change guard; Apply & restart when running |
| Setup | Full in-app pickers, selected-part instructions and terminal fallback |
| Library | Screenshot gallery, calibration backups and interface profiles |
| Diagnostics | Fix-it recipes + one-shot debug actions (`gui/debug_actions.py`); desktop shortcut |

Window chrome (`last_page`, geometry, onboarding dismissed) lives in `data/gui_window.json`. Timing / practice / Dev options live under `gui:` in `user_settings.yaml`. Desktop toasts use `gui/notify.py` (`notify-send`). ADB auto-reconnects while the bot runs if the link drops.

Activity log is a loguru sink. The Play status chip shows the current phase (watching chat / donating / farming / break). **Show DEBUG messages in activity log** controls raw DEBUG noise (default off).

---

## Calibration

[`src/coc_bot/calibration/wizard.py`](../src/coc_bot/calibration/wizard.py) defines steps (home → chat → donation → colors/grid → farm). Setup **Recalibrate Selected** / **Recalibrate All** use in-app pickers ([`gui/setup_calib.py`](../src/coc_bot/gui/setup_calib.py) + `InteractivePicker`) for all part kinds (including slot colors and grid). **Classic terminal calibrator** still launches `scripts/calibrate.py` as a fallback.

Saves:

- Images under `data/templates/`
- Coordinates / ROIs in `data/calibrated.yaml`

Re-run calibration when resolution or UI layout changes. Backups and interface profiles preserve both `data/calibrated.yaml` and template images. Restore stages both together and uses a recovery journal if interrupted. Matching resolution alone does not prove compatibility: verify the game layout, language and scaling after moving to another computer.

---

## Mental model for debugging

1. **Wrong taps** → usually bad calibration (tap points / templates) or resolution scale
2. **Wrong screen label** → mode mismatch or heuristic clash; check `BotMode` and activity log screen names
3. **Stuck in battle leave** → check the results-confirmed or timer-fallback log, the Return Home tap, then home/clan-chat confirmation. Verify the calibrated Return Home target if the tap misses
4. **Stuck in chat** → donation panel close loop, popup, or ADB lag; Diagnostics → classify / screenshot help

Prefer fixing vision with **mode-scoped rules** and strong UI anchors (Attack!, silhouettes) over more global color thresholds.

---

## Related docs

- [CONTRIBUTING.md](CONTRIBUTING.md) — how to extend screens, farm, donations, settings
- [README.md](../README.md) — install and use on Ubuntu / Waydroid
- [RUNNING.md](RUNNING.md) — updates, terminal operation, backups and troubleshooting
- [BATTLE_COMPLETION.md](BATTLE_COMPLETION.md) — results detection and timer fallback
- [SMART_COLLECTION.md](SMART_COLLECTION.md) — collect and review useful screenshots

## Reliability and interface profiles

See [RELIABILITY.md](RELIABILITY.md) for selected-elixir verification, capture ownership, cooperative Stop, calibration restore recovery, interface profiles, and regression checks.
