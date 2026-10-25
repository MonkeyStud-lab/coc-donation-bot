# Home Village progression

Village progression is an opt-in extension to automatic farming and building
upgrades. Enable **Settings → Upgrades → Village progression** on the selected
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

## Building order and Town Hall gate

The progression reader scans the complete unfiltered building list, including
Other upgrades. It gives new gold/elixir buildings priority over existing upgrades.
New construction applies a resource filter before selecting its fresh row, so
gem-only purchases are removed from the candidate list. Existing upgrades favor
offensive capacity and storage; walls are handled as instant upgrades. Exact
payment must accompany either the selected wall's level increase or a two-frame,
one-wall decrease in the queue at the same verified target level and price.
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

**Clear ordinary obstacles** is a separate opt-in. It runs only when placement
searches fail, and only for a recognized ordinary tree, trunk, bush, mushroom,
stone, rock, or log with matching gold/elixir removal prices on two screenshots.
It respects reserves and free-builder requirements. Special obstacles, decorations,
gem charges, and unknown names are left alone. The next construction check retries
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

## Supervised TH2 pilot, October 24–25, 2026

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
rearrangement, obstacle removal, or Laboratory progression. Obstacle and Laboratory
spending still need their own supervised trials on suitable targets. The final-wall
complete-inventory check is covered by regression tests; the pilot has not yet
reached the last wall in its queue.
