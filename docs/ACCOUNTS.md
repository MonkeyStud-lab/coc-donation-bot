# Accounts

Account management is available in the browser app's **Accounts** page. Only
one village runs at a time. Switching is user-initiated; this release does not
rotate between accounts on a schedule.

## Save your current village

1. Stop the bot and release Live view's manual control.
2. Open your own home village. Link it to Supercell ID in the game if needed.
3. Open **Accounts**, enter a nickname, choose roles, and press **Save loaded account**.

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
4. Give the account a nickname, choose its roles, and select **Save loaded account**.

Sign-in is required once per saved ID unless Supercell asks to authenticate
again. The bot does not store login codes or email credentials. Its screenshot
collector is stopped during this flow; account-navigation captures are not
added to the training library.

## Roles and settings

- **Donating** allows automatic donation scanning and filling.
- **Farming** allows scheduled attacks and Farm now.
- **Upgrading** allows Home Village building, research, and pet upgrades.
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

Start also verifies identity from the Home Village account menu. If a previous
run stopped in a battle or another screen that covers this menu, return home
through Live view before starting. Do not switch accounts directly in the game
while automation is running.
Recognized inactivity and Welcome Back notices may be dismissed before the tag
check. This does not bypass identity verification or authorize unknown dialogs.

Unknown screens, ambiguous names, missing/off-screen account cards, stopped
operations, and mismatched tags leave automation blocked. Use Live view to
finish loading the intended village, then **Verify current account**. For an
unfinished switch, this must be the selected destination account. For an
unfinished Add account, save the newly loaded village or verify a known village.
Duplicate village names may require renaming in the game before learning cards.

Managed-account automation must use the web app. Legacy desktop/CLI starts
without an account context are refused rather than applying the original
profile to a different loaded village.

## Storage and backups

The registry is `data/accounts/registry.json`. Additional profiles live under
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

`accounts/store.py` owns atomic metadata and profile isolation. `scope()` pins
the selected account through context variables; controller threads copy that
context. Roles mask configuration, and explicit farm/upgrade routes enforce
them too. Revisions include account identity to reject cross-account stale forms.

`accounts/navigation.py` uses inspected menu anchors and two independent tag
reads. Account setup runs under the existing device lease and cancellation
event. A pending transition is persisted before opening the switcher, so a crash
cannot silently resume automation on an unknown account. Startup verifies the
loaded account before recording or performing automatic actions.

`accounts/service.py` exposes controller jobs through the authenticated/CSRF
protected web API. No endpoint accepts login secrets or arbitrary ADB commands.
