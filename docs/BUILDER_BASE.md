# Builder Base

Builder Base visits are experimental and independent of Home Village farming.
In **Settings**, choose any combination of **Collect Builder Base resources**,
**Builder Base attacks**, **Builder Base building upgrades**, and **Builder Base
research**. Set the visit interval, builders to keep free, and the Builder Gold
and Builder Elixir reserves. All four switches default to off. Start the bot
normally. Collection-only visits do not require an equipped attack army.

A visit runs between donation operations, after any due Home Village farm or
upgrade check. A visible donation request takes priority. Each visit performs
at most one attack and one eligible upgrade, then returns by boat and verifies
clan chat. The interval runs from completion of the last visit; this separate
schedule uses wall-clock time, so a visit overdue while stopped can run on Start.
There is currently no separate Builder Base countdown or manual attack button.

The visit collects first, checks research and then buildings, attacks if enabled,
and collects again after returning from battle. If no eligible upgrade was found
before the attack, its rewards can trigger another eligibility check. A successful,
blocked, or uncertain purchase never causes a second purchase in that visit.

## Resources and builders

Builder Gold comes from ordinary attack rewards as well as the Star Bonus and
mines. Builder Elixir comes from defense rewards collected through the Elixir
Cart, the Star Bonus, and collectors. An unavailable Star Bonus does not remove
ordinary attack rewards. Defense rewards may arrive later than an attack; the
bot does not wait indefinitely for them. Neither Builder resource can pay for
Home Village donations or upgrades.

Collection recognizes specific Gold and Elixir bubble artwork, rechecks each
target on a fresh screenshot, and surveys the two connected areas and shoreline.
The Elixir Cart requires its title, close control, and enabled green Collect
button. Generic yellow/purple objects and the Gem Mine are not collection targets.
Collection is bounded by time, camera movements and taps. Unknown screens stop
it, and the recognized Star Bonus is dismissed before continuing.

Counters must settle before reporting gains. A disappearing bubble alone is not
proof of collection. Unreadable counters, full storage and unchanged amounts are
reported as unverified rather than invented gains; the bot does not repeatedly
tap the same bubble in one view. The report's total balance change can include
rewards arriving during the visit. Unknown gem readings stay unknown. A verified
gem balance change leaves a review checkpoint that blocks automatic recovery.

Builder availability is read as a fraction rather than assumed to be two. Counts
from 0/1 through 3/3 are supported when consistent, and the free-builder reserve
is respected. Master Builder, O.T.T.O. and the optional B.O.T.O. are Builder Base
workers; the B.O.B. unlock supplies the extra Home Village builder. The bot does
not purchase builders or attempt to transfer the Master Builder.

## Attacks

Equip **six Night Witches and Battle Machine** in Builder Base before enabling
attacks. The first version verifies this starting army before matchmaking and
skips other armies. It does not edit the army or train troops automatically.

The runner verifies Builder Base battle headers before touching the army bar,
zooms out, and finds clear drop tiles beside the visible deployment boundary.
It deploys Night Witches followed by the hero, checks card changes after each
placement, and activates recognized deployed-unit abilities. The same camera
must remain verified before reusing a drop location after the boundary vanishes.
Second-stage survivors and the inspected Battle Copter card are supported;
unrecognized cards are left alone. Both stages get fresh map checks.

Results require the **Total damage** heading and **Return Home** button. The
runner leaves when these are visible rather than waiting for a fixed battle
timer. The eight-minute limit only bounds recovery: it does not authorize a
blind Return Home tap. The inspected Star Bonus dialog is acknowledged before
returning to Home Village.

This is a simple catch-all deployment, not a tactical planner. It targets the
inspected English landscape layout and default Builder Base arenas. Different
sceneries, skins, camera positions, or armies can block recognition. Unknown
screens stop the operation rather than entering Home Village recovery.

## Upgrades

