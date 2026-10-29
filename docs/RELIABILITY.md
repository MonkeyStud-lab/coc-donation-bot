# Reliability safeguards and verification

These checks reduce accidental actions; they do not guarantee compatibility with
every game update or remove the account-ban risk in the [README](../README.md).
The [current status](WEB_UI_MIGRATION_STATUS.md) separates verified operation from
remaining installation/hardware acceptance.

## Ownership, Stop, and settings

The shared controller owns one cancelable bot/tool operation. Device leases use
OS file locks and, for CasaOS, the host bridge, preventing a second controller
from using the same selected Android device. Stale lock files alone do not imply
an owner. Different source-install aliases for one physical device are not always
identified; do not configure competing controllers under different serials.

Stop bypasses ordinary work, cancels waits/settling and active ADB subprocesses,
and checks cancellation before further input. Delivered game input cannot be
undone. Ownership remains held until the worker exits. Stopped automation leaves
Clash open and does not send cleanup taps. Desktop Quit waits for workers; browser
tab closure leaves the server/bot running.

Settings Save & restart uses a safe action boundary, not an immediate mid-attack
restart. Stop cancels that pending change/restart. Revision validation prevents
one browser silently overwriting another's draft. Settings and setup load within
one account scope; an account change preserves an unsaved draft but blocks applying
it to the new account. The session clock preserves paused time; an already-started
break uses its real-time end timestamp. Resource demand replaces farm timers.

## Capture and recognition

Captures share a per-device coordinator and latest-frame cache. Normal captures
have a twelve-second total command budget; battle observations have three seconds.
Failed observations do not start unbounded reconnect loops. The normal recovery
path owns reconnect attempts.

A generic screen label, issued tap, or bright button is not proof of an action's
success. Mode/phase narrows recognition; action-specific anchors provide additional
checks. High-level GameState unexpected-transition warnings are diagnostic and do
not themselves block input. Learned model predictions are observation-only.

Several recognizers can share one observation while the interface is unchanged.
Navigation invalidates planned chooser coordinates after input or scrolling;
fresh frames establish the next screen. Identical chooser pixels may reuse name
OCR, but independent player-tag reads, payment receipts and donation resource-mode
checks retain their own verification. A sequence of taps is not evidence that
the intended screens loaded or the action succeeded.

Donate candidates need verified text, not green color alone. Button-label OCR has
a two-second subprocess budget and a bounded crop cache; ambiguous results expire
quickly and do not authorize a donation. Optional capacity OCR is separate.
The default install uses Tesseract/OpenCV; EasyOCR/Torch are optional. Missing
optional models never initiate a download inside the device worker.

Unreadable display-only resource history cannot break status or Stop. Invalid
visit cursors and transaction data remain blocking rather than being skipped.
Fleet chat checks run inside ordinary loop recovery: a failed check remains due,
is logged in the account's verification history, and cannot count as clear chat
or authorize an account switch.

The army picker can dim the My Army header. Its foreground Info controls and
heading must first agree before two brightness-normalized capacity reads are
accepted. A covering inactivity/confirmation dialog cannot authorize army edits
or closing a dimmed X. Cleanup dismisses the verified picker before closing the
editor. Normal account handoffs have their own log message; actual worker failures
write their traceback to the rotating bot log without dumping local variables.

Anti-idle swipes require fresh clan-chat evidence and are suppressed during
pending upgrade/layout operations. Stop cancels the wait between the two swipes.
Generic recovery cannot dismiss an unresolved Home upgrade payment; its receipt
must be reconciled through the upgrade workflow before ordinary navigation.

Before filling, selected-elixir evidence must match. If necessary, a precise
elixir-button tap is followed by a fresh selected-state check. Missing references
or unconfirmed mode skip filling rather than permit gem donations. Visible troop
and spell slots are processed before either grid is scrolled; missing-capacity
panels use the supported alternative layout checks.

## Attacks and camera recovery

Automatic and planner attacks verify the new army confirmation and independent
battle controls before map/deployment operations. Fresh registered views must
support the deployment boundary. Army identities, quantities, and selected cards
are checked before input; map taps require a corresponding count or deployed-card
change. Uncertain map taps/abilities are not replayed. A bounded retry applies
to recognized selection clicks only, not an already deployed unit.

Normal attack waits require Return Home and Troops expended on two fresh frames
before early leave. A configured timer fallback remains for ordinary attacks.
Interrupted-attack recovery uses visual results only, with no timer leave tap.
Home/clan chat and camera restoration must be verified before normal work resumes.

