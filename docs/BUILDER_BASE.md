# Builder Base

Builder Base is an optional step in each saved account visit. In **Settings**,
choose **Collect Builder Base resources**, **Refill Builder Base resources**,
**Builder Base building upgrades**, and/or **Builder Base research**. Choose
builder reservations and gold/elixir reserves independently from Home Village.
These switches default off. **Builder village progression** adds new structures
and the complete building inventory gate before upgrading the Builder Hall.

The bot collects first, then refills enabled storages using the Farm start/target
percentages (75% / 95% by default). It reads actual balances and native **Max**
tooltips twice. After each battle it collects again, returns Home for the clan-chat
check, and saves the cursor before continuing the refill. Full storages do not
trigger more attacks. Unknown counters, unsupported armies, or three unproductive
attacks defer farming; affordable building and research checks still get a turn.

After refill, the bot checks the Star Laboratory and builders. Bounded batches
check up to three builders with fresh balances and independently confirmed
payments, then return Home for another chat check. A busy Laboratory does not
block free builders. Successful batches repeat until slots are busy or no
supported affordable upgrade remains. Uncertain payments retain their recovery
journal and block account switching. No gems, items or resource purchases are used.

There is no separate Builder Base visit interval in normal automation. Both solo
and fleet operation use the same saved checklist; a completed solo checklist is
checked again after five minutes. Disabled/locked features are skipped, including
Builder Base below Town Hall 6. Legacy interval values are retained only for
compatibility with standalone diagnostic visits.

## First visit

Accounts below Town Hall 6 skip Builder Base visits before starting a boat
journal. On an eligible account, a named **FREE** Boat rebuild can start the
inspected introduction. The bot clears the Home Build list's filters and searches
bounded pages for that exact free entry, including when it is below the first
page. The setup backs up the profile, follows recognized
dialogue and controls, repairs Builder Hall 1 to 2 with 3,500 Builder Gold,
and researches Raged Barbarian 1 to 2 with 3,500 Builder Elixir. It waits the
short timers rather than pressing gem completion controls.

An uninitialized boat can also be located by its wooden hull, adjacent tutorial
arrow, and Home controls on two fresh frames. The first tap selects the boat;
it does not assume the boat can sail. A selected **FREE Rebuild** action opens
the native confirmation, which must independently verify the free price before
rebuilding. This navigation is backed up and journaled, and other arrows are not
generic tap targets.

After rebuilding, the first-trip recovery can close a verified Build sidebar
and reacquire the boat's travel bubble after the tutorial moves the camera.
The exact first-sailing caption also authorizes that bubble while the tutorial
hides normal village controls. Small bubble movement is allowed between fresh
observations. A sea-trip transition gets a bounded observation period without
input; an unknown screen that remains visible still stops setup.

The mandatory three-Barbarian tutorial battle is a setup exception to ordinary
resource-demand scheduling. Its NPC, army count and control layout must match;
it cannot authorize a normal battle. Setup completes only after normal Build
controls return on two fresh observations. Payments are journaled before input,
and the matching resource deduction and unchanged gem balance must verify.
Unknown prompts or interrupted payments remain paused for review. Ordinary
Builder Base attacks still require the supported army described below; this
introduction does not add unrestricted support for other armies or upgrades.

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

The supported armies are **six Night Witches and Battle Machine**, or the
inspected starter **Raged Barbarian camps with three troops per camp**. Both
require fresh army artwork and quantity checks before matchmaking. The bot does
not edit the army automatically; other compositions are skipped.

Starter battles use their normal troop cards, including the enlarged selected
card and its zero-count state. Each individual deployment must decrement the
total remaining count by one. A saved possible deployment is never replayed on
recovery. The first real defense can introduce the Elixir Cart even after the
initial tutorial has finished; its separate account-owned recovery follows the
recognized captions and collection controls without paying anything.

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

Existing supported defenses, resource buildings, **Builder Barracks** and
**Star Laboratory** qualify when paid with **Builder Gold or Builder Elixir**.
The native row parser reads both Suggested and Other upgrades; early villages
can put essential buildings in Other. Among the visible existing rows, the lab
takes priority, followed by Barracks and storages. Each resource has its own
reserve. Without **Builder village progression**, green **New** rows, Builder
Hall and walls are excluded. Heroes, gems, potions and items remain excluded. The shared
excluded-building-name setting also applies. Builder availability and reserves
are separate from Home Village.

