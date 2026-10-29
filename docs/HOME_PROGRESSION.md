# Home Village progression

Wall upgrades use the native **Upgrade More** selector when its controls can be
verified. The bot adds one wall at a time and checks the count and total price
after every change. With no reserve, it previews one unaffordable wall and removes
one; with a configured reserve, it stops at the reserve-safe maximum. It never
uses gems, wall rings, or other items. Unknown controls stop the batch.

The selected count, unit price, total price, currency and before balance are
saved before requesting payment. The dedicated **Upgrade Walls** dialog must
name the exact total and gold/elixir currency on two fresh frames. Confirmation
is attempted once. Two complete inventories must then show the expected wall
queue reduction and matching resource deduction. Interrupted receipts reconcile
without buying another batch. A single-wall fallback remains for recognized
panels without Upgrade More.

The Laboratory is the first building priority when an eligible upgrade is
available. New construction follows, then other buildings and walls. The Town
Hall still requires a complete, readable, unfiltered inventory proving all
available buildings are finished; unaffordable rows do not count as maxed.

Defensive/trophy references for Town Halls 4–18 are kept in
`src/coc_bot/layouts/catalog.json`, with multiple official copy links per Hall.
References are candidates, not a promise of defensive performance or compatibility
with a later game update. Exact copy links are restricted to the official domain
and the saved account's Hall. TH2/3 stay unchanged until the native editor unlocks.

**Automatic defensive layouts** is a separate account setting. It first clears
permitted obstacles throughout the build zone using an inactive native editor.
Only after that survey finishes does it test imported layouts against the actual
owned inventory. Complete native fits take priority; after testing candidates,
at most six verified leftover items may be placed with native green-floor and
inventory receipts. Large merge/inventory mismatches need another reference,
not mass placement or automatic merging. Activation requires
all owned buildings to be placed, followed by an independent match between the
active preview and two actual Home screenshots. Seasonal clearing and replacement
of occupied inactive slots each need their own enabled option. Gems and shovels
are excluded, and the original active slot is kept until its replacement is ready.

State and payment receipts are account-scoped at `data/layouts/state.json`.
Bounded visits can save and resume incomplete drafts, and unresolved edits or
payments block switching. Default-terrain registration and native editor support
are required; TH2/3 do not yet have an automatic native-copy path. See
[automatic layouts](AUTOMATIC_LAYOUTS.md) for settings, geometry, checkpoint and
recovery behavior. Profile backups do not back up native game layout slots.

Village progression is an opt-in extension to automatic farming and building
upgrades. Enable **Settings â†’ Upgrades â†’ Village progression** on the selected
account. The account also needs the Farming and/or Upgrading role, the relevant
automatic schedules, and suitable resource reserves. A role alone does not turn
on a schedule. Settings and transaction history remain separate for each account.

This is being validated first on a Town Hall 2 account with the inspected English
landscape interface. Tutorial prompts and every later Town Hall are not certified
for unattended progression. The existing Electro Dragon method remains available
when Village progression is off.

## Farming army

Before an automatic attack, the app reads the Town Hall's next-level badge in the
Build list on two screenshots. It uses that to establish the current level without
opening a Town Hall purchase. It then opens My Army, checks the occupied and total
camp space, and identifies the current troop cards twice.
An empty army is supported: the wide empty layout must show zero occupied camp
space and the exact troop-row **Tap to edit** prompt on two fresh frames before
the troop picker opens. An empty Clan Castle area does not qualify. The bot then
reads unlocked troop levels and Info panels before adding any troops.
The native picker font includes higher-level digit shapes as well as starter
level 1. Gray cards without a verified level remain locked. A dropped Info
level 1 can be resolved only from its separate visible yellow numeral, not from
the expected picker value alone.

