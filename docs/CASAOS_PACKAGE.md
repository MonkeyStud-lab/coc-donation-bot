# CasaOS package

This package is under development. The bot image and existing-session pilot have
passed testing; installation on a clean host and unattended reboot are not yet
accepted. Do not replace a working installation until those checks pass.

## What the package does

CasaOS starts two services. The one-time setup service prepares the Linux host:
Waydroid, Android images, graphics/display prerequisites, a headless Wayland
session, and a small host helper. The ordinary bot service runs the dashboard,
ADB controls, and live video in a container. It does not get the Docker socket,
host filesystem, host D-Bus socket, or graphics devices.

The setup service explicitly requires host installation privileges. It mounts the
host root at `/host` and installs into it, then exits. The host helper exposes only
status/start/resume/stop and device ownership over a local Unix socket. Requests
cannot supply shell commands, package names, services, or file paths. The helper
must remain installed because Waydroid is a host runtime.

Initial target: x86-64 Ubuntu/Debian with systemd and working hardware graphics.
AMD/Intel graphics are the intended first target. Other GPUs, virtual machines,
ARM hosts, and alternative kernels require separate acceptance. Installation
stops on missing prerequisites; it never silently replaces the kernel.

## Data protection

- Host setup makes a dated ZIP backup before changes. It includes calibration,
  reference images, settings, runtime history, and default configuration, plus a
  SHA-256 manifest. Archives are verified and private.
- The package profile is separate from a previous checkout. Existing calibration
  is imported only into empty storage; it is never overwritten during seeding.
- Persistent profile: `/DATA/AppData/coc-bot/profile`.
- Installer backups: `/DATA/AppData/coc-bot/backups`.
- Waydroid's Android/account data remains on the host. Bot backups do not include
  the game account, Android private data, or account credentials.
- Image builds exclude live data, APK files, screenshots, and calibration. APKs
  are imported into private storage; they are not published in the image or repo.
- The bridge uses the same host `flock` as desktop/terminal bot runs. A second
  controller is rejected. Lease release is acknowledged before a restart.
- Calibration edits in the container and installer snapshots share a lock in the
  profile's data directory, even though their filesystem paths differ.

Keep an independent calibration backup on another device before migrating. Use
Library → import/restore to restore a portable calibration backup. Installer ZIPs
also include settings and use `data/` paths; they are full profile snapshots,
not the narrower Library calibration archive format.

## Build and install

Until a registry image is published, build from a checkout on Linux:

```bash
bash packaging/casaos/build.sh
```

In CasaOS, install a custom app and import `packaging/casaos/compose.yaml`.
The image name defaults to `coc-bot-casaos:local`. The dashboard uses port 8767
and discovers the host's LAN address. An address/origin override is available
for hosts with multiple network interfaces. Host networking also carries local
WebRTC video without a separate UDP port mapping.

The dashboard icon is the original blue shield/robot mark in
`web/public/casaos-icon.png`, also included in the web app at
`/casaos-icon.png`. `COC_ICON_URL` can override its URL when importing Compose;
for a locally built or private repository, use the dashboard address followed by
`/casaos-icon.png` so CasaOS can load it without GitHub access.

CasaOS installation itself is a prerequisite for a CasaOS app; this package does
not install or replace CasaOS. The setup container installs Waydroid automatically
on supported hosts. Its administrator-level access is visible in the Compose
definition and should be reviewed before installing.

For an existing Waydroid desktop session, set `COC_ADOPT_USER` and optionally
`COC_WAYLAND_DISPLAY` on the setup service. That mode retains the existing desktop
display and Android installation. It does not promise startup before that
desktop user's Wayland session is available. It can reopen a closed Android
session once that display is available. New installations use the dedicated
headless display instead. Neither mode changes an existing Android resolution.

An operator can also run the same host installer explicitly:

```bash
sudo python3 packaging/casaos/install_host.py
```

Use `--dry-run` for a read-only compatibility report. `--import-from /path/to/old/bot`
backs up and copies a previous profile into empty package storage. `--adopt-user`
retains an existing session. After host setup, `COC_SKIP_HOST_SETUP=1` skips the
setup container when testing or when setup was already performed separately.

The manually triggered GitHub workflow `CasaOS container image` builds Linux
amd64 images and publishes versioned and `casaos` tags to GHCR. Publishing and
registry installation have not yet been verified. Public images contain no game
APKs, account information, or user calibration.

## Install Clash without Google sign-in

Export APK files from an Android instance where Clash is already installed:

```bash
python3 scripts/export_clash_apks.py --device ANDROID_IP:5555 --output clash-apks.zip
```

This copies installation files only, including split APKs. It does not copy the
account. Open the package dashboard and use **Import Clash APK archive** when
prompted. The app validates every APK's package name before installation. Then
open **Live view → Take control** and sign into the game yourself. Never send
account passwords or login codes to the bot or the host helper.

Clash must be compatible with the selected Android/CPU. An ARM-only APK set may
need translation components not supplied by this initial package; a failed
compatibility check is not an invitation to alter game integrity protections.
Updated APKs may need to be imported when the game requires an update.

Fresh accounts/screens still need the existing guided Setup calibration before
automation can start. Universal automatic calibration is not implemented by this
package. Imported calibrations need matching screenshot dimensions and layout.
Farming also requires the user's army-specific deploy sequence. Installation and
runtime startup are automated; these gameplay assumptions must not be guessed.

## Startup and controls

The dashboard starts independently of Android readiness. It displays startup
progress or a specific error, with Retry. The runtime helper starts/reuses the
session; ADB connects; Clash is installed if absent and APK files are available;
the game launches; screenshot health is checked. Automation remains stopped.