The separate research switch supports **Night Witch** research paid with Builder
Elixir. Progression also supports the inspected **Sneaky Archer level 2** dialog.
It requires a free Star Laboratory, the recommended unit, sufficient
Elixir above the reserve, the matching portrait and ability label, and the exact
price and currency in the confirmation. Other troop research is skipped until
its confirmation has been inspected and tested. After payment, only the verified
close control is used; the Finish Upgrade button is never pressed.

The runner checks the building name, resource, price, balance and availability
on fresh frames before confirming. It records a pending transaction before
spending and then checks for a new running upgrade and fewer free builders.
An uncertain transaction is retained for review and is not automatically retried.

Progression inventories the unfiltered building list before selecting work.
The Star Laboratory comes first, followed by missing buildings and then existing
upgrades. A storage upgrade can precede an unbuilt structure when a verified
capacity is too small for its price. Builder Hall advancement requires a complete,
readable inventory, a verified Hall level, no outstanding construction, and no
remaining current-Hall building or wall upgrades. Unaffordable does not mean maxed.
Construction verifies the native placement controls, exact resource deduction
and unchanged gems. Free walls additionally require the unbuilt quantity to
decrease by exactly one. A subsequent wall preview is canceled rather than
placing another item without a new transaction.

The early-village regression fixture covers a 4,000-Elixir Builder Barracks
upgrade and a 15,000-Elixir Star Laboratory row under Other upgrades. The live
Barracks test started its upgrade, verified the builder changing from 1/1 to
0/1, checked the unchanged gem count, and returned to Home Village. This does
not prove every later Hall or troop confirmation. Further live tests built a
1,000-Gold Push Trap, a 12,000-Gold Archer Tower and a free wall, completed a normal
three-Barbarian attack, and verified Sneaky Archer level 2 for 5,000 Elixir.
The gem balance stayed unchanged. Short research can also reconcile after its
timer has finished when two fresh next-level badges, its saved resource
deduction and unchanged gems independently agree. Unrecognized later dialogs
remain blocked for inspection.

## Recovery and development

- `src/coc_bot/builder_base/vision.py`: village, boat, battle, troop-card,
  reward and upgrade recognition, using isolated UI templates.
- `runner.py`: bounded visits, deployment verification and return navigation.
- `resources.py`: bubble/cart collection, bounded camera survey and balance checks.
- `upgrades.py`: Builder-specific policy layered on the shared upgrade transaction.
- `progression.py`: full inventories, construction, free-wall receipts and Hall gating.
- `starter.py`: count-verified ordinary Barbarian deployment and visual results.
- `tutorials.py`: account-owned first-defense Elixir Cart instructions.
- `army.py`: guarded repair of an inspected BH2 army after its second camp is
  constructed. It preserves the first Barbarian camp, fills the empty second
  camp, and verifies two groups of three before matchmaking. Other incomplete
  compositions remain unsupported.
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
The inspected BH2 Barbarian executor also supports its first one- and two-camp
armies; this does not enable the other researched army profiles.
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

On 2026-10-25, a BH2 test account deployed its three ordinary Barbarians with a
verified 3→2→1→0 card-count receipt, recognized results and returned by boat.
The first-defense Cart tutorial was recovered without repeating the attack.
Live construction checks placed a Push Trap, Archer Tower and free Walls;
Sneaky Archer level 2 research was confirmed from its next-level badge and exact
Elixir deduction after the short timer had already finished. The visible gem
balance stayed at 297. A full visit also collected 5,055 Elixir and correctly
stopped when OCR could not verify a remaining wall count. That quantity reader
now checks the actual digit glyphs separately, and recovery verified the existing
placement without sending another purchase. Later farming troops, paid wall
upgrade dialogs and fully automatic Builder Hall advancement still require live
coverage; unfamiliar confirmations remain blocked.

