# CoC Donation Bot

> **THIS CAN GET YOUR ACCOUNT PERMANENTLY BANNED.**
> Supercell’s [Safe and Fair Play policy](https://supercell.com/en/safe-and-fair-play/)
> prohibits bots and gameplay automation and states that offending accounts face
> permanent bans. Practice mode does not make live use permitted. This is an
> educational project, not an endorsed or safe way to play.

A Python app that uses Android screenshots to recognize screens and control
Clash of Clans through ADB. Built for Ubuntu and Waydroid.

- Clan donations with elixir verification, including open and specific requests.
- Optional unranked attacks using a deployment sequence you program.
- Guided calibration, saved profiles, activity logs, and screenshot collection.

## Install

You need Ubuntu or a similar Debian-based Linux system, an internet connection,
and permission to install packages. **Waydroid and Clash of Clans must already
be installed and working.** The bot installer does not install either one.

Open Terminal and paste these commands:

```bash
sudo apt update
sudo apt install git
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/MonkeyStud-lab/coc-donation-bot.git
cd coc-donation-bot
bash scripts/get_started.sh
```

The installer downloads the bot’s dependencies and unit icons, creates its
private Python environment, and opens the app. It may ask for your Linux
password; Terminal does not show characters while you type it. The first setup
can take several minutes.

Already downloaded the files? Open Terminal in the project folder and run
`bash scripts/get_started.sh`. You do not need to change script permissions.

## Connect and calibrate

1. **Open the game.** Start Waydroid and open Clash of Clans manually.
2. **Find your device address.** Run `waydroid status` in Terminal and look for
   its IP address while the session is running. In the app’s **Settings**, set
   **ADB device** to that address followed by `:5555`, then **Save Settings**.
3. **Connect.** On **Dashboard**, press **Connect ADB**. If needed, use Terminal:

   ```bash
   adb connect YOUR_IP:5555
   adb devices
   ```

   Replace `YOUR_IP` with the address from Waydroid. The device should appear
   with the word `device`, rather than `offline`.
4. **Open Setup.** Choose **Calibrate what's missing**. Follow each instruction
   in the app: open the requested game screen, capture it, and mark the button
   or screen area. Calibration happens in the app; no separate image editor is
   needed. To redo one part, select it and press **Recalibrate Selected**.
5. **Confirm elixir mode.** In **Setup → Donation panel**, calibrate both the
   elixir button and **Selected elixir indicator**. Open a donation request,
   select the left elixir button, and capture the entire selected button,
   including its border and background. The bot skips donations if it cannot
   confirm elixir is selected.
6. **Save a backup.** Use **Library → Saved calibrations → Save calibration backup** before experimenting.
   **Restore** brings back a saved calibration and its reference images.

Keep the bot stopped while calibrating. The in-app checklist shows missing
parts. Farming is optional and can be configured later.

## Use the app

To open it again:

```bash
cd ~/Projects/coc-donation-bot
bash scripts/get_started.sh
```

- **Dashboard:** Start, Stop, Farm attack now, connection controls, and activity.
- **Settings:** Donations, timing presets, farming, breaks, themes, and collection
  limits. Developer options expose individual timing values.
- **Setup:** Calibrate individual parts using the in-app instructions.
- **Library:** Review screenshots and save, restore, rename, or delete calibrations.
- **Diagnostics:** View a current screenshot, run a selected test or recovery action,
  create a desktop shortcut, or close the game and Waydroid.

**Stop** stops bot actions and leaves Clash of Clans open. It also works for a
standalone **Farm attack now** run. **Close Waydroid + Clash** closes the game
and Waydroid session. Farm and break countdowns pause while the bot is stopped.

After changing settings, save them. If the bot is running, use the offered
**Apply & restart** action, or Stop and Start it yourself.

For a clickable launcher, use **Diagnostics → Actions → Create desktop shortcut**. Open Waydroid
and Clash of Clans before starting the bot. If Ubuntu asks, choose **Allow Launching**
on the shortcut.

### Optional farming

1. In the game, select the army you want to use for unranked attacks.
2. In **Setup → Farm / unranked attack**, calibrate Attack!, the unranked button,
   and Return Home. Calibrate the search button if your interface has one.
3. Select **Deploy tap sequence** to program your army selection and deployment
   taps in order. Follow the editor’s instructions, including positioning the
   camera. The sequence determines which troops, heroes, and spells are used.
4. In **Settings**, enable farming and choose an interval, then save.
5. Use **Farm attack now** for a single run, or **Start** for scheduled operation.

Battle results are checked using consecutive screenshots. The timer remains
as a fallback. See [battle completion](docs/BATTLE_COMPLETION.md) for details.

## Update

Stop the bot and close its control window, then run:

```bash
cd ~/Projects/coc-donation-bot
git pull --ff-only
bash scripts/get_started.sh
```

The launcher checks whether installation work is needed. Saved GUI settings and
calibration are separate from the tracked defaults and normally survive updates.

If Git says local changes would be overwritten, **do not delete or reset them**.
Keep the error message and back up those files before resolving the conflict.
After a game interface update, back up your calibration and redo changed parts.

## Troubleshooting

- **No connected device:** Make sure Waydroid’s session is running. Check its IP
  address, reconnect, and confirm `adb devices` lists it as `device`.
- **Start is blocked:** Open Setup and finish the required calibration parts.
- **Donations are skipped:** Check the elixir button and selected-indicator
  calibration first, then the donation grids and slot colors.
- **Taps miss:** Recalibrate the affected part. A different resolution or game
  layout may need a different calibration even on the same computer.
- **Screenshot fails:** Stop the bot, check the ADB connection, and use the
  screenshot/health tests in Diagnostics. Restart Waydroid if needed.
- **Need help:** Use **Copy logs** or **Export debug** on Dashboard. Review exported
  files before sharing; they may contain game screenshots and device details.

## Documentation

- [Running, backups, and advanced setup](docs/RUNNING.md)
- [How the bot works](docs/HOW_IT_WORKS.md)
- [Reliability safeguards and tests](docs/RELIABILITY.md)
- [Useful screenshot collection](docs/SMART_COLLECTION.md)
- [Screen-recognition research](docs/PERCEPTION.md)
- [Contributing](docs/CONTRIBUTING.md)

## License and project policy

The code uses the [MIT License](LICENSE). Maintainers do not provide help with
detection evasion, paid botting, or account farming/selling. See the
[contribution policy](docs/CONTRIBUTING.md). This project is not affiliated with
Supercell.
