# Progression and army plan for both villages

Research date: **2026-10-24**. Scope: Home Village TH1–18 and Builder Base
BH1–10. This is a proposed development plan, not a list of armies already
supported by the app.

Implementation status (2026-10-25): the candidate compositions are encoded and
capacity-checked in `src/coc_bot/progression/profiles.py`, including verified-unlock,
freshness and release gates. An opt-in Home Village pilot reads actual Town Hall,
camp space and troop unlocks, prepares a supported farming army, and applies
construction-first progression. The reference profiles remain unreleased as
complete all-hall presets. The initial live target is TH2; see
[Home progression](HOME_PROGRESSION.md) for tested behavior and limits.

The goal is dependable farming and continued upgrades with little user input.
These are deliberately simple candidate armies, not claims about the strongest
war or tournament compositions. All tactical choices below are recommendations
to test. Published unlocks and capacities are reference constraints.

## Design decision

Use a few reusable attack families, then scale them to the account:

- Home Village: basic ground troops, Giants with ranged support, Dragons,
  then mass Electro Dragons.
- Builder Base: Barbarians/Giants, spread Baby Dragons, then Power P.E.K.K.As
  with a wall-opening support camp.
- Keep the existing six-Night-Witch Builder Base routine as a tested baseline
  and fallback on eligible accounts. Do not replace it merely because a new
  candidate exists.
- Select from actual unlocked units, levels and capacity. Town Hall or Builder
  Hall alone never proves that the account can field an army.
- Do not prioritize Home Village elixir alone. Record all loot and whether it
  supports the next eligible upgrades, without constantly changing strategies.

No baseline army depends on donated Clan Castle troops, Super Troop boosts,
event troops, purchased equipment, gems, potions, or premium builders.

## Current mechanics that matter

