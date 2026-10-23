# Attack planner and verified executor

The browser's Attacks page offers automatic mass Electro Dragon farming and
custom map-based routines for unranked battles. These use measured opponent
maps and per-deployment verification. The original programmed pixel sequence
remains available; the app does not invent strategies or score opponents.

The original **Programmed tap sequence** remains the default. **Automatic** and
**Planner** are opt-in attack methods. Scheduling a saved routine requires a successful supervised
attack with that exact routine on the same device. Editing it removes that approval.

## Automatic attacks without a saved routine

Stop the bot and release Live view control, then choose **Attacks → Automatic
attack**. This starts a real unranked attack immediately. No drawn points, saved
routine, army review, or supervised-run approval are required. For scheduled use,
select **automatic** under **Settings → Attack method**, enable scheduled farming,
and start the bot. **Farm now** also uses that setting. The Automatic attack button
does not change your saved settings or overwrite a custom routine.

The built-in pattern deploys Electro Dragons along one mapped edge, spreads Rage
spells inside that edge, then deploys the siege machine and heroes. Each hero's
ability follows its own verified deployment. Quantities come from the current army. Before deployment, the bot reads
two matching frames on each army-bar page and checks both scroll endpoints. It
requires verified Electro Dragons and consistent counts for every used card.
Extra troop types, unrecognized cards and unsupported spells (including Recall)
are left unused rather than cancelling the dragon attack. They never authorize
selection or serve as army-scroll anchors. Multiple supported siege cards and
incomplete opponent maps still block deployment. Skipped
matches are allowed to finish, followed by home/camera/chat recovery; they advance
the farm interval so an unsupported army is not retried repeatedly.

Normal game connection and Farm navigation calibration are still needed. Artwork
recognition uses the installed icon pack and any existing reviewed card references,
but never needs `routine.json`. Unfamiliar hero skins may be unreadable and cause a
skip if an identified card cannot be read consistently. Unrecognized skins are
left unused. This is a supported-army automatic mode, not universal army recognition.
The executor still verifies individual deployments and never repeats an uncertain
tap. Stop interrupts immediately and leaves any required camera recovery pending.

## Use the planner

1. Stop the regular bot and release Live view control. Open **Attacks**.
2. Choose **Prepare opponent**. The app opens unranked Battle, passes the My Army
   confirmation, positively checks the opponent screen, zooms out, and surveys
   overlapping views. This enters a real match: the game's timer keeps running
   while you review the plan.
3. Expand **Review army**. Compare each pictured card with its name, type, and
   quantity. Correct unknown names using lowercase identifiers such as
   `electro_dragon`; check each card you intend to use, then **Save review**.
   A consistent machine reading is separate from your confirmation.
4. Check the blue village outline. If automatic mapping is incomplete, use
   **Mark village corners**, clicking top, right, bottom, then left on the map.
   Use the red village perimeter, not the decorative scenery border. Do not
   guess a corner that the surveyed picture does not show.
5. Choose **Create Electro Dragon routine**, or **Load saved routine** to reuse
   your own steps on this opponent. The generated routine spreads all confirmed dragons
   along one side, places explicitly identified Rage spells immediately afterward,
   then deploys the siege machine and heroes and sends their ability taps. A Recall
   spell is never substituted for Rage. Other spells require explicit steps.
6. Edit the numbered steps. Choose the unit, quantity, action, and map positions.
   A line takes two clicks; spells take one target per spell. Waits use seconds.
   Reorder or remove steps as needed. Troop targets belong outside the red
   perimeter; spell targets belong inside it.
7. **Validate preview**, then **Save routine** to retain it separately from your
   old calibration. **Run this attack** performs one supervised attempt. A used
   preview cannot be replayed, even if it failed partway through.
8. After a successful complete test, select **Planner** under Attack method in
   Settings if you want scheduled attacks to use it. An incomplete automatic map
   stops deployment; the bot never silently substitutes the old pixel sequence.

