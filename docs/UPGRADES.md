# Automatic upgrades

The browser app can check the game's **Build** menu and start eligible building
upgrades or laboratory research in its **Suggested upgrades** order. It can also
upgrade eligible pets from the **Hero Pets** tab, preferring unassigned pets.
Automatic
upgrades are off by default. This is an initial implementation for the inspected
English, landscape game interface; an unreadable or changed screen blocks spending.

**Village progression** is a separate opt-in mode. It scans the complete building
list, builds new structures first, prioritizes offensive capacity, handles walls,
and gates Town Hall upgrades on verified completion of the other available
buildings. Its Laboratory ordering favors the prepared farming army. The
Suggested-only rules below describe the normal mode; see
[Home Village progression](HOME_PROGRESSION.md) for the new mode and its limits.

## Try a recommendation

1. Stop the bot and close manual game controls.
2. Open **Diagnostics** in the browser dashboard.
3. Under **Building upgrades**, **Army research**, or **Pet upgrades**, press **Check upgrades**.
   The app opens the Build menu, reads the recommendations, and returns to chat.
   Checking does not buy or start anything.
4. Read the displayed cost and any reasons for skipping an entry.
5. To start the displayed recommendation, press **Start recommended upgrade** and review
   the confirmation. The app checks the recommendation and resources again before
   pressing the game's resource confirmation button.

The desktop interface does not include these new preview controls. Use the browser
dashboard for this feature.

Verified availability and spending are distinct. A Suggested row can be visible
with no free builder/laboratory slot; it is not authorization to start. Successful
execution requires observed progress and slot usage, not merely an issued tap.
See [current validation status](WEB_UI_MIGRATION_STATUS.md) for dated evidence.

## Automatic checks

Open **Settings → Upgrades**. Enable building upgrades, research, pet upgrades, or any combination, and
Save while stopped, or Save & restart during normal operation. The latter waits
for the current action; Stop cancels the pending settings restart. Start the bot
normally when stopped. It checks between donation rounds, after the farming
priority check, and gives a visible donation request priority. Saved visits check
builders before refill and perform one transaction before the next verified chat
checkpoint. Remaining research/pet/building checks survive donation detours.
Practice mode does not run automatic
upgrades; the manual Diagnostics action is a separate spending action.

The initial settings are:

- Check every 900 seconds while running.
- Use every available builder.
- Keep no additional gold/elixir/dark-elixir reserve by default. Optional reserve
  overrides are under **Advanced**, separately from farming's start/target percentages.
- Additional exclusions accept building, troop, spell or pet names separated by commas.

The reserve is the minimum balance **after** paying for an upgrade. It is a floor,
not a daily budget. Availability, price, resource type, and remaining balance all
have to pass before an upgrade starts. A busy laboratory is skipped. A building
needs more free builders than the number reserved. The normal building method
skips excluded or unaffordable Suggested entries. Village progression and
its farming-priority research also inspect **Other upgrades**.

List searches stop when the visible list no longer moves, rather than spending
the full swipe limit at the bottom. A complete progression inventory requires
stationary list text after both a normal swipe and a short confirmation swipe,
then reads the final settled rows. Animated thumbnails and timers are excluded
from the motion check. Blank or changed menus cannot certify completion.

An unpaid construction/confirmation failure gets a five-minute candidate retry
delay, allowing other verified buildings to use free builders. The failed row
still blocks Town Hall progression. A pending payment is never skipped this way.
Discounted confirmations read the current green price separately from the
red-struck original price; two fresh confirmations must still agree with the
selected name, currency, and price. Account cards show the last check and its
reason, rather than claiming that all builders are currently busy.

Each resource reserve accepts values from 0 to 100,000,000 in both the browser
and desktop settings. Builder reservations range from 0 to 6, and the check
interval ranges from 60 to 86,400 seconds.

## Pet upgrades

Enable **Automatic pet upgrades** in Settings. The app verifies the **Hero Pets**
tab and its separate pet-upgrade counter; spare builders or a free laboratory do
not establish pet availability. It reads known pet names and dark-elixir prices,
keeps the same dark-elixir reserve, and starts at most one pet upgrade per check.
Locked pets, missing prices, unreadable names, and a busy pet slot are skipped.