The May 2026 update moved the Barbarian King unlock to TH4 and introduced an
additional Builder Base builder through the shop, subject to Home Village
builder prerequisites. Therefore neither an old TH7 King assumption nor a
fixed two-builder limit is suitable for general progression.
[Official May update](https://supercell.com/en/games/clashofclans/blog/release-notes/may-update/).

The current builder identities are important: Master Builder works in Builder
Base; O.T.T.O joins there at BH6; the optional B.O.T.O adds another Builder Base
builder when unlocked. B.O.B is the permanent sixth Home Village builder after
the BH9 tasks. The old choice to move Master Builder between villages was
replaced in Builder Base 2.0. Do not implement a transfer button based on the
pre-2023 rules. Read the actual free/total count, supporting totals of 1, 2 or 3,
without assuming that a hall level proves a purchase or unlock.
[Current official builder guide](https://support.supercell.com/clash-of-clans/en/articles/builder-base-getting-master-builder-to-home-village-3.html),
[Builder Base 2.0 patch notes](https://supercell.com/en/games/clashofclans/blog/release-notes/full-patch-notes-bb2/).

TH18 has a maximum normal army capacity of 352. The April update added Army
Camp level 14. Our reference capacities below come from camp count multiplied
by the maximum capacity available at that hall; the live account may have less.
[Official April update](https://supercell.com/en/games/clashofclans/blog/release-notes/the-sound-of-clash-update/),
[Army Camp reference](https://clashofclans.fandom.com/wiki/Army_Camp/Home_Village).

Builder Base opens from Home Village TH6. Its attacks earn Builder Gold;
defense earnings provide Builder Elixir through the Elixir Cart. Two-stage
bases begin at BH6. A progression loop must collect that cart and maintain
defenses as well as attack.
[Official Builder Base guide](https://sc-clashofclans.zendesk.com/hc/en-us/articles/49529081752219-About-Builder-Base).

## Home Village armies, one level at a time

Troop counts below exactly fill the maximum normal camp space. They exclude
heroes, siege machines, pets and Clan Castle reinforcements. A fresh or rushed
hall must use a smaller validated composition until its camps catch up.

Unlock checks must include the relevant Barracks level: Wizards at TH5,
Dragons at TH7, and Electro Dragons at TH11 are milestones, not automatic grants.
The smaller troops' housing sizes and unlocks are in the
[troop reference](https://clash-of-clans.1337wiki.com/troops/);
Supercell confirms the Electro Dragon's TH11/Barracks 13 unlock and 30 housing
space in its [release article](https://supercell.com/en/games/clashofclans/blog/news/the-electro-dragon-is-here-to-wreak-devastation/).

Spell capacity assumes the factories have been built and upgraded:
2 at TH5, 4 at TH6, 6 at TH7, 7 at TH8, 9 at TH9, and 11 from TH10.
Rage/Healing each take two spaces; the other spells listed here take one.
Freeze begins at TH9. The proposed spell counts fit those capacities.
[Spell Factory](https://clashofclans.fandom.com/wiki/Spell_Factory),
[Dark Spell Factory](https://clashofclans.spokland.com/building/army/dark_spell_factory),
[Freeze](https://clashofclans.fandom.com/wiki/Freeze_Spell).
Use these sources for capacity/unlocks; older brewing-time/cost text on secondary
pages is not a requirement for the bot.

### TH1 — 20 troop space

- **Army:** 20 Barbarians.
- **Spells:** None.
- **Progression:** Tutorial only; do not automate tutorial dialogs.

### TH2 — 30 troop space

- **Army:** 2 Giants, 10 Barbarians, 10 Archers.
- **Spells:** None.
- **Progression:** Build offensive capacity; unlock Giants and finish the tutorial before multiplayer.

### TH3 — 70 troop space

- **Army:** 8 Giants, 2 Wall Breakers, 20 Archers, 6 Barbarians.
- **Spells:** None.
- **Progression:** Build the second camp; upgrade camps and the Laboratory, then this army's units.

### TH4 — 80 troop space

- **Army:** 8 Giants, 5 Wall Breakers, 30 Archers.
- **Spells:** None.
- **Progression:** Finish camp capacity and develop the available King. Balloons are optional, not a required strategy change.

### TH5 — 135 troop space

- **Army:** 12 Giants, 12 Wizards, 4 Wall Breakers, 19 Archers.
- **Spells:** 2 Lightning.
- **Progression:** Build the third camp and Spell Factory; unlock and research Wizards.

### TH6 — 150 troop space

- **Army:** 14 Giants, 16 Wizards, 4 Wall Breakers, 8 Archers.
- **Spells:** 2 Healing.
- **Progression:** Upgrade camps and Healing. Unlock Builder Base; keep the ground army until Dragons are available.

### TH7 — 200 troop space

- **Army:** 10 Dragons.
- **Spells:** 3 Rage.
- **Progression:** Build the fourth camp, unlock Dragons, and research Dragons and Rage first.

### TH8 — 200 troop space

- **Army:** 10 Dragons.
- **Spells:** 3 Rage, 1 Poison.
- **Progression:** Keep the same troop family; improve Dragon levels and build the Dark Spell Factory for the additional spell space.

### TH9 — 220 troop space

- **Army:** 11 Dragons.
- **Spells:** 4 Rage, 1 Freeze.
- **Progression:** Upgrade camps and spell capacity; improve this army before spending research time on unrelated troops.

### TH10 — 240 troop space

- **Army:** 12 Dragons.
- **Spells:** 4 Rage, 3 Freeze.
- **Progression:** Upgrade camps and spell capacity. Targeted Freeze use needs verified defenses; do not cast blindly.

### TH11 — 260 troop space

- **Army:** 8 Electro Dragons, 4 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Unlock Electro Dragons through Barracks level 13; upgrade camps, Electro Dragons, Rage and supporting heroes.

### TH12 — 280 troop space

- **Army:** 9 Electro Dragons, 2 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Upgrade camps and the main army. Add a supported siege machine only after recognizing its identity and availability.

### TH13 — 300 troop space

- **Army:** 9 Electro Dragons, 6 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Upgrade camps; strengthen the same army and the heroes actually used.

### TH14 — 300 troop space

- **Army:** 9 Electro Dragons, 6 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Keep the composition; prioritize research and useful hero/pet support instead of changing strategy for novelty.

### TH15 — 320 troop space

- **Army:** 10 Electro Dragons, 4 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Upgrade camps and the core army. Newly unlocked troops/heroes are candidates, not automatic replacements.

### TH16 — 320 troop space

- **Army:** 10 Electro Dragons, 4 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Maintain the army; improve its levels and measure actual loot and failed attacks against stronger defenses.

### TH17 — 340 troop space

- **Army:** 11 Electro Dragons, 2 Balloons.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Upgrade camps and main-army research; retain a tested fallback if stronger defenses make this profile unreliable.

### TH18 — 352 troop space

- **Army:** 11 Electro Dragons, 4 Balloons, 2 Archers.
- **Spells:** 5 Rage, 1 Freeze.
- **Progression:** Complete the new camp level and main-army upgrades. The two Archers fill the final two spaces and are cleanup only.

### How these Home Village armies should attack

**TH1:** tutorial handling remains manual. An army entry does not authorize the
bot to dismiss onboarding screens or enter unavailable multiplayer modes.

**TH2–6 ground attacks:** choose one accessible edge. Put Giants ahead of ranged
troops, open a verified wall segment with Wall Breakers where available, then
deploy the ranged group and cleanup. Release fragile troops in groups instead
of sending them individually into splash damage. Healing targets the fighting
ground group. Lightning targets an identified useful defense; two Lightning
spells must not be assumed to destroy every defense regardless of its level.

**TH7–10 Dragons:** use two edge units to create a funnel, then spread the
remaining Dragons across that edge. Place Rage along their observed route.
Use Poison only against identified defenders, and Freeze only against a
recognized threat that is engaging the army. A spell is not useful just because
its card is available.

**TH11–18 Electro Dragons:** retain the mapped-edge foundation. Use edge Dragons
for a funnel, send the Balloons shortly ahead of the main group, and deploy the
remaining Electro Dragons with enough spacing to avoid a single clump.
Place Rage ahead of their progress rather than dumping every spell on empty
ground immediately. The TH18 Archers are optional late cleanup and must not
delay the main deployment.

The five-Rage profile is a deliberately simple starting point close to the
existing executor. Once threat recognition is dependable, compare it with
**3 Rage + 5 Freeze** using the same troop army. Do not silently replace Rage
with Recall or use unknown spell artwork as an alias.

Electro Dragons are a maintenance-friendly farming baseline, not a universal
answer. Wide building gaps, strong air defenses and poor funneling can make them
ineffective, especially at high halls. If measured outcomes remain poor, compare
a regular-Dragon profile or another explicitly tested army; do not infer a
working high-hall strategy from success on a weaker opponent.

### Heroes, siege machines and pets

Use the heroes actually unlocked, equipped and available, within the account's
active slots. Keep their identity, equipment and ability behavior explicit.
Do not require a complete hero roster to run a profile that has been tested
without it. Prioritize support for the selected attack; newly unlocked does not
automatically mean better.

A supported air siege machine can be added after recognition and deployment
verification are tested. Missing Clan Castle troops must not block the baseline.
A different siege card must not be treated as an interchangeable button.

Pets and equipment can improve the chosen army without changing its troop
counts. Their upgrade plans need their own availability/resource checks.
Dragon Duke is available from TH15, but should not automatically replace an
existing hero without testing its interactions with an air army.
[Official February update](https://supercell.com/en/games/clashofclans/blog/release-notes/the-february-update-has-escaped/).

## Builder Base armies, one level at a time

These compositions are in **camps**, not housing space. Read the actual troop
count on each card; some camps contain multiple troops. Reinforcement camps
are separate and cannot be counted as first-stage troops. Their troops join
the surviving army only after reaching stage two.
[Army Camps](https://clashofclans.fandom.com/wiki/Army_Camp/Builder_Base),
[Reinforcement Camps](https://clashofclans.fandom.com/wiki/Reinforcement_Camp).

Baby Dragons require Builder Barracks 6 at BH4; Night Witches require Barracks
8 at BH6; Power P.E.K.K.As require Barracks 10 at BH8. Research levels and
actual unlocks must be checked before switching.
[Builder Barracks](https://clashofclans.fandom.com/wiki/Builder_Barracks).

### BH1 — 1 army camp, 0 reinforcement camps

- **Army:** Tutorial Barbarians only.
- **Progression:** Complete the guided introduction manually. Do not treat the tutorial army as a reusable multiplayer profile.

### BH2 — 2 army camps, 0 reinforcement camps

- **Army:** 2 camps of Raged Barbarians.
- **Progression:** Build both camps and develop the Barbarians. Read units per card; one camp is not necessarily one troop.

### BH3 — 3 army camps, 0 reinforcement camps

- **Army:** 1 camp of Boxer Giants, 2 camps of Raged Barbarians.
- **Progression:** Unlock Giants and upgrade the Star Laboratory. Giants lead, Barbarians follow; avoid feeding them separately into a Crusher.

### BH4 — 4 army camps, 0 reinforcement camps

- **Army:** 4 camps of Baby Dragons.
- **Progression:** Unlock Baby Dragons and build the fourth camp. Space deployments to preserve their isolation bonus.

### BH5 — 4 army camps, 0 reinforcement camps

- **Army:** 4 camps of Baby Dragons.
- **Progression:** Develop Baby Dragons and the Battle Machine. Cannon Carts can wait; their range/mode control adds complexity.

### BH6 — 5 army camps, 1 reinforcement camp

- **Army:** 5 camps of Baby Dragons; 1 Baby Dragon reinforcement camp.
- **Progression:** Build the fifth army camp; develop the second-stage infrastructure and Healing Hut. Inspect survivors before deploying reinforcements.

### BH7 — 6 army camps, 1 reinforcement camp

- **Army:** 6 camps of Baby Dragons; 1 Baby Dragon reinforcement camp.
- **Progression:** Build the sixth camp and strengthen the established army. Six Night Witches are an alternate profile we already have a live baseline for.

### BH8 — 6 army camps, 1 reinforcement camp

- **Army:** 5 camps of Power P.E.K.K.As, 1 camp of Bombers; 1 Power P.E.K.K.A reinforcement camp.
- **Progression:** Unlock Power P.E.K.K.A and the Battle Copter. Keep Baby Dragons or the tested Night Witch profile until the new ground army passes validation.

### BH9 — 6 army camps, 2 reinforcement camps

- **Army:** 5 camps of Power P.E.K.K.As, 1 camp of Bombers; 2 Power P.E.K.K.A reinforcement camps.
- **Progression:** Build the second reinforcement camp and pursue B.O.B requirements. Invest in the main troop and hero levels rather than researching every troop.

### BH10 — 6 army camps, 2 reinforcement camps

- **Army:** 5 camps of Power P.E.K.K.As, 1 camp of Bombers; 2 Power P.E.K.K.A reinforcement camps.
- **Progression:** Improve the same army, heroes and healing. Electrofire Wizards are optional advanced work, not necessary for the first automated progression.

### How these Builder Base armies should attack

**Barbarians/Giants:** use the tanking unit first and then release groups behind
it. A card can still have deployable units after the first map tap; its next tap
must not be confused with an ability.

**Baby Dragons:** distribute them around useful edges rather than placing every
unit together. Maintain separation from other air units where possible.
Activate Fiery Sneeze when its cone has useful targets. Hero routing must
preserve that spacing.

**Power P.E.K.K.As/Bombers:** create one useful opening, send the main group
through it, and keep Bombers behind tanks. Activate deployed-unit abilities
based on observed engagement, not by repeatedly tapping every card.
Until wall-opening behavior is reliable, test six P.E.K.K.A camps as the
simpler comparison profile.

**Night Witch fallback:** preserve the current working implementation while
collecting a broader outcome sample. Its successful live test is evidence for
that run, not proof it is the best army for every BH or layout.

The Battle Machine and Battle Copter need different control rules. Hero charge
levels and troop abilities must not share a generic repeat-tap routine.
The Battle Copter unlocks at BH8; it is an optional available hero, not a
requirement for the baseline. On stage two, re-read surviving cards, health,
ability state, reinforcements and hero availability. Never replay the first-stage
tap count blindly.
[Official hero and troop mechanics](https://sc-clashofclans.zendesk.com/hc/en-us/articles/49529094478875-Builder-Base-Heroes-Troops).

## Upgrade progression policy

### Home Village

1. Build permitted missing camps and unlock required army buildings.
2. Increase camp/spell capacity; upgrade the Laboratory to support the main army.
3. Research the main damage unit, then its spells and support units.
4. Improve the heroes, equipment and pets actually used by that profile.
5. Upgrade storages when they block a planned purchase; keep ordinary builders
   occupied with eligible defenses and economy upgrades.
6. Upgrade the Town Hall after the chosen offense is functional, capacity and
   storage prerequisites are understood, and the next hall offers a useful
   improvement. Do not wait for every wall solely to satisfy a max-everything
   policy, but do not rush beyond the ability to earn resources reliably.

This is a proposed **offense-first progression mode**, separate from the current
game-Recommended upgrade ordering. It should be optional. Town Hall upgrades
and new construction should remain explicit user decisions in the first release.

### Builder Base

Prioritize camps, the selected troop's Barracks unlock, Star Laboratory,
resource capacity and the relevant hero. At BH6, include second-stage
infrastructure; at BH7 finish the sixth camp. At BH8 evaluate the P.E.K.K.A
transition instead of abandoning a well-upgraded Baby Dragon army immediately.

If the additional Home Village builder is still locked, BH9 is an important
milestone. B.O.B requires three Gear Ups, one troop at level 18, one defense at
level 9, and a combined hero level of 45. Plan these dependencies explicitly,
including prerequisite Home Village buildings. Do not treat a Builder Hall
upgrade alone as completion.
[Official B.O.B requirements](https://supercell.com/en/games/clashofclans/blog/news/builder-base-2-0-layouts-troop-levels-and-bob/).

After B.O.B, develop the chosen army and defenses together. Collect the Elixir
Cart, avoid wasting attacks into full storage, and keep resources for scheduled
research or hero upgrades. Builder Gold and Builder Elixir reserves are
independent of Home Village resources.

The optional additional builder must be detected if owned. Do not buy it
automatically or assume it is needed for the progression plan.

## What the current app still needs

Code checked against this working tree on the research date:

- Home automatic mode recognizes and deploys Electro Dragons and Rage, with
  supported heroes/siege. Other troops and unsupported spells are left unused.
  **The mixed armies in this document are not implemented profiles.**
  See [current attack behavior](ATTACK_REBUILD.md).
- Builder Base currently requires six Night Witches and Battle Machine at the
  starting army screen. It does not fill or change that army, and its card
  handling is not a universal multi-unit-camp reader.
- Builder upgrades currently support selected existing buildings paid with
  Builder Gold. Army infrastructure, Builder Elixir purchases, research, hero
  upgrades, walls and hall upgrades need separate support.
- Builder availability parsing and eligibility currently accept at most two
  builders. Extend this with real fixtures for the additional builder before
  claiming compatibility with every account.
- Add verified Elixir Cart collection and capability-aware army preparation.
  See [current Builder Base scope](BUILDER_BASE.md).

## Implementation order

### 0. Builder Base resources and builder availability first

This should ship before new army families. It makes the existing Builder Base
visits useful for progression while preserving the working attack baseline.

**Resource rules:** Builder Gold is earned from successful attacks according
to battle performance and league; it is not restricted to the Star Bonus.
Builder Elixir from defenses goes into the Elixir Cart. The Star Bonus provides
additional Gold and Elixir, and regular rewards continue after it is collected.
Do not revive the original daily-win loot limit or require an active bonus
before every attack.
[Official battle rewards](https://support.supercell.com/clash-of-clans/en/articles/builder-base-versus-battles-3-2.html),
[Supercell's explanation of rewards beyond the bonus](https://supercell.com/en/games/clashofclans/blog/news/builder-base-2-balancing-attacking-defending-and-builders-2/).

Gold Mines and Elixir Collectors also produce resources independently. Their
local buffers stop producing when full and need collection into storage.
The defense-reward Elixir Cart is a separate collection operation, not an
ordinary Elixir Collector.
[Builder Gold Mines](https://clashofclans.fandom.com/wiki/Gold_Mine/Builder_Base),
[Builder Elixir Collectors](https://clashofclans.fandom.com/wiki/Elixir_Collector/Builder_Base).

**Proposed visit order:**

1. Confirm Builder Base and read storage balances, capacities, free builders
   and any visible bonus state. A missing bonus indicator is unknown, not proof
   the bonus is unavailable.
2. Collect recognized Gold Mine and Elixir Collector bubbles in the first area.
   Visit the second area if unlocked and inspect it too.
3. Open the verified Elixir Cart, read the available amount, and collect through
   its recognized free collection control. Close it and verify the village.
4. Re-read balances. If upgrading is enabled, start at most one eligible upgrade
   using the existing purchase journal. Prefer making space before attacking
   when storage is full. If an upgrade has freed room, perform one more bounded
   pass over previously blocked collection sources.
5. If attacks are enabled and useful, run at most one verified attack in this
   visit. An available Star Bonus is a reason to prioritize it, not a condition
   for receiving ordinary battle loot.
6. Handle the verified bonus dialog if shown, then check the Elixir Cart once
   more. Defense rewards can arrive later; an empty cart is not a failed attack.
7. If the upgrade allowance was not used before the attack, re-evaluate after
   rewards. Never repeat a successful or uncertain upgrade transaction.
8. Return to Home Village and verify clan chat. Keep the existing bounded visits
   so Builder Base does not monopolize donation time.

**Collection recognition and verification:**

- Detect resource bubbles with resource-specific artwork and village context;
  do not click all yellow or purple objects. Exclude the HUD, shop, attack UI,
  upgrades and paid resource offers.
- Require a stable target on fresh frames; acquire coordinates again after
  moving the camera or changing areas. Use the existing device lease and Stop
  checks. Never tap a cached building location after a layout change.
- Tap one verified bubble, wait for the collection animation, then re-read
  remaining bubbles and balances. Do not assume one tap collects every mine
  or works across both areas; establish that behavior during live testing.
- Mark success from corroborating evidence such as a cleared/decreased source
  and a balance increase. Handle capped storage and rounded HUD numbers
  explicitly; never invent an exact collected amount from an unreadable delta.
- If a tap selects a building instead, stop collecting and close only a verified
  selection/menu control. Never tap its Upgrade, Boost, Finish Now or Shop action.
- Deduplicate targets within a stable camera view. Bound camera exploration,
  total taps and elapsed time; unchanged frames must not cause endless tapping.
- Keep gold collection, elixir collection and cart collection separate in logs.
  Report collected, empty, storage-full, unrecognized and interrupted distinctly.
- Recovery re-observes the current screen and remaining resources. A checkpoint
  never authorizes blindly replaying a collection tap or a purchase.

**Scheduling and settings:** add a collection switch independent of attacking
and upgrading, so collection-only visits work. Reuse the Builder visit interval
initially. When both storages are full and no permitted upgrade can make room,
skip optional farming; when only one is full, evaluate the other resource's need.
Never conclude that full Gold means Elixir is unneeded. Do not wait indefinitely
for a defense reward or loop attacks continuously to fill storage.

A later resource-targeted schedule can attack until an eligible upgrade's
resource shortfall is covered, within visit/rate limits. Estimate attack Gold,
pending defense Elixir and bonus rewards separately. Use observed game values,
not permanent league payout tables. Builder resources cannot fund Home Village
upgrades or donations.

**Concrete code boundaries:**

- Extend `builder_base/vision.py` for 1–3 builder counts, resource bubbles,
  storage capacity, area transitions and Elixir Cart controls. Capture current
  positive/negative screenshot fixtures before enabling any new tap target.
- Add `builder_base/resources.py` for bounded collection and a structured report
  containing source, area, observed balances and verification outcome.
- Integrate it in `BuilderBaseRunner.run()` around upgrades/attacks. Add collection
  phases to the existing visit journal and recovery logic.
- Update `builder_base/upgrades.py` to accept verified three-builder availability
  and preserve the configured free-builder reserve. Test 0/3 through 3/3 and
  reject impossible fractions instead of assuming every three-builder read is valid.
- Add the collection toggle to config, defaults and the shared settings fields;
  include it in the bot's visit eligibility so it works when both other toggles
  are off. Practice mode continues to issue no collection taps.
- Add tests for both areas, shifted layouts, animated bubbles, empty/full cart,
  capped storage, unexpected dialogs, Stop and restart. Existing attack and
  donation regression checks remain required.

**Live acceptance:** record balances and source markers before/after collection
in both areas, separately demonstrate cart collection, and verify return to clan
chat. Confirm that gems do not decrease. Validate an ordinary attack reward
when the Star Bonus is already unavailable to distinguish it from bonus loot.
Where a scenario cannot be reproduced on the available account, report it as
untested instead of treating a mock fixture as live proof.

### 1. Account capabilities and versioned profiles

Read and persist the village, hall level, actual camps/capacities, unlocked
units, researched levels, spell capacity and available heroes. Keep observation
timestamps and confidence. Conflicting reads must block spending or army edits.

Store each profile as data with required capabilities, unit counts or camp
assignments, spell counts, fallback, deployment policy and supported game/UI
version. Validate all capacities before preparation. Keep the existing custom
routine option.

For lower capacity, choose a tested smaller variant: keep a minimum useful core,
then add support and cleanup without exceeding the observed capacity. Do not
merely round every unit count or shrink a composition until its core disappears.
A locked/weak new unit should keep the previous validated family eligible.

### 2. Army preparation and card recognition

Implement editing at home, verify the resulting army on two fresh frames, and
verify the My Army confirmation before matchmaking. Read identities as well as
counts. Snapshot the user's army before changing it and offer restoration.

First extend the already-working Electro Dragon and Night Witch families.
Then implement Dragons, Baby Dragons and P.E.K.K.As/Bombers. Finally cover
low-hall ground armies and multi-unit Builder cards. A higher hall does not
provide live validation for a lower hall's distinct UI.

### 3. Outcome-driven execution

Retain positive battlefield checks, deployment verification, camera recovery,
immediate Stop and durable crash checkpoints. Result recognition ends attacks;
a timer is only a recovery bound.

Add funnel timing, support placement and each new spell/ability separately.
Measure zero-deployment and zero-damage incidents before optimizing damage.
Recognize single-stage versus two-stage Builder battles, partial second stages,
early defeats, and reward dialogs.

### 4. Progression-aware upgrades

Add the missing Builder resource/army/research transactions one category at a
time. Verify currency, displayed price, balance, builder/research availability
and post-purchase state. Preserve the no-gems policy and uncertain-transaction
journal. Do not retry an uncertain purchase.

Make the optional progression mode reserve resources for its next useful
offensive upgrade while leaving the existing Recommended mode available.

### 5. Validation and release gates

- Unit-check all 18 Home compositions against housing and spell capacities.
  Check all 10 Builder entries against initial and reinforcement camps.
- Add real screenshots for each changed army UI, partial capacity, multi-unit
  cards, locked units, missing heroes, full storage and additional builders.
- Test each family under supervision before scheduling it. For each available
  hall/profile, initially aim for 20 varied completed attacks; this is a
  proposed sampling target, not proof of universal reliability.
- Record hall, army levels, actual composition, opponent hall where readable,
  deployment success, damage/stars, loot, time, return-to-chat success and
  any intervention. Compare the old and new profiles under similar conditions.
- Require no unintended currency spending or unverified purchases, and no
  reproducible navigation/deployment regression. Pause rollout on these
  failures even if average loot improves.
- If damage or loot drops, inspect the army/map evidence and retain the previous
  profile. A handful of high-damage runs must not hide new 0% failures.
- Label untested hall/profile combinations as experimental. Keep their automatic
  selection disabled until there is evidence, rather than claiming support
  solely from this research.

## Research limits and maintenance

Official update notes establish recent changes; community wiki pages provide
the detailed level tables. Some wiki pages were accessible through indexed
search excerpts rather than direct page loading. No army here has been
benchmarked across all halls. Exact costs, upgrade durations and unit levels
are intentionally read from the game instead of embedded as permanent constants.

Recheck unlocks/capacities after game updates. The live game's observed
capabilities take precedence over this dated reference, but an unexplained
mismatch should require review rather than silently expanding what the bot
is allowed to do.
