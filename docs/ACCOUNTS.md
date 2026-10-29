# Accounts

Account management is available in the browser app's **Accounts** page. Only
one village runs at a time. Switch manually while stopped, or enable
**Automatic account visits** and choose a main account with the Donating role.

Automatic visits return to the main donor between every secondary account.
The donor normally has a 15-minute watch window between secondary visits.
Secondary accounts are checked in oldest-visit order, no more often than every
30 minutes. Visits have no three-minute cutoff: they finish their saved
resource/upgrade checklist. Battles and payments finish before switching.
Blocked checks are recorded with a retry delay; they do not certify completion.

Each visit runs only that account's enabled features and roles. Stop freezes
the rotation's account-check due times. The coordinator holds one device lease
across handoffs, verifies the reloaded player tag, and pins each account's
settings and transaction files separately. An unresolved action blocks a
handoff. Unknown login/tutorial screens still require review.

Loading an account can reveal a completed defense summary or the mandatory
Daily Reward calendar. The bot uses independently recognized native controls
to return to the village or collect its free calendar reward. Purchase and
inventory-conversion dialogs remain blocked. These navigation steps never prove
which account loaded: the independent Profile and Settings tag checks still
have to pass before automation resumes.

Each visit refills Home resources, checks normal Clan Castle requests, checks
Home buildings/Laboratory/pets, then visits Builder Base if enabled. Optional
layouts retain their existing opt-in/recovery rules. Home refill starts below
75% and continues to 95% by default; both percentages are adjustable. Builder
Base uses the same targets with its own balances and capacities, then checks
its builders and Laboratory. Locked or disabled features are skipped.

The same saved checklist runs with a single account and with account rotation.
The cursor survives Stop, restart and donation detours. A successful attack
returns to a resource check, not an interval countdown. Three unproductive
attacks pause refill for 15 minutes and let other checks run. Unreadable resource
observations never authorize attacks. Legacy farm interval values are ignored.

## Save your current village

1. Stop the bot and release Live view's manual control.
2. Open your own home village. Link it to Supercell ID in the game if needed.
3. Open **Accounts**, enter a nickname, choose roles, and press **Save and verify account**.

Saving performs verification automatically; you do not need a separate check. Nicknames are optional and default to the village name.

The first account keeps the installation's existing settings, calibration,
timers, and histories. A checksum-verified backup is created before registration.
The bot reads the player tag independently in My Profile and Settings. It then
learns the saved-account card and reloads that card to verify the association.
Names help locate a card; the player tag decides whether it is the right account.

## Add another account

1. Stop the bot, then choose **Accounts → Add account**.
2. Open **Live view → Take control**. In the game's chooser, select
   **Log in to Supercell ID** and complete the game's sign-in. Enter email and
   verification codes directly in the game, never into bot settings.
3. When the village loads, dismiss welcome notices and release manual control.
4. Give the account a nickname, choose its roles, and select **Save and verify account**.

Sign-in is required once per saved ID unless Supercell asks to authenticate
again. The bot does not store login codes or email credentials. Its screenshot
collector is stopped during this flow; account-navigation captures are not
added to the training library.

## Roles and settings

- **Donating** allows automatic donation scanning and filling.
- **Farming** allows resource-driven attacks and Farm now.
- **Upgrading** allows Home Village building, research, pet upgrades, and enabled
  automatic defensive layouts.
- **Builder Base** allows its configured visits, collection, attacks, and upgrades.

An account can have several roles or none. A role grants permission; its
individual features must also be enabled in Settings. No roles means automation
cannot start. New accounts start with schedules disabled and no automatic roles.

Settings, timers, calibration, saved routines, and upgrade histories belong to
the selected account. Device recognition is copied as an initial starting point,
but another account's deployment sequence and transaction history are not.
Review calibration and enabled features for each village, especially low Town
Halls with locked features, missing clan access, or tutorial prompts. Registering
a low-level village does not certify unattended progression through Town Halls.
For the opt-in starter-account workflow, see [Home Village progression](HOME_PROGRESSION.md).

## Switch and recover

Stop automation, release manual control, and press **Switch** on an account.
The bot opens the saved-ID chooser and selects its learned card. After the
village loads, it checks the player tag again. It stays stopped; press Start
when you are ready to run that account's enabled tasks.

An ordinary Start verifies identity from the Home Village account menu. During
continuous rotation, the just-completed switch can hand its verification to the
next worker once, within 30 seconds, on the same thread, device, profile and
still-held device lease. A fresh Home/clan-chat screenshot is still required.
Expired proofs, restarts, changed screens and interrupted layout recovery use
the full Profile/Settings check again. These proofs are never saved to disk.
If a previous
run stopped in a battle or another screen that covers this menu, return home
through Live view before starting. Do not switch accounts directly in the game
while automation is running.
Recognized inactivity and Welcome Back notices may be dismissed before the tag
check. This does not bypass identity verification or authorize unknown dialogs.
An interrupted Build, Research, or Pets sidebar can be closed after its exact
heading and bright close control match on two fresh frames. The bot then verifies
the ordinary Home Village anchors before opening the account menu.