Only existing supported defenses and resource buildings in **Suggested
upgrades** paid with **Builder Gold** qualify for building upgrades. Builder
Elixir building confirmations are not supported yet. Builder Hall, heroes, walls,
new construction, gems, potions, and items are excluded. The shared
excluded-building-name setting also applies. Builder availability and reserves
are separate from Home Village.

The separate research switch supports **Night Witch** research paid with Builder
Elixir. It requires a free Star Laboratory, the recommended unit, sufficient
Elixir above the reserve, the matching portrait and ability label, and the exact
price and currency in the confirmation. Other troop research is skipped until
its confirmation has been inspected and tested. After payment, only the verified
close control is used; the Finish Upgrade button is never pressed.

The runner checks the building name, resource, price, balance and availability
on fresh frames before confirming. It records a pending transaction before
spending and then checks for a new running upgrade and fewer free builders.
An uncertain transaction is retained for review and is not automatically retried.

## Recovery and development

- `src/coc_bot/builder_base/vision.py`: village, boat, battle, troop-card,
  reward and upgrade recognition, using isolated UI templates.
- `runner.py`: bounded visits, deployment verification and return navigation.
- `resources.py`: bubble/cart collection, bounded camera survey and balance checks.
- `upgrades.py`: Builder-specific policy layered on the shared upgrade transaction.
- `data/builder_base/visit.json`: durable navigation checkpoint and visit schedule.
- `data/builder_base/upgrades.json`: separate spending journal.
- `data/debug/builder-base/`: at most 32 evidence frames per visit, included in
  the existing attack diagnostic retention budget. Pending visits preserve evidence.

Stop interrupts the current action. On restart, a pending visit is recovered
before donation, Home Village farming, anti-idle inputs or breaks can run.
Recovery waits out an existing battle without starting new deployments, closes
only verified controls, and returns to clan chat. Practice mode starts no visits.
Saving settings while running finishes the visit before restarting the worker;
the priority Stop button remains immediate.

Run the Builder Base, upgrades, settings, game-state and screenshot-retention
tests after changes. Test fixtures contain isolated game controls rather than
account names. Live screenshots remain private diagnostic data.

The versioned army candidates in `src/coc_bot/progression/profiles.py` cover
TH1–18 and BH1–10 with capacity, unlock, freshness and release checks. They are
research profiles, not additional supported attack executors. Their automatic
release flags remain off. Automatic army editing and attacks with Dragons,
Baby Dragons, P.E.K.K.As/Bombers and low-hall ground armies are still pending.
The current Home Electro Dragon and Builder Night Witch executors remain in use.
See [the progression plan](ARMY_PROGRESSION_PLAN.md) for those later phases.

The initial live validation on 2026-10-24 started an Elixir Collector upgrade for
5,000 Builder Gold and verified the builder count changing from 2/2 to 1/2.
The corrected attack completed both stages at 200% damage, received 130,000
Builder Gold, recognized results and returned. A Star Bonus interrupted the
first return; its recognition was added and recovery back to clan chat verified.
The gem balance stayed unchanged during these checks. These are individual observed
tests, not a guarantee for every base or account.

Further validation on 2026-10-24 collected 108,000 Builder Gold and 616,425
Builder Elixir across mines, collectors and the Cart, started Night Witch level
13 research for 2,500,000 Builder Elixir, and verified its occupied research slot.
A complete subsequent visit collected resources, started an Elixir Collector
upgrade for 400,000 Builder Gold, finished an attack at 150% damage, collected
again and returned to clan chat. That attack earned 114,000 Builder Gold after
the Star Bonus was already claimed. The visible gem balance remained 698;
some intermediate counter reads were unavailable and stayed unverified in reports.
Calibration and saved settings were unchanged. A separate Ubuntu test environment
passed 292 relevant regression tests, including the browser settings API and OCR
fixtures. Three-builder accounts, full storages and lower-hall armies have not
been live-tested on this account.
