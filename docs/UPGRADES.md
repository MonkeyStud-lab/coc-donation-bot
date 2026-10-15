# Suggested upgrades

The browser app can check the game's **Build** menu and start eligible building
upgrades or laboratory research in its **Suggested upgrades** order. Automatic
upgrades are off by default. This is an initial implementation for the inspected
English, landscape game interface; an unreadable or changed screen blocks spending.

## Try a recommendation

1. Stop the bot and close manual game controls.
2. Open **Diagnostics** in the browser dashboard.
3. Under **Building upgrades** or **Army research**, press **Check upgrades**.
   The app opens the Build menu, reads the recommendations, and returns to chat.
   Checking does not buy or start anything.
4. Read the displayed cost and any reasons for skipping an entry.
5. To start the displayed recommendation, press **Start recommended** and review
   the confirmation. The app checks the recommendation and resources again before
   pressing the game's resource confirmation button.

The desktop interface does not include these new preview controls. Use the browser
dashboard for this feature.

## Automatic checks

Open **Settings → Upgrades**. Enable building upgrades, research, or both, and
save. Start the bot normally. It checks between donation rounds, after the farming
priority check, and gives a visible donation request priority. Each check can start
at most one upgrade per enabled category. Practice mode does not run automatic
upgrades; the manual Diagnostics action is a separate spending action.

The initial settings are:

- Check every 900 seconds while running.
- Keep one builder free.
- Keep at least 1,000,000 gold, 2,000,000 elixir, and 50,000 dark elixir.
- Additional exclusions accept building or troop names separated by commas.

The reserve is the minimum balance **after** paying for an upgrade. It is a floor,
not a daily budget. Availability, price, resource type, and remaining balance all
have to pass before an upgrade starts. A busy laboratory is skipped. A building
needs more free builders than the number reserved. The app skips excluded or
unaffordable Suggested entries; it does not choose from **Other upgrades**.

## What is excluded

The first version does not buy new buildings, upgrade the Town Hall, upgrade heroes
or walls, manage equipment or pets, or upgrade the Laboratory, Barracks, spell
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

## Stops, interruptions, and uncertain results

**Stop** interrupts previewing, navigation, and waiting. A resource press already
sent to Android cannot be undone. Before that press, the app saves an intent in
`data/upgrades/state.json` inside the active profile. A new matching progress row
and a decrease in free builder/research slots confirm that it started.

If verification fails or the app restarts after the press, it retains that pending
intent and blocks another spending attempt. It can reconcile the pending entry
when the corresponding running upgrade and slot usage become visible. It never
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
`buildings` or `research`. `POST /api/upgrades/start` also requires the token from
the displayed preview. Both use the normal session, origin, and CSRF protections,
and return their final report through `/api/status`. A token identifies the
recommendation; fresh game checks still determine whether it can be started.

Offline coverage lives in `tests/test_upgrades.py` and the web integration tests.
Use disposable profiles for tests. Never run tests against a live calibration or
allow a test fixture to send ADB taps.