**Stop** interrupts mapping, card selection, deployment, waits, and recovery. It
sends no cleanup inputs afterward and retains unfinished attack/camera state.
On the next Start, recovery inspects that state before normal operation; it does
not replay the plan. You can also finish/wait for the battle manually and return
home before starting recovery. **Attacks → Restore camera** is the explicit idle
tool for restoring the saved reference, including a preserved legacy reference.
Unresolved recovery blocks ordinary automation; an automatic-only zoom-limit
exception can still leave the old pixel sequence blocked. See
[interruption recovery](#interrupted-attacks-and-diagnostic-storage).

A first review may take longer than a match. Keep the saved routine and reviewed
artwork, then prepare a fresh opponent. An expired screenshot cannot authorize a
new attack. Maps are opponent-specific; the saved routine contains normalized
positions, not a previously visited opponent's map or army-bar coordinates.

## Camera and opponent mapping

The two-finger gesture uses the pinned scrcpy 3.3.3 server already used by Live
view. It needs neither Android root nor another Waydroid window. Every gesture
releases its fingers and removes only its own ADB forwarding rule.

The survey takes at most three pinches and twelve short pans. It normally finishes
within eight pans. When all four candidate sides exist but coverage is insufficient,
the final four pans bring their largest unobserved sections into view. These
camera hints cannot authorize deployment; the same coverage thresholds must pass
on fresh observations. Without usable four-side evidence, the bounded exploratory
pass remains available.
An already visible, stationary deployment outline is kept selected. Otherwise,
the survey permits at most two freshly located army-card clicks and rechecks
the outline, rather than assuming a click worked or toggling an existing outline
off. No map/deployment taps are sent by the survey.
Each view must have
positive battle controls, a settled camera, and measured registration to the
reference image or an overlapping registered view. Red boundary fragments are
combined only after registration. Four separately supported sides, a balanced
convex diamond, and sufficient observed coverage are required for an automatic
projection. A panorama helps review areas hidden beneath the interface.

The projection maps normalized battlefield positions to pixels. Its inner square
`[0.1, 0.9]` represents the village perimeter. Troop targets use the outside ring;
spell targets use the inside. The executor avoids the army bar, loot labels,
resource controls, and battle buttons. It measures camera movement again before
using coordinates, including after a pan or unit selection.

A successful pinch does not prove maximum zoom. Red fragments and a fitted
outline do not guarantee every deployment location is legal on every scenery.
One short observed side can be accepted when the other three have strong combined
coverage and the complete diamond passes the geometric checks. Missing sides or
two short sides remain blocked.
Unsupported scenery can still stop an attack. Count changes provide the separate
confirmation that a particular deployment actually happened.

Home retains the battle zoom. The app saves its original home image before a
survey and restores the measured scale afterward. Restoration measures the
actual home image; an opponent's starting zoom is not a home zoom reference.
If no reliable match is available, one wider home overview can expose landmarks
for a fresh measurement. Normal restoration requires a verified home-image
comparison; the automatic-only measured zoom-limit exception is described under
interruption recovery. Device or
resolution changes, missing references, or failed comparisons leave it blocked.
Restoration tolerates a measured scale difference below three percent; it does
not rewrite calibration coordinates.
If the restored view lands on sparse repeated decorations, a plausible existing
translation can guide up to two bounded pans at home. Each pan requires a fresh
image; a subsequent verified comparison is required for normal restoration.
These probes never authorize battle coordinates or bypass camera verification.
Home-only matching includes edge landmarks while explicitly masking fixed HUD
controls. A small source image pyramid handles large zoom differences without
loosening reciprocal-match or distributed-inlier requirements.

## Army and execution

Army detection combines the unit icon pack with private artwork references from
reviewed cards. Names are not guessed from slot order, hero levels, or skins.
If scenery merges with a card's border, matching the reviewed portrait's
landmarks can locate the card afresh. That crop still has to pass identity and
quantity checks; it does not authorize tapping an old slot.
Top `xN` badges provide troop/spell quantities. Digits are segmented before OCR,
including special handling for the game's narrow `1` and block-shaped `0`.
Bottom level numbers are not quantities. Scrolled cards are located with a
bounded search inside the army bar; positions are reread on each use.

Before the first deployment, all used units must match the reviewed inventory.
Selection needs the bright card outline, allowing equipment chips above the
card without treating those chips as the card itself. A selection click gets
two fresh observations while the card settles. If it missed, one additional
card click can use the newly recognized position. Already deployed heroes/siege
machines cannot be reclicked through this retry path, and Stop cancels further
attempts. Selection intent and confirmation are recorded in the execution journal.
Hero identity includes
unchanged crown/face landmarks because deployment can replace the lower portrait
with an ability graphic. Each map tap is journaled before being
sent and then checked against a fresh image: a decreased count, a depleted siege
card, or a deployed hero/siege machine's health bar. Thin cyan selection highlights
and green scenery touching a card's border do not qualify as health bars. Active cards rise above the
army row, so their current bounds are detected again. One extra observation is
allowed during that animation, without repeating the map tap. If the change is uncertain, remaining
steps stop. The executor never repeats an uncertain map tap or whole sequence.
Hero abilities are sent once, only after verified hero deployment; an ability
log records that the tap was sent, not proof of its gameplay effect.
The ability check accepts enclosed red and yellow health bars on already deployed
heroes as well as green ones. Initial deployment still needs the stricter evidence;
wounded heroes cannot be mistaken for fresh deployments.
If a freshly identified, previously deployed hero has no usable health bar, its
ability is logged as skipped and the remaining heroes continue. Uncertain identity
or changed battle/camera evidence still stops the executor.

After battle has been established, a troop tooltip may cover Surrender. In that
case, both the battle timer heading and Overall Damage label must be readable.
Their verified lettering can be reused while it remains bright and unchanged.
A small set of observed outlined-font errors, such as `Surreender` and
`Qverall Damage`, is accepted without removing either independent control check.
A dimmed reward overlay does not qualify. The executor waits briefly for clear
controls, then stops remaining deployment if they do not return.

Results use the existing conservative result detector and timer fallback. The
fallback starts with the first verified deployment, or the first attempted tap
when its result is uncertain. A no-deployment cleanup includes the scouting
period. Home is confirmed through clan chat, the old camera is restored, and
only then can normal operation resume. An unsuccessful mapping/execution does
not count as a successful supervised routine.

## Files and integration

- `attack/plans.py`: versioned plan validation and the mass Electro Dragon routine.
- `attack/camera.py`, `adb/multitouch.py`: gesture transport and image measurements.
- `attack/mapping.py`, `survey.py`, `projection.py`: boundary evidence and map coordinates.
- `attack/army.py`, `battle_gate.py`: fresh army and battle-control evidence.
- `attack/automatic.py`: current inventory scan and built-in Electro Dragon plan.
- `attack/executor.py`: measured execution and per-action journal.
- `attack/planned_farmer.py`: automatic/planner scheduling and camera restoration.
- `attack/recovery.py`: durable attack checkpoints and interruption reconciliation.
- `control/attack_planner.py`: supervised previews, private templates, and lifecycle.
- `web/src/AttackPlanner.tsx`: map editor and numbered steps.

Plans and reviewed card references live in `data/attack-planner/`. Observations,
survey views, execution journals, and diagnostic frames live under `data/debug/`.
These account-specific files are ignored by Git. Saved plans are separate from
`calibrated.yaml` and the legacy deployment sequence. The web API uses the normal
session/origin checks, revision checks, allowlisted images, exclusive device
lease, and Stop mechanism. No route accepts an arbitrary local image path.

## Validation history and release limits

The dated results below record particular source snapshots and inspected armies.
They are not a test run performed by updating this document. The latest overall
deployment status is maintained in [current status](WEB_UI_MIGRATION_STATUS.md).

Live testing uses an isolated source snapshot and a verified calibration backup.
It has exercised real pinch gestures, multiple sceneries, reviewed army artwork,
measured projections, and deployment count checks. Tests exposed false battle
OCR, camera settling/overlap problems, and `x10` being read as `x16`; these have
specific fixes. Experimental code is not automatically deployed to production.

The October 17, 2026 live acceptance run verified 21 deployments: eleven Electro
Dragons, five Rage spells, one siege machine, and four heroes. All four hero
ability taps were sent. The run then returned home, restored the original camera
scale, and confirmed clan chat. The saved routine passed its supervised-run
requirement. All nineteen protected calibration files matched their pre-test
hashes. The targeted Linux regression suite passed 173 tests, and the TypeScript
and production web build passed. This is evidence for the tested army and device,
not a guarantee for every scenery or hero skin.

The subsequent Automatic-mode test generated its own eleven-step plan from seven
current army cards, without loading or approving the saved routine. It verified
the same 21 deployments and sent all four ability taps. Earlier attempts exposed
two cases now covered by regressions: a wounded hero's red/yellow health bar, and
an unavailable ability preventing other heroes from continuing. Automatic mode
now sends each hero's ability immediately after its verified deployment. The
expanded Linux suite passes 190 tests; the TypeScript and production web build
also pass. The final automatic run returned home, restored the original camera,
and reopened clan chat. All twenty protected calibration/routine files matched
their pre-test hashes. The original production bot was resumed with its existing
attack method; enabling Automatic remains an explicit settings choice.

The October 18 live monitoring enabled Automatic in production. A complete
19-deployment run verified eleven Electro Dragons, five spells, one siege and
two available heroes, with both hero ability taps sent. Subsequent tests fixed
results-label and home-camera recognition failures. The final battle-end check
recognized results before the fallback, restored home zoom and reopened clan
chat. All 34 protected calibration/template/routine files retained their hashes;
the expanded Linux regression suite passed 197 tests.

Monitoring also found conservative stops on maps without four verified edges
and one hero selection that could not be confirmed. That final deployment run
stopped after 17 verified placements, so it was not recorded as a fully successful
army execution even though battle-end cleanup passed. These guards remain in
place; ambiguous maps or card selection must not trigger blind map taps.

The follow-up refinement keeps those approval thresholds intact. On 30 saved
surveys, all 18 accepted and 12 rejected fits retained their decisions; six
rejected fits supplied camera hints for further observation. Bounded selection
retries, delayed card observations, outline preservation and targeted final pans
pass the expanded 206-test Linux regression suite.

With the game's decoration-hiding option enabled, the live acceptance run mapped
an opponent using two views and one pan, verified all 19 deployments and sent both
available hero ability taps. It recognized battle results visually, restored the
home camera and reopened clan chat. All 34 protected calibration/template/routine
files and application settings were unchanged. Hiding decorations reduces visual
clutter, but this was not a controlled comparison of the same base with the
option off; it does not replace boundary or selection verification.

Offline tests cover plan quantities/order, geometry, stale cameras, uncertain
selection/deployment, no duplicate taps, Stop, camera recovery, web ownership,
timed battle overlays, missing card outlines, settings restarts, and legacy navigation. Run the relevant suite plus the web
build before deployment:

```bash
python -m unittest discover -s tests -p 'test_attack*.py'
python -m unittest discover -s tests -p 'test_updated_battle_menu.py'
python -m unittest discover -s tests -p 'test_web_interface.py'
cd web
corepack pnpm install --frozen-lockfile
corepack pnpm run build
cd ..
```

Scenery coverage, small display sizes, unknown skins, crowded/scrolled bars,
network delays, and the observable effects of hero abilities remain validation
limits. A single successful routine does not establish universal support.

## Interrupted attacks and diagnostic storage

Before opening an attack, the controller writes
`data/attack-planner/attack-pending.json`. It records the device, attack ID,
navigation phase and whether a deployment might have happened. Every map input
is preceded by an atomic, fsynced checkpoint and a durable intent journal entry.
Checkpoint write failures block the input. Stop leaves unfinished checkpoints
intact; it never sends cleanup taps after cancellation.

On Start, after an unexpected error, or before another farm operation, the device
owner checks this marker and the existing camera recovery marker. Recovery:

- Never replays army selection, deployment, hero abilities or upgrade actions.
- Waits through a verified live battle. Two fresh results observations authorize
  Return Home; recovery has no timer-based Return Home tap.
- Cancels a positively recognized army confirmation or Multiplayer page using
  Back. Generic screen labels do not authorize Back.
- Requires the home Build control or clan-chat anchor, restores the original
  camera when needed, then verifies clan chat on a fresh screenshot.
  Camera restoration keeps the five-gesture limit and 3% verified zoom tolerance.
  If repeated measurements show a tiny correction was ignored, it can use one
  larger home-only gesture, then remeasure before correcting back. The final
  permitted gesture also receives a fresh verification without another input.
  In automatic mode only, a nearby home zoom endpoint can be accepted after a
  strong zoom-out produces no measured zoom change (within 0.5%), with the
  original home scale still within 7% and clan chat subsequently verified. The
  old reference is preserved as `camera-legacy-before.png` and
  `camera-legacy-blocked.json` prevents running fixed pixel sequences. Automatic
  attacks must still rebuild and verify their opponent map from fresh images.
  Attacks → Restore camera can attempt the preserved legacy reference. The regular
  3% camera-restoration tolerance and opponent geometry thresholds are unchanged.
- Advances the farm interval once for a potentially fought battle. Its attack ID
  is persisted so a crash between saving the interval and clearing the checkpoint
  does not roll a second interval.
- Stops after three unknown-screen/cancel attempts, three results taps, or four
  minutes waiting. If blocked, open the home village manually and press Start.
  A corrupt/foreign-device checkpoint is preserved and needs inspection; it is
  never silently discarded. `last-attack.json` retains the last completed record.

This recovers work when the controller starts again; it does not automatically
restart a stopped bot process. Existing Docker restart policy remains unchanged.
Malformed camera references and unknown menus can still require manual help.

Generated diagnostic evidence under `data/debug/attack-surveys`,
`attack-executions` and `attack-v2` is cleaned between operations: older than seven
days, above 1 GiB combined, or above 40 evidence groups. The newest three groups
in each category are protected, making the limits soft if those alone exceed the
budget. Entire survey/execution groups are removed together. Any pending attack
or camera recovery suspends cleanup. Calibration, backups, learned portraits,
saved routines, reviewed observations, labeled datasets and screenshot collection
are excluded. Collection keeps its separate configured storage policy.

Tests in `test_attack_recovery.py` exercise abrupt process exit, failed atomic
writes, battle/results/home recovery, duplicate interval saves and Stop.
`test_screenshot_retention.py` covers age/size/count limits, pending guards,
protected data, dry runs and links. No calibration is erased to simulate a crash.

Validation on 2026-10-18: 235 Linux regression tests passed. A live controller
was killed after 11 verified Electro Dragon deployments. Its journal received no
further deployment inputs during recovery; results authorized one Return Home
tap, home/clan chat were subsequently confirmed, and the interval was recorded
under that same attack ID. The test exposed a nearby home zoom endpoint; the
automatic-only endpoint handling preserved the old reference and blocked legacy
pixel recipes. The final deployment resumed normal requests with both pending
markers cleared. All 34 protected calibration/template/routine files and saved
application settings remained unchanged. Retention removed about 1.08 GiB of
generated evidence across the test; labeled collection data was excluded.
