# Automatic Home Village layouts

**Automatic defensive layouts** is an account-specific toggle in Settings → Upgrades
and is **off by default**, including for newly added accounts. Turn it on only for
accounts that should change layouts automatically. Turning it off leaves active
layouts and saved drafts intact; an unfinished edit or payment still needs safe
recovery before normal operation can resume.

Supervised layout work can run separately while this toggle remains off. It must
hold the device lease with the normal bot stopped, retain the same payment and
activation checks, and must not enable the account's saved setting.

To enable automatic changes, turn on **Automatic defensive layouts** for each account.
Enable **Replace inactive layouts** if no empty spare slot is available. Enable
**Clear ordinary obstacles**, and optionally **Remove seasonal obstacles**.
Gold/elixir reserves apply to removal payments. Obstacle removal does not need
a free builder; the reserved-builder setting applies to building upgrades.

The runner first clears all permitted obstacles inside the registered build zone.
It edits an inactive native layout and uses **Remove All** to expose obstacles;
no layout copy is imported during this stage. Each removal uses gold/elixir and
needs its own verified receipt. The original active village and saved draft stay protected.

After every survey view is complete, it tests Town Hall-specific defensive copy
links against the account's actual owned buildings. The game's enabled Save
control proves a complete inventory fit, including merged/unmerged defenses.
An incomplete copy is inspected before any manual placement: all catalog
candidates are tried before a small fallback is selected. A fallback permits at
most six confirmed placements across all visits. Two stable inventory observations
plus a swipe check can prove a fully visible small remainder. If a small known
prefix is followed by unreadable cards (such as decorations), only a bounded
inactive trial is allowed: unknown cards are never placed, and native Save must
prove completion before activation. Six placements without completion reject
that reference. Larger known differences need another compatible reference;
they no longer trigger prolonged mass placement.
This is native compatibility testing, not a guess about merge state from Town
Hall level or a website caption. It never merges defenses to fit a layout.

Saved-draft fingerprints exclude the native status badges at the bottom of
the thumbnail. A new obstacle warning on reopening a draft invalidates its
previous clearance and returns it to clearing, while preserving the saved copy.

Work resumes in bounded visits; first-time/Hall-change layouts get a turn before
scheduled farming, while visible donation requests and unresolved payments keep
their priority. Already Home-verified active layouts survive the policy upgrade;
unfinished old drafts are retained but undergo the new clearance/matching flow.

## Supported native workflow

The catalog in `src/coc_bot/layouts/catalog.json` contains multiple researched
defensive copy links for every TH4–18, with source pages and check dates. Imports require the
saved account’s verified Town Hall and an independently recognized inactive
native slot. Reference links can expire or become incompatible after game
updates; those cases stop without replacing the active village.

TH2/3 are skipped because this implementation requires the native layout
editor and copy workflow. It does not rearrange starter bases through ordinary
Home-screen drags. An unavailable editor or spare slot leaves the base unchanged.
Builder Base has different geometry and is not handled by this layout runner.

The current game opens **Layout Editor** through the hand button in the Build
menu. The bot uses the native **Home Village** tab, chooses an inactive slot,
finishes inventory placement, saves, and explicitly selects **Set as active**.
A **Finish later** draft is never reported as applied.
If clan chat remains open over an imported editor, its close arrow is used only
after two native editor controls independently verify the screen. Ordinary Home
chat is not closed by this editor recovery rule.

Activation then needs an independent Home check. Terrain registration aligns
the active card's preview and two fresh Home screenshots despite camera/zoom
differences. Their structure/edge maps must agree; an active badge alone is not
success. Unverified application remains in a resumable verification stage.
Clearly different settled villages are reimported, and verified arrangements are
checked again during periodic layout visits. Ranked defensive snapshots are a separate game feature;
this workflow changes the visible Home Village, not the current Ranked tournament.

Each account retains its own verified Town Hall, layout progress and cooldown.
Two matching current-level observations from the building list refresh the
Town Hall during progression and army preparation. Starting a Town Hall upgrade
does not advance that level. Once completion is observed, the old layout cooldown
no longer applies: the next eligible layout visit selects the new Hall's catalog
entry and resumes clearing/importing in an inactive slot. A stale account-chooser
level cannot downgrade a more recent verified level. Unsupported levels are
checked at most hourly until their verified Town Hall changes. Missing buildings
retain empty reference footprints, and a previous active layout is preserved
until the new one is complete and activation is verified.

The default Home Village terrain is currently the registration reference.
Unknown sceneries or uncertain camera geometry stop the operation. The system
does not promise universal scenery support or competitive defensive results.

## Clearing