Durable checkpoints and intent journals precede game input. A failure to persist
required intent blocks the input. Restart recovery inspects the live state,
records completion once per attack identity, and never restarts the
army recipe. Corrupt/foreign-device markers are preserved for inspection.

Camera restoration normally requires a measured scale within 3% and bounded
gestures. A verified near-home zoom limit has an automatic-only recovery exception;
it preserves the old reference and blocks legacy fixed-pixel recipes. It does
not relax opponent mapping or authorize deployment. See [attack recovery](ATTACK_REBUILD.md#interrupted-attacks-and-diagnostic-storage).

## Upgrade spending

Only supported Suggested entries may qualify. Builder/laboratory availability,
resource balances, remaining reserves, name, price, and currency must pass fresh
checks. Two confirmation observations precede the resource press. No gem/magic-item
or missing-resource purchase is authorized.

Intent is saved before spending. A matching progress row and reduced free slots
confirm success. An uncertain result or restart leaves a pending journal and
blocks another purchase until reconciled. Reconciliation can inspect the pending
category even when its automation is off; it does not enable or repeat spending.
See [upgrade safeguards](UPGRADES.md).

## Calibration and profile protection

Stop and release manual control before calibration or restore. Browser capture
IDs bind original images/dimensions to a revision. Saves reject stale captures,
out-of-bounds selections, and conflicting revisions. Skip/Cancel retains existing
calibration. Required fields and dimensions can be checked in Diagnostics, but
matching dimensions alone do not prove a matching game layout.

Restores stage YAML and template images together. Failure rolls both back; a
journal lets a later config load recover an interrupted restore. Config reads,
restores, and installer backups share locks. A failed safety backup aborts restore.
These mechanisms protect interrupted processes, not every disk/hardware failure.

Library archives contain calibration/templates. Full profile backups must also
cover settings, planner artwork/routines, and pending attack/upgrade state;
Android account data needs separate protection. See [backup scope](RUNNING.md#backups-and-migration).

## Storage and private data

- Verification failures appear as warnings and persist per account in
  `data/verification/failures.json` (100 distinct records, repeated observations
  deduplicated). An unresolved Builder receipt pauses that account's Builder Base
  work after a verified safe Home return; it is never treated as a successful
  purchase. An unsettled payment/placement/battle still blocks navigation.
- Application logs rotate at 10 MB with seven-day retention.
- Generated attack survey/execution evidence is pruned between operations, with
  seven-day, 1 GiB, and forty-group targets. The newest three groups per family
  remain protected, so limits can be exceeded. Pending attack/camera recovery
  suspends cleanup. Unknown paths, links, calibration, backups, saved routines,
  reviewed observations, and labeled datasets are excluded.
- Smart collection has separate configurable daily/storage limits. It pauses at
  capacity rather than deleting reviewed data; legacy `--record` storage is
  separate and is not covered by those limits.
- Screenshots, models, calibration, APKs, and account data are private profile
  files, not automatic GitHub uploads. Review report exports before sharing.

## Reproduce offline checks

From an installed source environment:

```bash
python -m pip install -e '.[web,web-test]'
python -m unittest discover -s tests -v
python scripts/verify_farm_offline.py
python scripts/verify_smart_collection.py
python scripts/verify_battle_completion.py
python scripts/verify_auxiliary_screens.py
python scripts/verify_screen_model.py
xvfb-run -a python scripts/verify_gui_offline.py
```

Tesseract with English language data is needed for relevant OCR fixtures; Tk/Xvfb
is needed for headless desktop checks. Python 3.12 and 3.14 are the CI targets.
Use disposable data and fake ADB; tests must not control the live game. Rebuild
the frontend after source changes using the pnpm lockfile, as in [browser development](WEB_UI.md#development-and-verification).

The tests cover capture/Stop/ownership, revisions and restore failures, OCR/resource
checks, paused clocks, mapping/selection, no duplicate map input, spending intent,
crash recovery, and diagnostic retention. Offline success cannot establish new
scenery, language, fresh-host, or hardware compatibility. Live checks must compare
requested actions with visible game outcomes and retain evidence of both success
and conservative aborts.

`constraints/linux-py314.txt` records tested direct versions for optional
`bash scripts/setup_linux.sh --tested-deps --web`. Other Python versions should
use normal setup. Do not interpret a historical test count as the size/result of
a newly run suite.