Adding an account scans the full chooser through bounded overlapping pages.
Routine switches first inspect the current stable viewport and search further
only when needed. Card positions are reacquired after scrolling. Identical
chooser pixels can share name OCR within one operation; player-tag reads are
independent and are not served from that cache.
Names only nominate a card; two-screen tag verification still establishes
identity. Distinct Supercell ID names are required.

Activity logs include chooser selection, game loading and identity-verification
timings for switches, plus capture/cache counts for diagnosis.

Unknown screens, ambiguous names, missing account cards, stopped
operations, and mismatched tags leave automation blocked. Use Live view to
finish loading the intended village, then **Check loaded account**. An unfinished
switch instead shows **Finish switch**. It reloads the recorded destination and
verifies that village, including when the previous attempt stopped before its
card was tapped. The drawer must finish closing before avatar/menu input is
allowed; a brief closing animation no longer immediately fails the switch.
For an unfinished Add account, use **Save and verify account** for the new village;
it performs verification as part of saving. The recovery option below that form
can confirm a village that was already saved in the app.
Duplicate village names may require renaming in the game before learning cards.

Managed-account automation must use the web app. Legacy desktop/CLI starts
without an account context are refused rather than applying the original
profile to a different loaded village.

## Storage and backups

The registry is `data/accounts/registry.json`; rotation settings and per-account
due times are in `data/accounts/rotation.json`. Additional profiles live under
`data/accounts/profiles/<id>/`. The original profile remains in the installation
root. Account registration backups are in `data/account_backups/<timestamp>/`,
with a SHA-256 manifest. These folders are ignored by Git.
Account snapshots also preserve learned progression troop portraits and the last
prepared army, so restoring settings does not discard those verified identities.

Back up the entire persistent profile volume to preserve all accounts and their
settings. Library calibration backups cover the currently selected profile,
not every account or Android's saved logins. Account tags and nicknames are
personal data; review exports before sharing them.

## Developer notes

Non-donating accounts at Town Hall 3 or above check their Clan Castle during
rotation visits. Two fresh My Army readings must agree that its contents are
empty before the bot opens the normal request dialog. It preserves the saved
request text and troop preferences. Gem cooldown resets and raid-medal purchases
are never used. Accounts without a rebuilt Clan Castle or an available request
button are skipped. Checks are persisted per account; a sent or uncertain request
has a twenty-minute retry delay, and the game's own cooldown must also be clear.

Request checks share the saved visit checklist with upgrades, farming, Builder
Base, and optional layouts. They do not replace the main donor's watch windows.

`accounts/store.py` owns atomic metadata and profile isolation. `scope()` pins
the selected account through context variables; controller threads copy that
context. Roles mask configuration, and explicit farm/upgrade routes enforce
them too. Revisions include account identity to reject cross-account stale forms.

`accounts/navigation.py` uses inspected menu anchors and two independent tag
reads, with two fresh readings on each screen. Every visible tag character must
be accounted for; shortened OCR output cannot verify an account. Account setup
runs under the existing device lease and cancellation
event. A pending transition is persisted before opening the switcher, so a crash
cannot silently resume automation on an unknown account. Startup verifies the
loaded account before recording or performing automatic actions.

The embedded hero viewer consumes drag gestures. When a Profile remembers a
scrolled position, navigation finds a visible flat native page strip outside
that viewer and checks the same strip on a fresh frame before scrolling. It
waits for scroll inertia rather than reusing a stale point. Unreadable tags still
stop verification; expected account tags never fill in missing OCR characters.

`accounts/service.py` exposes controller jobs through the authenticated/CSRF
protected web API. No endpoint accepts login secrets or arbitrary ADB commands.

Between checklist steps (including individual attacks and bounded Builder Base
batches), and before a scheduled switch, the bot checks verified clan chat.
A completed or recovered Home attack explicitly queues this check before the
next refill battle, including manual attacks. The check follows a visible
request-jump icon once and reads a fresh frame, so an old chat scroll position
does not hide a request. Activity logs show the between-attack check and outcome.
A visible request detours to a randomly selected Donating-role account in the
same clan. Membership is learned from two fresh native My Clan tag reads;
names do not establish membership. Unknown/stale clan identities are excluded,
and the destination's membership is rechecked before donating. Its verified clan
tag is shown in Accounts. A changed clan cancels the detour. The interrupted
account's cursor and rotation destination are restored afterward. Detours are bounded to
three minutes and have a three-minute retry delay to avoid looping on requests
that cannot be filled. Battles and unresolved upgrade payments still block switching.