1. Verify the loaded account and back up its settings, calibration and journals.
2. Verify the Home-only builder icon and read gold, elixir and gems on two
   fresh frames. Builder-count OCR is not required for obstacle removal.
3. Open an inactive native slot without importing a copy, use **Remove All**, and verify the exact
   **Collect All — collect all buildings** confirmation. This stashes buildings
   in the temporary editor; it does not demolish them.
4. Register permanent terrain on stationary frames. Survey overlapping views
   of the full 44×44 build area, excluding controls and the outer decorative border.
   Both an obstacle’s body and lower anchor must fall inside the conservative
   build-zone polygon. Contrast edges supplement color so bright foliage is
   not mistaken for grass; the legal first and last tile rows remain included.
   Low-saturation stone facets have a separate mask. A recognized selected border
   tree is excluded only when its actual trunk anchor projects outside the zone
   with a full tile of tolerance; a nearby grass tap is not its location proof. The final pan must produce
   a new stationary screenshot and registration before any candidate is tapped.
5. Select one obstacle. Read its native **Remove** command, positive gold/elixir
   price and floating name on fresh frames. Seasonal objects require the
   separate permission. Green gem prices, shovels and storage actions are rejected.
   Before each candidate, the native **Drag buildings from the inventory**
   instruction must verify on two fresh frames. An existing selection is first
   cleared through the blank left margin, outside payment controls. The camera
   is reacquired before projecting the next target. This permits surveying the
   lower canvas safely, including trees that cannot pan above the old tap area.
   If idle selection cannot be proved, no candidate tap is sent. The exact
   Remove label locates its own price tile, including horizontally shifted actions.
   The full five-digit price fits in that tile's read, including 20,000-gold
   stones. Neutral lettering on beige tiles has a strict digit fallback; conflicting
   readings block payment. An unreadable Remove tile also blocks clearance, so
   skipped price reads cannot falsely mark the zone clear.
   The exact full-word Remove template proves the command. Redundant OCR of
   that already matched label is avoided because beige backgrounds distort it.
6. Write the same transaction ID into both the layout and upgrade journals
   before paying. Discard the stripped temporary edit, prove the original slot
   is still active, and return Home to verify the exact resource deduction and
   an unchanged-or-increased gem count. If a reward masks that deduction, two
   matching native demolition/Cancel controls for the selected obstacle must
   also have proved removal started. A stale proof from another transaction
   cannot be reused. Uncertain outcomes block another payment.
7. Allow one new removal per visit. Observe its native progress control finish,
   then allow the reward to settle before the next payment. A 90-second guard
   is used when completion was not observed. This separates seasonal resource
   rewards from the next obstacle's deduction. Builder availability is neither
   a removal requirement nor evidence that removal has finished.
   After a confirmed removal, continue the full clearance pass. Never return
   to placement after just one removal. Preserve saved drafts during clearing.
   Once all registered survey views are complete, begin native copy matching.
   Clearance older than one day is checked again before further imports.

A short-lived identity proof is held only on the current controller session;
it is never persisted or shared across account visits. The controller’s device
lease excludes simultaneous manual control. Recovery can reconcile an already
closed editor and a crash between the two receipt writes without paying twice.

## Placement and activation

The official import establishes the defensive arrangement. Missing buildings
retain their empty planned spaces. Remaining owned inventory is read by level,
artwork and quantity, including three-digit wall stacks.

The first visible inventory card is completed before advancing. Its count can
be checked without the native tray scrolling to another card during a drag.
Inventory-only swipes restore its first page before selection. A full first
card must remain unchanged after the swipe; fading arrows alone cannot prove
the page. Items lift vertically before moving across the map so the game does
not mistake a diagonal pickup for horizontal inventory scrolling.
The reader follows the actual blue card boundaries: short inventories centre
themselves and recenter after a card disappears. These shifts do not change
the observed item's identity or count.
If OCR confuses a level such as 11 with letters, its numeric suffix must match
the actual native digit glyphs. Uncertain labels are not guessed.
The known hut card with no displayed level requires its exact artwork and a
blank caption area; failed OCR on an ordinary level cannot become that card.
Thin reflections on storage artwork are excluded from quantity glyphs, so a
single storage does not become an unreadable stack when the previous card
disappears. Actual stack labels still require their multiplication glyph and
verified numeric count.

