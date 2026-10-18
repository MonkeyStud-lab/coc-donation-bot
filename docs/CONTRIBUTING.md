# Contributing to CoC Bot

Start with the [architecture](HOW_IT_WORKS.md), [README](../README.md), and
[reliability safeguards](RELIABILITY.md). The current interface is browser-based,
with CasaOS host integration and retained desktop/terminal entry points.

## Project policy

Maintainers do not provide implementation help for detection evasion, paid or
commercial botting, bot-as-a-service, or account farming/selling. Issues/PRs in
those areas are out of scope. Reliability, calibration usability, documentation,
and computer-vision research contributions are welcome.

Live gameplay automation can permanently ban accounts. Practice mode does not
remove that risk or prevent every game action. See the README warning and
[MIT License](../LICENSE).

## Development setup

Install from a checkout, activate `.venv`, then:

```bash
python -m pip install -e '.[web,web-test,web-live]'
python scripts/setup_live_view.py
python -m coc_bot.web
```

For browser work without Android, run:

```bash
PYTHONPATH=src python scripts/preview_web_offline.py
```

Use a disposable profile. `--home` selects a separate prepared root; the browser's
Simulate first launch isolates files but still permits real game input. A fresh
clone does not include private screenshots, models, account data, or calibration.
Do not run unit tests against a production profile or device.

Frontend dependencies/build use the committed pnpm lockfile:

```bash
cd web
corepack pnpm install --frozen-lockfile
corepack pnpm run build
cd ..
```

Commit rebuilt `src/coc_bot/web/static` assets alongside frontend source changes.
Normal users should not need Node.js or a separate Vite server.

## Preserve these contracts

- One operation owns Android. Use `ControlService`, `BotController`, the shared
  capture coordinator, and `DeviceLease`; do not add an independent ADB loop.
- Stop reaches active commands/waits immediately. Pass cancellation through
  subprocesses and check it before input. Do not send cleanup taps after Stop.
- Recognize, act, then verify. Generic screen labels, issued-input logs, or
  learned-model guesses alone must not authorize game input or confirm success.
- Persist required spending/deployment intent before input. Never retry an
  uncertain map tap, ability, or purchase, or silently clear recovery markers.
- Preserve calibration/profile formats and transactional restores. Saving a
  setting is not permission to rewrite calibration or trained artwork.
- Browser writes require normal sessions/origins/CSRF, revisions, payload/file
  boundaries, and server-side ownership checks. Password-free LAN mode does not
  justify exposing arbitrary commands, host paths, ADB, or the Docker socket.
- Keep screenshot/model/account data private. Review screenshots for player/chat
  details before contributing evidence. Never commit credentials or game APKs.

## Where to make changes

### Screens and recovery

Broad screen classes/modes live in `vision/screens.py`. Current Multiplayer/army,
combat, and reward checks are in `vision/battle_menu.py`; result-label checks are
in `battle_completion.py`; auxiliary and inactivity dialogs have dedicated readers.
Annotation labels in `data/labels.yaml` are not automatically runtime ScreenTypes.

Add action-specific evidence to the appropriate navigator/runner. If screens
share colors, prefer flow context and independent anchors to a broader threshold.
A covering dialog invalidates background targets. Add representative positive,
negative, dimmed, and changed-layout regression cases. Keep observer predictions
diagnostic unless a separate action-authority design is explicitly reviewed.

### Donations

`donation/chat_monitor.py` finds and verifies Donate rather than Trade;
`request_parser.py` handles request kind; `navigator.py` owns chat/panel/global-chat
recovery; `executor.py` fills colored slots. `resource_mode.py` guards elixir.

Preserve the visible troop-and-spell first pass before scrolling, supported
low-capacity layouts, fresh panel checks, and selected-elixir verification.
Capacity/budget/inventory modules are optional/experimental, not the default live
fill method. Do not replace resource checks with guessed capacity or slot order.

### Attacks

- `attack/navigator.py`: current menu/army confirmation, battle gate integration,
  results observation, and home/chat navigation.
- `deployer.py`: legacy programmed pixel sequence only.
- `plans.py`, `automatic.py`: validated custom plans and the built-in supported
  Electro Dragon pattern, respectively.
- `army.py`, `battle_gate.py`: current card identity/counts and fresh combat evidence.
- `camera.py`, `survey.py`, `mapping.py`, `projection.py`: gestures, registration,
  deployment-boundary evidence, and map coordinates.
- `executor.py`: selection observations, durable map intents, per-action verification.
- `planned_farmer.py`, `recovery.py`: scheduling integration, camera restoration,
  interruption reconciliation, and completed attack identity.
- `control/attack_planner.py` and `web/src/AttackPlanner.tsx`: supervised editing,
  inventory review, approval, and browser controls.

Only sequence mode requires `farm_deploy_sequence.taps`. Automatic builds a fresh
supported routine; custom planner scheduling requires supervised approval of the
saved routine/device. Never silently fall back from a failed map to old pixel taps.
Ordinary waits keep visual results plus a configured timer fallback; interrupted
recovery has no timer-based leave. See [attack guide](ATTACK_REBUILD.md).

### Upgrades

`upgrades/vision.py` and `digits.py` read the menu/amounts, `policy.py` decides
eligibility without input, and `runner.py` executes/reconciles. Preserve reserve,
slot, name/price/currency, pending-intent, and no-gem/magic-item boundaries.
An upgrade preview must not spend. Pending-category reconciliation must work even
when that category's automation is off, without enabling a new purchase.

### Settings, calibration, and tools

1. Add compatible defaults and load/validation mapping in `config.py` and
   `config/default.yaml`.
2. Add a typed field with description/range/choices in `control/settings_fields.py`.
   Desktop compatibility modules re-export shared definitions.
3. Preserve browser common/Advanced/Dev visibility and settings revision checks.
   Running Save & restart uses `ControlService.apply_settings`, not a competing
   worker restart. Stop must cancel it.
4. Add calibration parts/directions in the shared `calibration/schema.py` and
   `instructions.py`; keep terminal, desktop, and browser paths consistent.
5. Register diagnostics through shared `control/diagnostics.py`. Browser exposure
   needs an explicit allowlisted route/action and proper ownership. Local Tk-only
   editor/shortcut behavior belongs in desktop adapters.

Do not bake private device IPs, account details, game screenshots, or absolute
operator paths into code, examples, or default configuration.

## Verification and PRs

Run the affected focused tests, then required checks in [RELIABILITY](RELIABILITY.md#reproduce-offline-checks).
Do not add tests that merely duplicate implementation or issue real ADB input.
For UI work, check narrow/desktop sizes and rebuild production assets. For host
packaging, test profile preservation and privilege boundaries without modifying
a user's Android installation as an offline fixture.

Recognition changes need inspected positive/negative evidence. Model evaluation
must split by recording session/similarity and report unvalidated classes, not
only aggregate accuracy. Partial object annotations are not exhaustive detector
training labels. See [annotation workflow](ANNOTATION_WORKFLOW.md).

When authorized to test live, back up the profile, exclude competing controllers,
and compare actual outcomes: request capacity, deployed-card counts, visual
results/home/chat, or progress rows after an upgrade. Include Stop/interruption
and failure cases. Restore settings after temporary experiments. A safely aborted
attack is not a complete successful deployment.

PR descriptions should explain the concrete trigger, resulting behavior, relevant
checks, and remaining limits. Do not claim live or clean-host tests that were not
performed. Keep changes focused, update affected docs, preserve historical test
records/plans as dated evidence, and do not force-push main.