**Stop** cancels bot/tool actions and leaves the game open. **Close Waydroid and
Clash** explicitly closes the session. Stopping the CasaOS bot container does not
delete Android data or uninstall Waydroid. Closing a browser tab does not stop
automation. Live view wake/recovery uses the helper through narrow command shims.

Do not run the previous bot service and package concurrently. Locks prevent
simultaneous control, but a paused desktop bot should be disabled deliberately
at final migration. Do not uninstall the fallback until migration acceptance.

## Acceptance still required

1. Clean supported host: setup from no Waydroid installation and no calibration.
2. GPU-backed headless Android surface, Clash installation and account sign-in.
3. Reboot with no desktop login; CasaOS starts the dashboard and Android.
4. Game update/import, network loss, frozen payload, repeated Stop/Retry.
5. CasaOS GUI import, health status, update and rollback.
6. Calibration/template checksum preservation and restore to the fallback.
7. A supervised donation and farm using an explicitly prepared test profile.

Existing-session testing alone does not prove clean-host or headless compatibility.
The production host cannot finish administrator installation unattended while
sudo requires interactive authentication.

## Current verification

The development image built on Ubuntu and passed 84 offline regression tests
inside its own container. An existing-session pilot launched Clash at the
original screen dimensions, produced decoded browser video, and validated all
five APK splits from the installed game. The full large archive upload endpoint
also passed; it did not replace the already-installed game or start automation.

The administrator-installed helper passed ownership tests against the original
desktop controller in both directions. The Linux root/user `/tmp` lock protection
case is covered by a container regression test. The original bot service is
retained as a fallback; evaluation profiles and imported APKs are separate.

The closed-session acceptance test exposed stale `Session: RUNNING` metadata
after Android shutdown. The helper now treats a stopped payload with an
unresponsive Android check as needing startup, rather than failing status on a
timeout. The package regression suite passed after this correction. Installing
this correction succeeded. The adopted host also had stale container-manager
tracking and a stale ADB transport. Restarting its container manager and cleanly
stopping the retained Android session cleared the host condition. Package
startup now refreshes only its own ADB transport while holding the device lease.
The deployed package subsequently passed a complete close/reopen cycle:
Waydroid stopped, automatically reopened, launched Clash, and captured a frame
at the original resolution. Automation remained stopped throughout.

CasaOS app management subsequently accepted the existing-host configuration and
listed the app as running with its dashboard URL. That registration includes
only the bot service: host installation was already completed, so its privileged
setup service was removed. The local development image uses `pull_policy: never`
because it has not been published to a registry. A calibration backup was taken
before registration, and both original and imported calibration hashes remained
unchanged afterward. The CasaOS dashboard tile itself still requires a signed-in
visual check; app-management registration does not verify a fresh installation.

After a helper code update, stop automation and release manual control, then run
`sudo python3 packaging/casaos/install_host.py --refresh-helper`. This takes a
backup, checks that the Android device is unowned, and refreshes only the helper.
It does not reinstall packages, reset Android, or change calibration. Directory
preservation prevents container socket mounts becoming stale during restart.

These checks do not satisfy the clean-host, headless reboot, or CasaOS GUI gates
listed above. Do not describe this as a universally compatible one-click release.

## Updating Clash

Once a trusted copy of Clash is installed, CasaOS checks for updates each time
its managed runtime starts. To check immediately, stop the bot and close manual
control, then choose **Diagnostics → Update Clash**. Download progress appears
in the dashboard. Automation stays stopped; start it again after checking the
updated game's layout.

The source is APKPure's direct HTTPS endpoint:
`https://d.apkpure.net/b/APK/com.supercell.clashofclans?version=latest`.
APKPure is a third-party distributor, not Supercell. Supercell's official Android
download links use Google Play. APKMirror also publishes releases and describes
its signature checks, but its multi-page download flow is not the integration
used here. No Google login is added.

Before installation the updater verifies the actual APK signature with
`apksigner`, compares its SHA-256 certificate identity with the installed base
APK, checks the package name and a strictly newer version code, and refuses
split-only downloads. Android additionally verifies the in-place update.
Signature rotation to a different certificate is deliberately rejected and
requires manual review. A fresh installation still requires a trusted APK
archive; this download endpoint cannot establish the initial trusted signer.

Calibration is backed up before an update. The previous installed APK set is
retained in `data/game-update-backup` (one previous version); account data is
never cleared and the game is never uninstalled. These APK copies are not a
backup of Android account data and automatic downgrade/rollback is not attempted.
Downloads are capped at 2 GB and require 6 GB free staging space. Downloads have
timeouts and cancellation checks. Only the HTTPS source host and its observed
`data.winudf.com` CDN are allowed; unexpected redirects fail closed. An unavailable
source leaves startup usable with the existing game and reports the failed check.
An explicit update failure is shown as a runtime error; Retry startup can reopen
the existing game. Updates never run periodically during gameplay.

Set container environment `COC_AUTO_UPDATE_GAME=0` to disable startup checks;
the Diagnostics button still works. Existing CasaOS installations need the new
container image to gain this feature. ZIP import remains the fallback if the
provider changes its endpoint or stops publishing compatible standalone APKs.

Waydroid may keep an APK temporarily frozen during installation. The updater
uses non-streamed ADB installation and checks the committed version even when
ADB loses its final response. Runtime readiness still requires Clash to stay
running. If Waydroid reports `Session: RUNNING` with `Container: STOPPED`, a host
administrator may need to run `sudo systemctl restart waydroid-container.service`,
then choose Retry startup in the dashboard. Do not uninstall Clash or reset
Android to resolve this condition; both would risk losing account data.

Sources: [Supercell](https://supercell.com/en/games/clashofclans/),
[APKPure](https://apkpure.net/p/com.supercell.clashofclans),
[APKMirror FAQ](https://www.apkmirror.com/faq/).