The placer proposes clear peripheral tiles outside reserved future footprints.
It ranks candidates by grass coverage over the whole building footprint before
preferring the edge, avoiding repeated attempts along strips too narrow to fit.
That ranking cannot authorize a drop or replace the native overlap checks.
It holds an inventory item, reacquires the camera after native movement, and
reads the actual footprint floor. Lime movement arrows are not acceptance.
The connected floor's full width distinguishes a large building from the small
tile diamonds drawn inside its footprint. Larger floors are allowed to extend
below the drag pointer, while their lower boundary must remain above the tray.
The observed floor also corrects the building-specific pickup offset, so a
large building is positioned by its footprint rather than the finger position.
Two fresh green floor outlines must agree on tile position and size before
release. The subsequent native inventory decrement must verify before another
item is attempted. An unknown receipt retains the move intent rather than
replaying it.
A red floor can teach its dimensions and skip impossible edge cells, but cannot
authorize release. Completing the final item at a visit deadline proceeds to
verified Save and activation rather than trying the incomplete-draft control.
Only an explicit red floor at the proposed world position is cached as a
rejection. Unreadable frames and unsettled confirmation frames remain retryable.
The cache-policy migration preserves confirmed placements and measured sizes.

Future white footprint edges are mapped into tile space and conservatively
expanded to protect their interiors, including partly occluded outlines. The
native game remains the final overlap/boundary validator.

If every placement view has been searched without room after clearance, that
reference is marked incompatible and the next catalog reference is tried. A failed camera read does not disqualify a reference.
If all references fail, it reports that a compatible layout is needed and
keeps the original active base. New construction or a Hall change resets
compatibility checks; it does not silently discard owned buildings.

An enabled native **Save** control is required on two fresh frames before saving.
The selected inactive slot and original active slot must then verify. Only
then may **Set as active** be pressed. The new **Active Village** badge must
verify twice, followed by a verified Home Village. Partial copies cannot activate.
The selected active thumbnail enlarges its caption. Both observed native badge
sizes are recognized without lowering the match threshold. Recovery also
requires Home before marking the automatic stage complete.

## Scheduling, checkpoints and recovery

Each account stores state in `data/layouts/state.json`. The automatic stage is
`clearing`, `matching`, `placing`, `verifying`, or `active`, with a next-check timestamp and bounded
removal history. New construction marks the layout dirty; a verified Town Hall
change also requires a new reference. Ordinary level upgrades do not force a
rebuild.

Placement can save an incomplete inactive draft using **Finish later** and
resume it on a later visit. A small private thumbnail verifies the exact draft.
Its camera-search cursor is saved too: reaching the visit deadline after a pan
must not reset the next visit to an already exhausted corner.
Drafts also retain their exact copy link. A changed reference starts a fresh
inactive copy rather than resuming a different layout. Loading and identity
checks can be slow on a cold visit; after setup, each visit allows at least
30 seconds for actual survey or placement work. Stop still interrupts it.
Confirmed progress is also saved when the next camera or inventory read fails,
provided there is no unresolved drag. Crowded terrain gets a bounded larger
feature search with unchanged geometry thresholds.
The fallback chooser path protects that slot while using another authorized
inactive slot as an expendable import/cancel entry.

Stop interrupts further actions. On restart, an owned unfinished editor is
cancelled or reconciled before ordinary navigation. Exact native Collect All,
inventory-notice and discard dialogs have dedicated recovery controls. A saved
complete layout and interrupted activation are reconciled from observed badges.
On the verified import chooser, an animated copy arrow can cover the active
caption; its independent continuous green border identifies the original slot.
Unknown payments and unclosed edits block account switching. Starting the bot
may recover an owned layout; manual tools cannot bypass that gate.

Secondary account work rotates between upgrades, farming, Builder Base and
layouts. Long operations finish at safe checkpoints, and the existing donor
schedule repays overrun time to the main account.
The donation account waits at least five minutes between layout visits, giving
chat priority while its initial layout is being prepared.

Profile backups preserve configuration and transaction evidence. They do not
back up the game’s server-side layout slots; keeping the active native slot
intact until the replacement is complete is a separate protection.

## Validation

Tests cover account ownership, resource/gem receipts, interruption between journal
writes, native green/red footprints, inventory decrements, future-space guards,
terrain registration, disabled/practice modes and fair account scheduling.
Live validation uses separate inactive copies and records removal costs and gem
balances. Development screenshots and account profiles remain private; generic
UI anchors and anonymous regression fixtures are the reusable repository assets.
Independent native wall probes verified green floors at the first/last legal
tile centres and red floors immediately outside all four edges of the default
44×44 field. The probe's temporary edits were discarded and its inventory
count restored before closing the editor.

The 2026-10-26 live TH12 validation completed 49 resource-priced removals without
a recorded gem deduction, imported the defensive reference, placed the remaining
owned inventory, saved and activated the new slot, and verified Home afterward.
The previous active layout remained in its original slot. This validates that
account and default scenery; it does not establish every catalog link or Hall.