After a battle, the blue **Star Bonus received!** reward can cover the village
while its Build and Battle buttons remain visible behind it. Its exact title,
Treasury-delivery message and enabled **Okay** control must match on two fresh
frames before acknowledgment. Home confirmation continues after that window
closes; it cannot itself complete the attack checkpoint.
An uncertain first badge or a slightly moving row gets a bounded wait for two
consecutive matching rows and levels. Saved account metadata never fills an
unreadable level, and conflicting readings still block preparation.
The complete badge must account for every visible digit; an observed level
below the verified saved account level is rejected. The first-use Battle Menu
instruction can be dismissed after its exact caption and speech-bubble corners
match twice, before Edit Army is used. Other dimmed or unknown instructions do
not authorize army input.

Only verified unlocked troops qualify. A gray troop portrait alone does not prove
an unlock: the troop picker must show a readable level badge and matching artwork
on two fresh screenshots. The chosen composition
comes from the [reference armies](ARMY_PROGRESSION_PLAN.md), scaled to actual camp
space. A starter account with only Barbarians uses Barbarians; Archers and Giants
can join after their actual unlocks are recognized. Later reference families use
Giants with ranged support, Dragons, and Electro Dragons with Balloons.

If the artwork is ambiguous, the app may open that unlocked card's verified blue
Info control. Two fresh Info screens must agree on the troop name and level and
show the expected stats/close controls. It then closes Info and caches that card's
artwork inside this account. Future matches use fresh portrait landmarks, not a
remembered card position. A hash mismatch invalidates cached artwork. These reads
never press the research, magic-item, or upgrade buttons inside Info.

Every army edit must produce the expected troop count and housing-space change.
Opening the troop picker dims the army header. If that header is unreadable,
two fresh, complete card readings must still prove the exact expected counts
against the previously verified camp limit. Any readable conflicting capacity
rejects the edit. Initial and final army checks require a readable capacity;
the final check dismisses the picker first. Safe picker navigation and closing
use their own visible controls instead of depending on capacity text.
Unknown cards, conflicting counts, missing controls, and unexpected edits stop
preparation. The app does not purchase unlocks or fill missing space with gems.
When a newly added troop's small army card differs from its picker artwork, its
identity can be learned from that edit: a fresh named picker selection, exactly
one new card, unchanged existing counts, and the exact housing increase must agree
on two screenshots. The verified small portrait is cached for later attacks.
Spell composition is not automatically edited in this version; only an already
recognized supported Rage spell may be used by the executor. Recall is not Rage.

The attack still requires a verified opponent screen, fresh deployment-boundary
mapping, stable camera evidence, and a visible quantity decrease after deployment.
Ground attacks deploy Giants before support troops. Results recognition ends the
attack; the recovery timeout remains a fallback. Accounts without the Donating
role confirm the home Build control instead of trying to open locked clan chat.

The progression ground routine can send up to five troop taps together. Each
group requires fresh battle/camera/card checks, clear mapped targets, and the
exact expected decrease in troop count afterward. A partial or uncertain result
stops deployment and is never replayed. Stop is checked before each group; up to
five already-sent inputs can be in flight. Heroes, siege machines, spells, and
the established air-attack method retain their separate checks.

TH2's red deployment outline can surround separate small building groups. Its
starter mapper therefore creates a conservative envelope around the complete
visible outline on two stationary frames, rather than demanding one large
diamond. Troops deploy along a visible, unobstructed portion outside that envelope.
The envelope's conservative corners can extend under controls; those portions are
never chosen as deployment targets. Missing outline evidence, cropped
edges, camera movement, or unclear battle controls still block deployment. This
path is restricted to a freshly verified TH2 army; other accounts retain the
normal multi-view mapper.

If a verified Dragon or Electro Dragon army lacks a recognized filler troop,
army preparation can retain the mass-air family and leave spare camp space
empty. It never assumes an unrecognized filler is unlocked. Fresh troop
identities, quantities and actual housing must still agree before deployment.

## Building order and Town Hall gate

The progression reader scans the complete unfiltered building list, including
Other upgrades. The Laboratory takes first priority; new gold/elixir buildings
then take priority over other existing upgrades.
New construction applies a resource filter before selecting its fresh row, so
gem-only purchases are removed from the candidate list. Existing upgrades favor
offensive capacity and storage; walls are handled as instant upgrades. Exact
payment must accompany either the selected wall's level increase or a two-frame
decrease by the purchased wall count in the queue at the same verified target
level and unit price.
When the final wall leaves that queue, two complete readable inventories must
confirm its absence; a missing row on a scrolled page is insufficient.