The second Army Camp was subsequently built for 12,000 Builder Elixir. Its
receipt verified 14,448→2,448 Elixir and 297 gems before/after. Testing added
recognition for the native gray placement check at small scale changes and a
strict outlined-counter fallback. An unreadable resource counter now prevents
the confirmation input, even if the same counter was also unreadable in the
preceding menu. These fixes do not alter Home Village placement recognition.

Further current-UI checks found that Army Upgrades exposes a sorting-only
popup, not the building Resource/Type filters. Research inventory now verifies
that popup, closes it and returns to the first row before scanning. The Builder
row detector also retains long Star Laboratory titles; Home row thresholds stay
unchanged. Native wall previews whose red Cancel button touches a Barracks roof
use a separate inspected control variant. Recovery can cancel an unpaid preview
without confirming it.

The final unbuilt wall is displayed as `Wall`, without a multiplication suffix.
A short-title fallback requires the exact native word and four visible glyphs;
it cannot turn a dropped suffix into quantity one. Free-wall receipts need the
independent inventory decrement, including the final one-to-zero case. Unknown
new rows cannot prove the last wall disappeared.

An orphaned Builder payment journal also counts as a pending visit. Recovery
uses the existing receipt reconciler with execution disabled; it never sends the
payment again. From Home, it verifies the account and uses only an already-built
boat, with onboarding actions disabled. An uncertain receipt blocks new Builder
spending. If the screen has settled, the bot closes only recognized menus,
returns by boat, and independently verifies Home Village. It then pauses Builder
Base automation for that account while donations and other safe work continue.
The original receipt stays in `data/builder_base/upgrades.json`, alongside a
receipt- and account-specific `deferred_receipt` marker. A changed receipt or an
unfinished visit invalidates that marker. Unknown screens, held placements,
battles, and failed Home verification remain blocking.

Verification warnings appear in Activity and the normal log. Account-local
`data/verification/failures.json` keeps the latest 100 distinct failures, including
timestamps, repeat counts, feature, receipt and available evidence location.
Repeated observations update their record; warnings are rate limited. A deferred
receipt requires review before Builder Base automation resumes; restarting does
not erase it or repeat the purchase.

Green Builder wall quantities use additional native digit templates only for
wall counts, without lowering the shared digit-match threshold. A remaining
free-wall stack must show the exact one-wall decrement on two observations;
the final disappearing stack still requires a complete readable New inventory.

A live recovery check verified an existing 18-to-17 free-wall decrement without
repeating placement, with Gold, Elixir and gems unchanged. A separate supervised
failure check preserved the uncertain receipt, safely returned to clan chat and
released other account work. Later independent verification marked that logged
failure resolved while retaining its history.

The early Barbarian executor now normalizes the camera before reading placement
targets, like the existing Night Witch executor. It discards scouting coordinates
after zooming, stops if terrain cannot establish a target, and requires a troop
count decrement after each map tap. Recovery never repeats a possible deployment.

The inspected Daily Reward calendar can require claiming its free reward before
closing. Recognition checks its title, footer, and exact native controls; the
gray disabled X and red enabled X are distinct. Free claims have a bounded,
persistent intent. Purchase and inventory-conversion dialogs are not accepted by
this handler. A live check collected the required calendar reward and returned
to clan chat with the same gem balance.

A subsequent two-camp live test verified all six Barbarian deployments, observed
100% damage and 15,000 Builder Gold on results, then collected 41,003 Builder
Elixir and returned to clan chat. Gems stayed at 297. The placement reader checks
multiple positions along visible red edges and the inspected default/winter
terrain palettes; occupied or unknown patches are still rejected. These results
cover the tested compositions and arenas, not every scenery or Builder Hall.

The Star Laboratory payment dialog has an inspected title-art fallback because
OCR can misread its stylized lettering. Its price, resource icon, enabled payment
button, and close control are still checked independently on fresh observations.
The fallback is specific to that building and never supplies a missing price.
Live validation selected the laboratory ahead of an unbuilt Double Cannon,
started level 2, verified the builder changing from 1/1 to 0/1, and read the exact
46,140→31,140 Elixir deduction with gems unchanged at 297.
