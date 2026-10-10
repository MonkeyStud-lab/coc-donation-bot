# Contributing / extending the bot

This guide is for developers who want to change or build on the project. Read [HOW_IT_WORKS.md](HOW_IT_WORKS.md) first for the architecture.

---

## Out of scope — we will not help with

Issues, PRs, and discussions in these areas will be closed without implementation help:

- **Detection evasion** — hiding, randomizing, or otherwise trying to avoid Supercell’s bot / fair-play enforcement
- **Paid or commercial botting** — selling access, running bot-as-a-service, or scaling farms for profit
- **Account farming / selling** — bulk accounts, trophy or resource farms for trade, or similar

Welcome contributions improve reliability, calibration UX, docs, and learning value for people running their **own** Waydroid setup. Using this software on live Clash of Clans can get accounts **permanently banned**; that risk is yours. See the README warning and [LICENSE](../LICENSE).

---

## Setup for development

```bash
cd ~/Projects/coc-donation-bot   # or your clone
source .venv/bin/activate        # after ./scripts/setup_linux.sh
python -m pip install -e .
```

Run without GUI for quick terminal tests:

```bash
python -m coc_bot.main --no-gui --dry-run
```

This still sends live navigation input. Practice / dry-run skips donation taps;
use the offline checks below when no game interaction is wanted.

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
4. Update navigators that branch on that screen (`donation/navigator.py`, `attack/navigator.py`, `bot.py` recovery).
5. Optionally add a calibration step / template key in [`calibration/wizard.py`](../src/coc_bot/calibration/wizard.py).

**Rule of thumb:** if two screens look alike, disambiguate with **BotMode** or **flow phase** (what the bot was doing), not only with stricter colors.

### 2. Change farm combat (deploy recipe)

| Goal | File |
|------|------|
| Order of actions / success criteria | `attack/farmer.py` |
| Matchmaking, results, Return Home | `attack/navigator.py` |
| Pan + replay programmed deploy sequence | `attack/deployer.py` |
| Programmable tap editor | `calibration/sequence_picker.py` + Diagnostics actions in `gui/debug_actions.py` |
| Tunables | `config/default.yaml` → `farm:` + `BotConfig` in `config.py` + GUI field in `gui/settings_fields.py` |
| New tap targets | Wizard step `"farm"` |

Farm deploy requires `farm_deploy_sequence.taps` (no built-in recipe).
Keep both completion paths in `wait_for_battle_end`: two consecutive observations
must verify the Return Home and Troops expended labels before an early leave;
otherwise the deadline force-taps calibrated `return_home` coordinates. Generic
screen classifications must not end a battle early. After a leave tap, confirmation
looks for home village / clan chat rather than reusing results/battle heuristics.
See [BATTLE_COMPLETION.md](BATTLE_COMPLETION.md) for the exact checks and limitations.

### 3. Change donation behavior

| Goal | File |
|------|------|
| When a request is eligible | `DonationBot._should_handle_request` in `bot.py` |
| Specific vs open vs hybrid | `donation/request_parser.py` |
| How slots are filled | `donation/executor.py` |
| Finding Donate in chat | `donation/chat_monitor.py` |
| Chat open/close / panels | `donation/navigator.py` |

There is experimental budget-aware code (`fill_planner.py`, `inventory.py`, `icon_matcher.py`). The **live** path today is colored-slot filling. Wire planner carefully if you revive it.

Preserve selected-elixir verification in `donation/resource_mode.py`. Missing or
ambiguous evidence must refuse donations; do not bypass it to improve speed.
Green chat buttons also need verified Donate text, not just a color match.

### 4. Add a Settings UI field

1. Add a default in `config/default.yaml` (and `BotConfig` + `load_config` mapping).
2. Append a `SettingField` in [`src/coc_bot/gui/settings_fields.py`](../src/coc_bot/gui/settings_fields.py) with the correct `yaml_path`.
3. Save from the GUI writes `data/user_settings.yaml`. Running bot loops usually need Stop → Start to pick up timing/farm changes; GUI-only filters (e.g. activity DEBUG) may apply immediately.

### 5. Add a Diagnostics (debug) action

Register in `DEBUG_ACTIONS` and wire the action through `run_debug_action` in [`src/coc_bot/gui/debug_actions.py`](../src/coc_bot/gui/debug_actions.py), using `DebugSession` where appropriate.

### 6. Cooperative Stop

Any new long wait must honor `stop_check` / `interrupted_sleep` so the GUI **Stop** button stays responsive (including farm one-shot).

Pass cancellation through ADB commands and check Stop before sending input. Use
the shared capture coordinator instead of starting a competing capture loop.
Preserve device leases, capture budgets and transactional calibration restores.
Learned screen predictions and collection hints are diagnostic evidence, not
authorization to send input.

---

## Testing

Start with the offline regression checks in [RELIABILITY.md](RELIABILITY.md).
They run without a game connection, and GitHub runs the same core suite. Add
focused regression coverage for behavioral fixes. For recognition/model work,
also use the checks in [PERCEPTION.md](PERCEPTION.md).

Then verify the affected flow on Waydroid; offline tests cannot establish that
a new game layout works:

1. **Donation:** open request + specific request; panel opens and closes cleanly.
2. **Farm:** Attack → Battle → deploy → confirmed results or timer fallback → Return Home → clan chat opens.
3. **False leave:** mid-fight green scenery should not eject you (End Battle still visible).
4. **Stop:** during matchmaking wait and during donation scroll.
5. **Break (optional):** shorten `session_limit_seconds` in settings for a dry test, then restore.

Record the checks actually performed and any live verification still needed.
Review screenshots for player names, chat and other private content before
sharing. Local datasets and trained models are not part of a normal checkout.

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
- Add a Diagnostics action that reproduces a bug in one click

PRs that include a short “how I tested on Waydroid” note are much easier to review.
