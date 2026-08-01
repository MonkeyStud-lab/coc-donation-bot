# How the CoC Donation Bot works

This document explains the architecture for anyone who wants to understand or extend the project. For install and day-to-day use, see the [README](../README.md). For contribution tips, see [CONTRIBUTING.md](CONTRIBUTING.md).

**Educational use only.** Automating Clash of Clans may violate Supercell’s Terms of Service.

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

The orchestrator is `DonationBot` in [`src/coc_bot/main.py`](../src/coc_bot/main.py). By default it runs behind a Tkinter GUI ([`src/coc_bot/gui/app.py`](../src/coc_bot/gui/app.py)).

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
| `src/coc_bot/gui/` | Control window (Home / Settings / Setup / Tools) |
| `config/` | Defaults (`default.yaml`), clan perk limits |
| `data/` | Calibration, user settings, templates, logs, runtime state |
| `scripts/` | Calibrate, verify, dry-run, desktop install helpers |
| `docs/` | This documentation |

---

## Config layers

Loaded by [`src/coc_bot/config.py`](../src/coc_bot/config.py) → `load_config()`:

1. **`config/default.yaml`** — factory defaults (timing, donation, farm, gui, ADB package name, …)
2. **`data/user_settings.yaml`** — deep-merged overrides from the Settings UI
3. **`data/calibrated.yaml`** — device-specific geometry: frame size, ROIs, tap points, template paths, colors, grid (written by the calibration wizard)
4. **Environment** — e.g. `ADB_DEVICE` overrides the ADB address

Clan donation housing limits come from `config/clan_perks.yaml` using your configured clan level.

The bot refuses to **Start** until calibration is complete (`frame_width` / `frame_height` + ROIs). Farm needs extra taps: `attack_button`, `unranked_battle`, `return_home`.

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

`HOME`, `CLAN_CHAT`, `DONATION_PANEL`, `LOADING`, `POPUP`, `ATTACK_MENU`, `MATCHMAKING`, `BATTLE`, `BATTLE_RESULTS`, `LIVE_REPLAY`, `UNKNOWN`.

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
| Find request | `donation/chat_monitor.py` | Match green Donate in chat ROI |
| Kind (specific / open / hybrid) | `donation/request_parser.py` | Icons vs capacity bars |
| Fill | `donation/executor.py` | Tap colored troop/spell slots; scroll bars |

**Gating:** specific requests are always handled. Open/hybrid depend on `donate_open_requests` in settings.

**Anti-idle:** periodic tiny chat swipe so CoC does not kick for inactivity (`anti_idle_seconds`).

**Watchdog:** if a donation state stalls too long, recover with a broad reclassify (`BotMode.ANY`) and reopen chat.

Farm is only started when the bot is **not** mid `open_donation` / `donate`.

---

## Farm attack loop

Orchestrator: [`src/coc_bot/attack/farmer.py`](../src/coc_bot/attack/farmer.py).

```text
leave clan chat → Attack! → unranked Battle → battlefield
    → pan + deploy army (custom tap sequence OR built-in e-drag recipe)
    → wait 3m30s from first deploy (configurable), then tap Return Home coords
    → confirm home (Attack! / clan chat) — no early surrender
    → reopen clan chat
```

| Piece | Location |
|-------|----------|
| Navigation | `attack/navigator.py` |
| Deploy recipe | `attack/deployer.py` |
| Custom army taps | Tools → **Farm: program deploy sequence** → `farm_deploy_sequence` in `calibrated.yaml` |
| Triggers | GUI **Farm attack now**, or auto when `farm.enabled` + interval elapsed |

### Custom farm deploy sequence

If `farm_deploy_sequence.taps` is non-empty, farm **replays those ordered taps** (army-bar selects + map drops) after panning with the **side / pan_swipes stored in the sequence**. The built-in e-drag / rage / siege / hero settings are unused until you **Tools → Farm: clear deploy sequence**.

Program from **Setup → Farm → Deploy tap sequence** (Recalibrate Selected), or Tools: be on the battlefield first; the bot pans, shows a screenshot, and you click taps in order (numbered circles; radius = **farm deploy jitter**). That jitter applies only to custom farm sequence taps — donations use Timing → Tap jitter. Jitter for farm deploy is also a number field under Settings → Farm (slider lives in the editor only).

### Leave / Return Home safeguards

Leaving after a fight used to rely heavily on vision mid-battle; that was flaky. The farm path is now intentionally simple:

1. **Timer** from first troop deploy (`farm.battle_timeout_seconds`, default **210** = 3m30s)
2. When the timer ends, **always** tap calibrated **Return Home** coordinates — no vision, no skip
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

Dry-run mode still navigates but skips donation taps (navigation input stays live so the bot can move around the UI safely for testing).

---

## Runtime: stop, breaks, farm timing

- **Stop** sets a cooperative flag. Long sleeps use `interrupted_sleep` ([`src/coc_bot/stop.py`](../src/coc_bot/stop.py)). Clash stays open unless you use **Close Waydroid + Clash**.
- **Breaks** ([`runtime/breaks.py`](../src/coc_bot/runtime/breaks.py)): after enough active time, force-stop CoC, wait a random break window, relaunch, reopen chat. State lives in `data/runtime_state.json`.
- **Farm clock:** any fought battle (deploy happened) advances `last_farm_at` for the interval, even if leave/chat confirm fails. Failures *before* deploy use the shorter retry cooldown.

GUI one-shot farm (**Farm attack now** without Start) wires the same stop flag into the farmer/navigator/deployer.

---

## GUI

[`src/coc_bot/gui/app.py`](../src/coc_bot/gui/app.py):

| Page | Role |
|------|------|
| Home | Start / Stop, farm now, activity log, Waydroid close |
| Settings | Editable fields from `gui/settings_fields.py` → `user_settings.yaml` |
| Setup | Calibration checklist + recalibrate steps |
| Tools | One-shot debug actions (`gui/debug_actions.py`) |

Activity log is a loguru sink. **Show DEBUG messages in activity log** (Interface settings) controls whether DEBUG lines appear there (default off).

---

## Calibration

[`src/coc_bot/calibration/wizard.py`](../src/coc_bot/calibration/wizard.py) walks through home → chat → donation → colors/grid → farm taps and saves:

- Images under `data/templates/`
- Coordinates / ROIs in `data/calibrated.yaml`

Re-run calibration when resolution or UI layout changes. Same resolution on another PC can often reuse `data/calibrated.yaml` + `data/templates/`.

---

## Mental model for debugging

1. **Wrong taps** → usually bad calibration (tap points / templates) or resolution scale
2. **Wrong screen label** → mode mismatch or heuristic clash; check `BotMode` and activity log screen names
3. **Stuck in battle leave** → look for Attack! / clan-chat confirm logs; scenery false greens should clear when End Battle is still visible
4. **Stuck in chat** → donation panel close loop, popup, or ADB lag; Tools → classify / screenshot help

Prefer fixing vision with **mode-scoped rules** and strong UI anchors (Attack!, silhouettes) over more global color thresholds.

---

## Related docs

- [CONTRIBUTING.md](CONTRIBUTING.md) — how to extend screens, farm, donations, settings
- [README.md](../README.md) — install and use on Ubuntu / Waydroid
