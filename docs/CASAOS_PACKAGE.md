# CasaOS package

CasaOS runs the browser dashboard in a container while Waydroid remains on the
Linux host. The package is in use on an existing Ubuntu/Waydroid installation.
Clean-host/headless installation and unattended reboot still need dedicated
acceptance; this is not a universally tested one-click appliance.

See the [README](../README.md) for the quick start and
[verification and limits](#verification-and-remaining-limits) before migrating.

## What runs where

The Compose file has two services:

- **setup:** one-time administrator-level host preparation. It mounts the host
  root and installs supported Waydroid/Android images, display prerequisites,
  headless session units when applicable, and a small runtime helper, then exits.
- **bot:** the ordinary browser/ADB/video app, running as user 1000:1000 with a
  read-only root filesystem, temporary `/tmp`, dropped capabilities, and private
  profile storage. It has no Docker socket, host root, host D-Bus, or graphics
  device mounts.

The system helper exposes allowlisted status/start/resume/stop/device-ownership
operations over a local Unix socket. Requests cannot supply shell commands,
package names, host paths, or arbitrary service actions. A code-only bot update
does not replace that separately installed helper.

The initial target is x86-64 Ubuntu/Debian with systemd, compatible binder support,
and working hardware graphics, initially AMD/Intel. CasaOS and Docker are
prerequisites. Other GPUs, VMs, ARM, and alternative kernels need separate
validation. The installer checks compatibility and does not silently replace
the kernel. ARM-only game packages may require translation not supplied here.

## Data protection

Persistent locations:

- `/DATA/AppData/coc-bot/profile`: the bot profile, mounted as `/profile`.
- `/DATA/AppData/coc-bot/backups`: verified host-installation snapshots.
- `/run/coc-waydroid`: runtime socket/device metadata exposed to the bot.
- Host Waydroid storage: Android installation and game/account data, separate
  from bot-profile backups.

Setup snapshots calibration YAML, templates, user settings, runtime state, and
base configuration with a SHA-256 manifest before changes. It verifies the archive
and keeps it private. These snapshots are not complete copies of every profile
file: custom planner routines/artwork, collection, and Android account data need
separate backups. Library calibration ZIPs are narrower still: calibration and
templates, not settings or account data.

Before migration, Stop/release manual control and keep an independent full-profile
backup on another device. Import copies the supported old profile files into empty
storage only; it does not merge over a live setup or promise to migrate every new
feature directory. Preserve planner state separately and inspect the imported
profile before starting. Do not copy `.venv` between hosts.

Image builds exclude private calibration, datasets, APKs, and account files.
Entrypoint seeds missing defaults/game data/gesture assets without overwriting
existing user files. Shared calibration locks protect installer snapshots from
concurrent edits even when host/container profile paths differ. Device leases
exclude the original controller and package controller in both directions.

## Build and install

From a checkout on the CasaOS Linux host:

```bash
bash packaging/casaos/build.sh
```

In CasaOS, install a custom app by importing
[`packaging/casaos/compose.yaml`](../packaging/casaos/compose.yaml). The local image
is `coc-bot-casaos:local`; a registry release is not assumed. Review setup's
administrator host access before running it. The setup package does not install
CasaOS itself.

The dashboard defaults to `http://YOUR_LINUX_IP:8767`. Host networking carries the
HTTP/WebSocket API and local WebRTC traffic. Set `COC_WEB_HOST` and
`COC_WEB_ORIGIN` when automatic address selection chooses the wrong interface;
an origin includes scheme, address, and port. Default access is password-free,
so restrict it to a trusted LAN. A TCP web-port mapping/tunnel alone does not
establish the WebRTC UDP path.

The included castle icon is served at `/casaos-icon.png`. `COC_ICON_URL` can point
the CasaOS tile to that dashboard URL for a private/local installation. The image
also includes the compiled frontend; users do not need Node.js.

### Existing Waydroid and profiles

For an existing desktop session, set `COC_ADOPT_USER` on setup and, if different,
`COC_WAYLAND_DISPLAY`. `COC_IMPORT_PROFILE` can name the old profile for supported
empty-storage import. Adoption retains the Android installation and requires that
user's Wayland display; it does not guarantee startup before desktop login.
New installations use the dedicated headless display path instead. Neither mode
changes an existing Android resolution.

An administrator can perform host setup explicitly:

```bash
python3 packaging/casaos/install_host.py --dry-run
sudo python3 packaging/casaos/install_host.py --adopt-user YOUR_USER --import-from /path/to/old/bot
```

Replace the placeholders. Omit `--adopt-user` for the new headless-session route;
omit `--import-from` without an old profile. Do not execute a fresh install just
to update application code. `COC_SKIP_HOST_SETUP=1` skips bootstrap when the host
was already prepared. An installed bot-only Compose configuration is also used
for existing-host deployments; preserve its settings rather than replacing it
with the two-service fresh-install configuration.

A manually triggered image-publishing workflow exists under
`.github/workflows/casaos-image.yml`. Its GHCR publication/installation is a
separate release path, not proof of a tested public app-store installation.

## Install Clash without Google sign-in

The first installation needs your own trusted APK files. On a computer with Python
3, ADB, and an already-installed compatible Clash instance:

```bash
python3 scripts/export_clash_apks.py --device ANDROID_IP:5555 --output clash-apks.zip
```

Replace the device address. This exports installation files, including split APKs,
not account data. Use **Import Clash APK archive** when the package requests it.
The importer validates package identity and archive contents before installation.
Then open **Live view → Take control** and sign into the game yourself. Do not
supply account passwords/codes to the bot or helper.

Fresh profiles still require guided calibration. Imported calibration needs
matching dimensions and layout. Sequence mode needs recorded army taps; automatic
Electro Dragon mode does not. Automatic/planner modes still require navigation
calibration, supported army readings, pinned gesture assets, and verified maps.
See [attacks](ATTACK_REBUILD.md).

## Startup and controls

The dashboard remains available while Android prepares or fails. Runtime status
shows a stage/message/error and Retry. The helper starts/reuses the session,
connects and refreshes only the selected ADB transport, checks/installs the game,
launches it, and verifies screenshot health. Automation remains stopped.

**Start** begins automation; **Stop** cancels bot/tool actions and leaves the game
open. **Close Waydroid and Clash** explicitly closes the session. Closing a browser
tab leaves automation running. Stopping the bot container does not uninstall
Waydroid or delete Android data. On restart, pending attack/purchase work is
reconciled when its owning operation starts; no deploy/purchase recipe is replayed.
The container restart policy is not automatic gameplay Start.

Do not run an old service/controller alongside CasaOS. Keep a stopped rollback
installation and backups until the migration has been verified.

## Updating the bot and helper

1. Stop automation, release manual control, and back up the complete private
   profile as well as exporting calibration. Preserve the current image/tag.
2. Update the source with `git pull --ff-only` and build the new image with
   `bash packaging/casaos/build.sh` (or the intentionally selected image tag).
3. Recreate only **bot** using the installed Compose file, image, environment,
   and mounts. A checkout pull or browser refresh cannot replace code in an
   existing container. Do not rerun privileged setup for a code-only update.
4. Check container health, runtime readiness, assets, device/screenshots, and
   affected live actions. Verify protected profile data/settings. Press Start
   deliberately; refresh the browser for updated assets.

Helper changes require a separate administrator command while the device is idle:

```bash
sudo python3 packaging/casaos/install_host.py --refresh-helper
```

It takes a verified snapshot, checks device ownership, refreshes the helper,
reloads systemd, and restarts `coc-waydroid-host.service`. It does not reinstall
Android or reset calibration. Runtime directory preservation avoids stale socket
mounts. Administrator authentication is a host requirement, not a dashboard field.

If reverting an image, keep the same compatible profile and installed environment.
A profile restore must be deliberate; do not discard unfinished attack/upgrade
journals to make rollback start. Verify migration compatibility before using an
older controller against newer data.

## Updating Clash

After a trusted initial installation, managed runtime startup checks for a newer
Clash APK. To request a check immediately, Stop/release manual control and choose
**Diagnostics → Update Clash**. Progress appears in runtime status; automation
stays stopped. Set `COC_AUTO_UPDATE_GAME=0` to disable startup checks; the explicit
button remains available.

The current implementation uses APKPure's direct HTTPS endpoint and an allowlisted
CDN. This is a third-party source, not a Supercell distribution service. The
updater verifies a standalone package/version with `aapt`, its actual signature
with `apksigner`, and the signing-certificate identity against the installed trusted
base APK. Version must be newer. Unexpected redirects, changed certificates,
split-only packages, and invalid signatures are rejected. A new signing identity
needs manual review; the endpoint cannot bootstrap trust for a fresh account/device.

Before installation, calibration is backed up and the previous installed APK set
is retained under `data/game-update-backup` (one previous version). It never clears
account data or uninstalls the game. APK copies are not Android account backups;
automatic downgrade is not attempted. Downloads have cancellation/timeouts, a
2 GB cap, and require 6 GB free staging space.

If the provider fails during startup, the existing installation remains usable
and the failed check is reported. An explicit update error is shown as runtime
failure; Retry startup can reopen the existing game. Use trusted archive import
if the provider no longer supplies a compatible standalone APK. Updates do not
run periodically during gameplay.

Waydroid can temporarily freeze a package during install; the updater uses
non-streamed ADB installation and checks the committed version when the final
response is lost. If Waydroid shows a running session but a stopped/unresponsive
container, a host administrator may need:

```bash
sudo systemctl restart waydroid-container.service
```

Then Retry startup. Do not reset Android or uninstall Clash for this condition.
After any game update, check layout/calibration and preview affected operations;
a successful APK update does not establish recognition compatibility.

## Verification and remaining limits

Existing-host checks have covered image build/imports, CasaOS app management,
original/package ownership exclusion, verified profile backups, closed-session
reopen, stale-session/ADB recovery, trusted APK import/update, and decoded LAN
video/manual controls. Supervised donation and automatic farm checks have also
run on the current game; see [current evidence](WEB_UI_MIGRATION_STATUS.md).

The October 18 deployment of exact source `7d01eba` passed health/readiness and
installed-source checks, completed nineteen verified map deployments, recognized
results before the fallback, returned to home/chat, and cleared recovery markers.
Thirty-seven protected files and settings remained unchanged. A donation request
was not available in that particular deployment check, so fulfillment was not
retested there.

Still separate acceptance work:

- A clean supported host from no Waydroid/profile through APK import and sign-in.
- Dedicated headless GPU/display startup and reboot without desktop login.
- Broader GPU/kernel/CPU/Android/browser combinations and sustained failure/soak tests.
- Published image/app-store fresh installation, release updates, and rollback.
- All new game layouts/languages, sceneries, capacities, and unknown army artwork.

Historical pilot test counts do not establish these gates. The failed
[ReDroid evaluation](REDROID_EVALUATION.md) is not a supported runtime alternative.
