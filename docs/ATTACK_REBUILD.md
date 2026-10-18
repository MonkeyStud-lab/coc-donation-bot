# Attack planner and verified executor

The experimental planner runs a configurable mass Electro Dragon routine in
unranked battles. It does not choose strategies, score opponents, prioritize
elixir, or replace an existing deployment sequence automatically.

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
rejects unknown cards, inconsistent counts, extra troop types, unsupported spells
(including Recall), multiple siege cards, and incomplete opponent maps. Skipped
matches are allowed to finish, followed by home/camera/chat recovery; they advance
the farm interval so an unsupported army is not retried repeatedly.

Normal game connection and Farm navigation calibration are still needed. Artwork
recognition uses the installed icon pack and any existing reviewed card references,
but never needs `routine.json`. Unfamiliar hero skins may be unreadable and cause a
skip. This is a supported-army automatic mode, not universal army recognition.
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
sends no cleanup inputs afterward. If stopped in a battle, finish or wait for that
battle manually, return home, then choose **Restore camera** before using the old
sequence. The persisted camera marker blocks both regular bot startup and legacy
farming until restoration has been measured successfully, including after an app
restart.

A first review may take longer than a match. Keep the saved routine and reviewed
artwork, then prepare a fresh opponent. An expired screenshot cannot authorize a
new attack. Maps are opponent-specific; the saved routine contains normalized
positions, not a previously visited opponent's map or army-bar coordinates.

## Camera and opponent mapping

The two-finger gesture uses the pinned scrcpy 3.3.3 server already used by Live
view. It needs neither Android root nor another Waydroid window. Every gesture
releases its fingers and removes only its own ADB forwarding rule.

The survey takes at most three pinches and twelve short pans. It normally finishes
within eight pans; an incomplete fit gets an extended pass toward the top edge.
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
survey and restores the measured scale afterward. A measured zoom-change hint
can guide one correction when the original view is too different to match, but
only a subsequent home-image comparison can clear the pending marker. Device or
resolution changes, missing references, or failed comparisons leave it blocked.
Restoration tolerates a measured scale difference below three percent; it does
not rewrite calibration coordinates.

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
card without treating those chips as the card itself. Hero identity includes
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
- `attack/planned_farmer.py`: opt-in scheduled engine and camera restoration.
- `control/attack_planner.py`: supervised previews, private templates, and lifecycle.
- `web/src/AttackPlanner.tsx`: map editor and numbered steps.

Plans and reviewed card references live in `data/attack-planner/`. Observations,
survey views, execution journals, and diagnostic frames live under `data/debug/`.
These account-specific files are ignored by Git. Saved plans are separate from
`calibrated.yaml` and the legacy deployment sequence. The web API uses the normal
session/origin checks, revision checks, allowlisted images, exclusive device
lease, and Stop mechanism. No route accepts an arbitrary local image path.

## Validation and release limits

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

Offline tests cover plan quantities/order, geometry, stale cameras, uncertain
selection/deployment, no duplicate taps, Stop, camera recovery, web ownership,
timed battle overlays, missing card outlines, settings restarts, and legacy navigation. Run the relevant suite plus the web
build before deployment:

```bash
python -m unittest discover -s tests -p 'test_attack*.py'
python -m unittest discover -s tests -p 'test_updated_battle_menu.py'
python -m unittest discover -s tests -p 'test_web_interface.py'
cd web
npm run build
```

Scenery coverage, small display sizes, unknown skins, crowded/scrolled bars,
network delays, and the observable effects of hero abilities remain validation
limits. A single successful routine does not establish universal support.