Pets have **Assigned** and **Unassigned** sections rather than a Suggested list.
By default only unassigned pets are eligible, in displayed order. **Allow upgrades
of equipped pets** is a separate opt-in; unassigned pets visible in the list are
still preferred. Upgrading an equipped pet may make it unavailable for attacks.
Pet House building upgrades remain excluded. A pet-upgrade operation never
changes hero assignments, spends gems, or uses a hammer/book to finish instantly.

Live validation on 2026-10-22 started an unassigned L.A.S.S.I upgrade for 60,000
dark elixir. The balance decreased by that amount, gems stayed unchanged, and
the pet counter changed from 1/1 to 0/1 with a matching active timer. Recovery
also verified that timer and cleared the pending journal without another
purchase. This validates the inspected English landscape interface; other
layouts and future game changes still need testing.

## What is excluded

Without Village progression, the app does not buy new buildings, upgrade the Town Hall, upgrade heroes
or walls, manage equipment, or upgrade the Laboratory, Barracks, spell
factories, Workshop, Hero Hall, or Pet House. Building names must match an explicit
supported list. Laboratory research must appear in the verified Army upgrades tab.
Unknown layouts, incomplete Suggested sections, unreadable numbers, and resource
shortfalls cause a skip rather than a guessed purchase.
If scenery shows through a partly empty resource bar, its balance may be unreadable;
upgrades using that resource are skipped until it can be verified.

The runner only targets a green resource confirmation whose name, price, and
currency agree with the recommendation on two fresh screenshots. It never
authorizes gems, missing-resource purchases, books, hammers, or potions. These
checks reduce mistakes; they cannot guarantee compatibility with future game
changes. Test a preview after a game update before enabling automatic checks.

Confirmation prices use both the original text and a contrast-isolated version
with the same strict digit thresholds. This handles shading on green buttons
without guessing a missing leading digit. Conflicting readable amounts block
the purchase, even if one matches the recommended price.

Live validation on 2026-10-22 started a Builder's Hut level-5 upgrade for
7,000,000 gold. Gold changed from 24,500,000 to 17,500,000, gems stayed at 698,
and free builders changed from 1/5 to 0/5. The active-name count increased from
one Builder's Hut to two, and the runner confirmed its journal without a retry.

## Stops, interruptions, and uncertain results

**Stop** interrupts previewing, navigation, and waiting. A resource press already
sent to Android cannot be undone. Before that press, the app saves an intent in
`data/upgrades/state.json` inside the active profile. A new matching progress row
and a decrease in the corresponding free builder, research or pet slot confirm that it started.

If verification fails or the app restarts after the press, it retains that pending
intent and blocks another spending attempt. It can reconcile the pending entry
when the corresponding running upgrade and slot usage become visible. It checks
the pending entry's building, research or pet tab first, even when the next requested
check is for the other category or the pending category's automation is off.
This recovery check only verifies the earlier attempt; it does not repeat its
purchase or enable that category's automation. It never
silently resets a damaged journal. If the upgrade finishes before reconciliation,
manual inspection may be needed; there is deliberately no automatic retry or
"clear and buy again" button.

Do not delete the journal to make the app retry without first checking the game.
Keep the journal and activity logs when reporting a problem. Calibration, settings,
and game data remain separate; this feature does not rewrite calibration.

## Development

`coc_bot.upgrades.vision` reads menu headings, Suggested rows, resource icons,
availability, and confirmation controls. `digits.py` uses bundled glyph references
and rejects ambiguous numbers; it does not fall back to an uncertain OCR amount.
`policy.py` decides eligibility without tapping. `runner.py` handles fresh-frame
checks, durable intent, resource confirmation, and reconciliation. The shared
control service and device lease prevent simultaneous upgrade, farm, calibration,
and manual-control jobs.

The browser API provides `POST /api/upgrades/preview` with `kind` set to
`buildings`, `research` or `pets`. `POST /api/upgrades/start` also requires the token from
the displayed preview. Both use the normal session, origin, and CSRF protections,
and return their final report through `/api/status`. A token identifies the
recommendation; fresh game checks still determine whether it can be started.

Offline coverage lives in `tests/test_upgrades.py` and the web integration tests.
Use disposable profiles for tests. Never run tests against a live calibration or
allow a test fixture to send ADB taps.