Town Hall upgrades require a complete, unfiltered, readable inventory, no busy
builders, and no remaining available construction or building/wall upgrades.
Being unaffordable, excluded, or unreadable never counts as being maxed. A partial
inventory blocks Town Hall progression. Premium builder purchases do not become
a requirement. The normal upgrade method still excludes Town Hall upgrades when
Village progression is off.

There is one approved starter exception: at a verified TH2, the unreconstructed
Clan Castle's exact level-1, 10,000-elixir rebuild may wait until TH3 if that amount
is unavailable. TH2 normally cannot store the required amount. All other available
TH2 buildings and walls must still be maxed. If overflow rewards already make the
rebuild affordable, it remains a prerequisite; at TH3 the exception never applies.
Unknown prices, target levels, or Town Hall readings do not qualify.
[Supercell's rebuild cost](https://ingame.help.supercellsupport.com/clash-of-clans/en/articles/joining-a-clan-3.html),
[starter storage limitation](https://clash-of-clans.1337wiki.com/town-hall-level-2/).

The Laboratory prioritizes units recorded in the account's most recently prepared
farming army, then the supported farming-unit order. A locked or busy Laboratory
is skipped. Two fresh Build-menu images must show the Research tab's actual
padlock before it is skipped as locked; a missing or unreadable list alone is
insufficient. Laboratory spending cannot be exercised on TH2 before it unlocks.

## Making room

**Search for building space** moves only the selected new-building preview through
a bounded set of positions. A stable green checkmark and matching red cancel
control are required before paying. Positions scale with the observed controls,
including zoomed and tall-building previews.

**Clear ordinary obstacles** is a separate opt-in. It runs when placement searches
fail and recognizes ordinary trees, trunks, bushes, mushrooms, stones, rocks, and
logs. **Remove seasonal obstacles** separately permits other named obstacles with
the same verified Remove command and gold/elixir price on two screenshots.
Both respect reserves and free builders, journal the payment, and check the
matching resource deduction and no gem loss. Gem charges, shovels, storage actions,
and unreadable names/prices remain excluded. The next construction check retries
after clearing finishes.

This version does not repack the whole base or move existing buildings. If bounded
placement and ordinary clearing cannot establish a valid spot, construction pauses
for review rather than moving unrecognized objects.

## Spending, interruptions, and evidence

The app records an intent before a construction, wall, or obstacle payment. Exact
resource deductions and the corresponding changed UI must confirm the outcome.
An uncertain or interrupted payment blocks further spending for review; restarting
does not repeat it. Do not delete a pending journal to force a retry.

Evidence stays inside the active account's profile:

- `data/progression/army.json`: observed hall, capacity, unlocks, and prepared troops.
- `data/progression/picker-references/`: bounded, automatically learned troop
  portraits and matching identity/hash records; these can be relearned from Info.
- `data/progression/army-references/`: smaller troop portraits learned from verified
  named additions and matching housing/count changes, with identity/hash records.
- `data/progression/*-inventory.json`: latest building/research inventory.
- `data/progression/screens/`: bounded, overwritten inventory screenshots.
- `data/upgrades/state.json`: shared spending journal.
- `data/debug/attack-surveys/` and `attack-executions/`: attack evidence covered by
  the existing screenshot-retention rules.

Calibration is not rewritten by progression. Back up the persistent profile volume
before a new-account trial, and keep its schedules disabled until a supervised
attack and upgrade check succeed.

Sparse starter battlefields use the complete visible footprint outline to build
an enclosing deployment envelope. Short stepped fragments are retained, but both
diagonal directions, clear screen boundaries, and two stationary observations
remain required. Missing or moving outlines never authorize troop inputs.
Small white starter resource counters use the inspected capacity/price font
variants with the usual strict matching thresholds. Conflicting readings still
block spending.
An inspected My Army heading also handles an observed OCR error without guessing
troop counts. Its heading and close control can recover a failed army read before
an account handoff; unknown or covered controls do not authorize input.

## Supervised TH2 pilot, October 24â€“25, 2026

The live pilot built an Elixir Collector, Gold Mine, Cannon, and Archer Tower,
then started and reconciled the Army Camp level-2 upgrade. Resource deductions
were checked, and the gem balance stayed unchanged. A 20-Barbarian attack verified
all 20 troop-count decreases, gained gold and elixir, recognized the results, and
returned home before the fallback timer.

After the camp finished, army preparation recognized its new 30-space capacity
and filled it to 30 Barbarians using verified picker inputs. Partial-army alerts
and the picker level font have dedicated regression examples, and troop quantities
use strict game-font matching before falling back to OCR.
The subsequent attack verified six groups of five deployments in about 19 seconds,
then recognized results on two frames and returned home before the timeout.
The pilot also started and verified the 500-elixir Barracks level-2 and
2,500-elixir level-3 upgrades. Two wall upgrades each spent exactly 1,000 gold;
the second confirmed completion automatically after the game deselected the wall.
After unlocking Giants and Archers, the pilot prepared 2 Giants, 10 Barbarians,
and 10 Archers and verified the full 30/30 housing total. Picker and smaller army
portraits were learned from Info and verified addition evidence; their common
level badges are excluded from picker identity matching.
That mixed army then deployed all 22 troops in the planned Giant-first order,
recognized results, returned home automatically, and gained gold and elixir.
The gem balance remained unchanged throughout these supervised trials.
The continuous pilot also exposed an unreadable red 5,000-elixir Barracks price
and an unavailable Laboratory tab. The price now uses the inspected game-font
variants with the existing strict confidence checks, and a verified padlock
skips research without sending a tab or purchase input.
After deploying those fixes, the normal scheduled cycle started and verified
Gold Storage for 750 elixir, skipped the locked Laboratory, and then started and
verified Elixir Storage for 750 gold. These were ordinary scheduled checks rather
than individually directed upgrade helpers.
The following scheduled farm also prepared the same mixed army, verified all
22 deployments, recognized results on two screenshots, returned home before the
timer fallback, and recorded its next randomized farming interval. The normal
loop then resumed building checks.

These observations do not certify later Town Halls, automatic whole-base
rearrangement, or Laboratory progression. Laboratory spending still needs its
own supervised trial on a suitable target. The final-wall
complete-inventory check is covered by regression tests; the pilot has not yet
reached the last wall in its queue.

A separate supervised high-Town-Hall test removed anniversary cakes for 14 gold
each and a Curious Stump for 2,026 elixir, with matching deductions and an unchanged
gem balance. Seasonal removal required its own enabled setting. The inspected
low/high Home builder counters and the later Dark Elixir/gem HUD rows have
regression examples; unverified availability or prices still block removal.
Copied defensive layouts remain inactive drafts until all existing buildings are
placed and the game accepts the layout. Missing buildings keep empty footprints;
saving an incomplete draft does not make it a valid active village.

Upgrade passes give buildings, Laboratory, and pets a turn, then revisit building
upgrades after each confirmed start to fill remaining available builders. Each
attempt rereads resources, availability, and confirmation details. A pass is
bounded to ten attempts and stops for an uncertain payment or a waiting donation
request. Remaining work is revisited on later checks. Farming troops retain
Laboratory priority; other verified research can follow once those priorities
are finished. Resource reserves, explicit exclusions, locked facilities, and
unreadable screens can legitimately leave a slot idle.

If automatic attack mapping cannot verify a deployment boundary before any
deployment attempt, it uses the verified End Battle control and confirms Home
instead of waiting through the match timer. A durable recovery marker preserves
this intent across restart. Once deployment may have occurred, normal battle-end
recognition and conservative recovery still apply.

Affordable new structures retain priority after the Laboratory. If a named new
structure is unaffordable or unsupported, independently verified affordable existing
upgrades can keep other builders working. The incomplete construction queue still
blocks Town Hall advancement. An unreadable price on a named existing structure
is skipped individually; unknown construction identities remain a blocker.
