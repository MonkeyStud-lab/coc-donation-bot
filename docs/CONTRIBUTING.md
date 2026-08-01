# Contributing / extending the bot

This guide is for developers who want to change or build on the project. Read [HOW_IT_WORKS.md](HOW_IT_WORKS.md) first for the architecture.

---

## Setup for development

```bash
cd ~/Projects/coc-donation-bot   # or your clone
source .venv/bin/activate        # after ./scripts/setup_linux.sh
pip install -e .
```

Run without GUI for quick terminal tests:

```bash
python -m coc_bot.main --no-gui --dry-run
```

Useful one-shots:

```bash
python scripts/calibrate.py --step farm
python scripts/verify_farm_offline.py
python scripts/save_screenshot.py
```

Prefer small, focused changes. Match existing naming and logging style (`loguru`). Do not commit secrets, account files, or huge binary dumps under `data/` unless they are intended templates.

---

## Extension recipes

### 1. Add or refine a screen type

1. Add a value to `ScreenType` in [`src/coc_bot/vision/screens.py`](../src/coc_bot/vision/screens.py) (if needed).
2. Implement a heuristic and/or template check.
3. Wire it into the right `_classify_*` method(s) for `BotMode` (`HOME` / `DONATE` / `ATTACK` / `ANY`).
4. Update navigators that branch on that screen (`donation/navigator.py`, `attack/navigator.py`, `main.py` recovery).
5. Optionally add a calibration step / template key in [`calibration/wizard.py`](../src/coc_bot/calibration/wizard.py).

**Rule of thumb:** if two screens look alike, disambiguate with **BotMode** or **flow phase** (what the bot was doing), not only with stricter colors.

### 2. Change farm combat (deploy recipe)

| Goal | File |
|------|------|
| Order of actions / success criteria | `attack/farmer.py` |
| Matchmaking, results, Return Home | `attack/navigator.py` |
| Pan + replay programmed deploy sequence | `attack/deployer.py` |
| Programmable tap editor | `calibration/sequence_picker.py` + Tools actions in `gui/debug_actions.py` |
| Tunables | `config/default.yaml` → `farm:` + `BotConfig` in `config.py` + GUI field in `gui/settings_fields.py` |
| New tap targets | Wizard step `"farm"` |

Farm deploy requires `farm_deploy_sequence.taps` (no built-in e-drag recipe).
Keep the simple post-deploy timer in `wait_for_battle_end` (wait N seconds from first
deploy, then **force-tap** calibrated `return_home` coords with no vision skip). After
that tap, leave confirmation should **only** look for home village (Attack! / chat) —
never results/battle heuristics.

### 3. Change donation behavior

| Goal | File |
|------|------|
| When a request is eligible | `DonationBot._should_handle_request` in `main.py` |
| Specific vs open vs hybrid | `donation/request_parser.py` |
| How slots are filled | `donation/executor.py` |
| Finding Donate in chat | `donation/chat_monitor.py` |
| Chat open/close / panels | `donation/navigator.py` |

There is experimental budget-aware code (`fill_planner.py`, `inventory.py`, `icon_matcher.py`). The **live** path today is colored-slot filling. Wire planner carefully if you revive it.

### 4. Add a Settings UI field

1. Add a default in `config/default.yaml` (and `BotConfig` + `load_config` mapping).
2. Append a `SettingField` in [`src/coc_bot/gui/settings_fields.py`](../src/coc_bot/gui/settings_fields.py) with the correct `yaml_path`.
3. Save from the GUI writes `data/user_settings.yaml`. Running bot loops usually need Stop → Start to pick up timing/farm changes; GUI-only filters (e.g. activity DEBUG) may apply immediately.

### 5. Add a Tools (debug) action

Register in `DEBUG_ACTIONS` and implement on `DebugSession` in [`src/coc_bot/gui/debug_actions.py`](../src/coc_bot/gui/debug_actions.py).

### 6. Cooperative Stop

Any new long wait must honor `stop_check` / `interrupted_sleep` so the GUI **Stop** button stays responsive (including farm one-shot).

---

## Testing checklist (Waydroid)

Manual checks beat unit tests for this project:

1. **Donation:** open request + specific request; panel opens and closes cleanly.
2. **Farm:** Attack → Battle → deploy → wait timer → Return Home → clan chat opens.
3. **False leave:** mid-fight green scenery should not eject you (End Battle still visible).
4. **Stop:** during matchmaking wait and during donation scroll.
5. **Break (optional):** shorten `session_limit_seconds` in settings for a dry test, then restore.

Offline helpers: `scripts/verify_farm_offline.py` (no live match required for some checks).

---

## Code style expectations

- Prefer clarity over clever abstractions.
- Log **why** a decision was made (`logger.info` for flow; `logger.debug` for noise).
- Avoid editing the plan files under `.cursor/plans/` in PRs.
- Do not force-push `main` or commit `.env` / credentials.

---

## Suggested first contributions

- Improve a single flaky heuristic with before/after screenshots in `data/debug/`
- Add a GUI setting you personally need
- Document a failure mode you hit on Ubuntu in this `docs/` folder
- Add a Tools action that reproduces a bug in one click

PRs that include a short “how I tested on Waydroid” note are much easier to review.
