# Game UI compatibility

The October 2026 update renamed the home Attack! control to **Battle** and
added a **Find a Match** button on the left Battle card of the Multiplayer menu,
followed by a **My Army** confirmation page with a green **Attack!** button. The right Ranked Battle card is
not the farming route.

`vision/battle_menu.py` identifies the left gold button geometrically, then
requires readable **Multiplayer** and **Find a Match** labels. It isolates white
lettering from the bright gold fill before OCR. Color alone cannot start search.
Coordinates come from the current screenshot and scale with its dimensions.
The classifier treats this strong menu evidence before weaker battlefield
heuristics, which previously misclassified the new menu as a live battle.

The new clan-war card can also resemble the old Live Replay color heuristic
while chat is open just after relaunch. Readable **Build** lettering on the gold
village control now vetoes that replay interpretation. Actual replay screens do
not have this control. The attack navigator additionally rejects recognized
clan chat and donation panels before using legacy green-button menu heuristics.
Verified Multiplayer menu anchors also rule out Surrender dialogs; the new
menu's card artwork otherwise falls into the old orange/green dialog regions.

`AttackNavigator.start_unranked_battle()` taps the verified left button
once. During the wait, readable **My Army**, **Cookbook**, and **Attack!** labels
authorize the army confirmation tap. It does not blindly send the old second-screen tap. Calibration records
`farm_direct_search: true` when the user calibrates this menu, so that an
unavailable OCR read still cannot reactivate a blind second tap. Older
calibrations default to the legacy flow; recalibrating the unranked button on an
older menu resets this metadata. It is calibration data, not a timing setting.

## Setup after updating the game

1. Save a calibration backup in Library before changing any selections.
2. On home with chat closed, calibrate **Open chat** using the speech bubble,
   and **Battle button** using the large bottom-left gold control.
3. Press Battle manually. On the Multiplayer tab, calibrate **Unranked Find a
   Match** using the left card's button. Keep the menu open; calibration itself
   does not start matchmaking.
4. Skip **Second search button (older UI)** on the current layout.
5. Use Diagnostics to inspect request recognition, the donation panel, and
   elixir selection before enabling donations. Recalibrate only affected areas.
6. Test the selected attack method and Return Home in a supervised unranked
   attack if battlefield/results layout changed. Sequence mode needs its recorded
   taps checked; automatic/planner modes need current card and boundary evidence,
   not a new fixed tap recipe.

The existing-host compatibility pass inspected real home, clan chat, global
chat, Multiplayer menu, and specific-request donation screenshots. It verified
the global-to-clan tab, Donate text, the panel classification, elixir selection,
and four colored troop slots plus a Recall spell. No troop donations, matchmaking,
or deployments were triggered during this inspection. It therefore does not
claim an end-to-end attack test or coverage of every donation capacity/layout.
The deployed navigation check opened the Battle menu, closed it, recognized
home, and reopened clan chat while the post-relaunch replay watch was armed.

Screenshots stay in private profile/debug storage, outside Git. Regression tests
use synthetic button frames and mocked input to cover label verification,
resolution scaling, one-tap unranked selection, army confirmation, legacy search, Stop, and menu
classification. For the next update, compare private screenshots against these
anchors before changing broad color thresholds or overwriting calibration.

Live monitoring subsequently exposed the extra army confirmation step: the old
weak battlefield heuristic accepted My Army and sent deploy taps into Cookbook.
Before deploying, **End Battle** (or **Surrender**) and either **Next** or the
battle countdown heading must be readable on the opponent screen. The OCR
spelling `End Battie` is accepted only with the second anchor. The same gate applies to timeout recovery and a fresh
frame immediately before deployment; generic BATTLE classification is insufficient.
Missing OCR fails closed. Calibration and the programmed tap sequence are preserved.

Full-screen resource rewards can appear after Return Home. Recognition covers
Gold, Elixir, Dark Elixir, Capital Gold, Raid Medals, Gems, Builder Gold and
Builder Elixir. The warm brown reward hall on both sides, a supported title,
green button, and readable **Continue** label are checked together before a tap.
Long resource titles tolerate one substituted OCR letter (the observed Dark
Elixir title read `ddrkelixir`); unrelated titles and generic green buttons fail.
Both donation startup and attack-return recovery dismiss this page before
attempting to open clan chat; it must not be classified as the home village.
The inner home-confirmation loop checks each fresh frame too, allowing successive
resource reveals to clear without repeatedly tapping the clan-chat coordinates.
Unknown reward names or a different backdrop need a new inspected screenshot.

## Live validation October 14, 2026

This section records that release's inspected game version and test outcomes.
Subsequent results-detector and camera refinements are covered in
[battle completion](BATTLE_COMPLETION.md), [attacks](ATTACK_REBUILD.md), and
[current status](WEB_UI_MIGRATION_STATUS.md). The fallback used in the test below
is not the normal completion behavior of every later attack.

The supervised repeat recognized My Army, pressed its Attack button, verified
the opponent controls, and replayed the existing 33-tap sequence. Screenshots
confirmed all 11 Electro Dragons deployed, the siege and heroes on the map,
and all five Rage spells used. Return Home used the 200-second timer fallback;
the fixed results-label detector did not confirm the updated result layout.
A Capital Gold reward initially blocked clan chat. After adding its specific
Continue detector, the controlled recovery dismissed it and opened clan chat.

A subsequent live donation donated six requested troops, including three Super
Minions, and one Recall spell to a specific request. The request started at 0/50 troop
capacity, 1/3 spell capacity and 1/1 siege capacity; the first four troop taps
visibly advanced it to 26/50. The remaining two Super Minions and Recall spell were
then donated, the fulfilled request disappeared, and the bot resumed scanning
clan chat. The gem balance stayed at 403. All 117 regression tests passed.
This verifies the observed request layout, not every possible capacity/scenery.
