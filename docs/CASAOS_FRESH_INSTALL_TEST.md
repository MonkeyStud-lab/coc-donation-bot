# Fresh CasaOS installation test

Test date: **October 18, 2026**. Candidate based on `90a97a3` plus the
fresh-install provisioning changes. This is a separate acceptance record from
the existing-host gameplay checks; it does not describe a production deployment.

Latest result: a subsequent blank-disk KVM run completed fresh provisioning,
Android startup and APK installation with the complete `ddf04bb` image. Clash
itself exited during native-library loading, so full game acceptance remains
open. See the hardware-accelerated follow-up below.

## Isolation and environment

- A disposable Ubuntu 24.04.5 VM started with no Docker, CasaOS, Waydroid, game,
  calibration, or bot profile. The official Ubuntu cloud-image checksum was
  verified before boot.
- QEMU used software CPU emulation, initially two virtual CPUs and 4 GiB guest
  memory, later four CPUs and 8 GiB for reboot testing, with a 48 GiB sparse disk
  and a virtual graphics render device. Hardware CPU virtualization was
  unavailable. Graphics access did not detach the host GPU.
- Guest networking used NAT. SSH and the candidate-image transfer endpoint were
  bound to host loopback. The guest received no production profile, account data,
  host Docker socket, or host filesystem share.
- The VM ran inside a resource-limited, non-restarting container. Administrator
  installation commands ran inside the guest only.
- The live bot retained its original image. A checksum-verified private backup
  was taken before testing, including planner and upgrade recovery files.

## Checks completed

- The official CasaOS installer completed inside the guest. CasaOS reported
  v0.4.15; its dashboard responded and its services started. Docker reported
  29.9.1.
- CasaOS's own `app-management install --dry-run` accepted the project Compose
  file. Its app list discovered the created project and dashboard address.
- Before installation, the project preflight correctly reported Ubuntu 24.04,
  systemd and a graphics render node, with Waydroid absent and binder not loaded.
- The setup container installed display prerequisites and the matching kernel's
  extra modules, loaded binder, and added Waydroid's signed repository. The
  running kernel was retained.
- The actual two-service Compose setup completed with exit code 0. It installed
  Waydroid, downloaded and validated new VANILLA system/MAINLINE vendor images,
  created the dedicated `coc-game` user/headless display units, and enabled the
  host helper. No desktop session or existing Android installation was adopted.
- Guest EGL probing initialized GBM/surfaceless graphics through virgl, reporting
  OpenGL 4.3 and OpenGL ES 3.2. This is a graphics prerequisite check, not proof
  that Android or the game renders correctly.
- The candidate image was built from the changed Dockerfile. The build fetched
  46 validated public unit/spell icons rather than using a private profile cache.
- The image's offline acceptance check passed as its normal unprivileged user:
  a blank profile received matching artwork checksums and the pinned gesture
  server, the army catalog loaded its core identities, existing artwork was
  preserved, and no calibration or Android input was supplied.
- The final Linux regression suite completed **335 tests, two skipped**. A
  separate administrator-run package suite completed all **38 tests**, including
  actual key generation as the application user and the root/user lock checks.
- The image archive transferred to the guest matched its SHA-256 checksum.
  This used a locally built candidate, not a published registry image.
- A trusted installation-only Clash APK archive was exported and checksum-checked
  in the guest. Its native libraries include x86-64; no Android account/app data
  was copied.
- The fresh dashboard served its bundled frontend and setup/readiness controls
  without importing calibration. Secure ADB enrollment and a targeted reconnect
  authenticated the new Android device. The dashboard accepted and validated the
  trusted APK ZIP through its normal import endpoint.
- After a guest reboot, CasaOS, the dashboard and managed headless/helper
  services returned without a desktop login. The test profile sentinel and ADB
  identity were unchanged, and no calibration or gameplay automation was started.
  Android/game readiness is a separate, still-unpassed check.
- The production bot retained its original container start time and remained
  healthy/running. All 34 protected calibration/template/planner files and the
  settings values matched the baseline. The test candidate was not deployed.

The VM was used to diagnose and repair the candidate iteratively. Later app
checks used a code-only derivative of the verified image and a read-only bind of
the corrected runtime module. Each final source change was also rebuilt and
regression-tested in the complete image outside the VM. This is not an untouched
published-image acceptance run.

## Problems caught and fixed

- Fresh images previously omitted recognition icons, leaving automatic army
  reading dependent on an imported private cache. Builds now validate downloaded
  artwork and fresh-profile seeding.
- Atomic artwork writes initially left root-only permissions. The unprivileged
  image check caught this; public assets now use readable permissions, while
  private backups retain restricted permissions.
- Installation backup/import omitted planner and upgrade state. Both are now
  included; imports stage before publishing and reject nonempty destinations.
- A first-boot readiness regression reproduced the helper returning while
  Android still reported `sys.boot_completed=0`, before ADB preparation. The
  helper now waits. The fix was copied into the VM installer's staging directory
  before its first helper installation, and included in the rebuilt candidate.
- The real VM's first startup exposed Waydroid reporting `IP address: UNKNOWN`.
  The dashboard stayed healthy, but runtime preparation failed during IPv4
  parsing. The helper now treats missing/placeholder/invalid addresses as pending
  and never publishes them as an ADB device. A regression covers those values.
- Android eventually completed its first boot and obtained a DHCP lease, about
  eight minutes after session startup under CPU emulation. Fresh initialization
  now has a bounded ten-minute allowance; ordinary reopen keeps three minutes.
  The client timeout covers that allowance. A simulated slow-boot regression
  checks that readiness still waits for boot and ADB preparation.
- Helper-only refresh assumed both device metadata and a lease file existed.
  It now queries the current runtime when metadata is absent, creates a missing
  lease safely, and still rejects an active controller or an unknown device.
  This does not bypass ownership when Android has no usable address.
- VANILLA Android requires ADB authorization. Fresh setup now creates the app's
  private identity as the unprivileged application user and enrolls only its
  validated public key through the managed host helper. Existing identities are
  preserved, authentication remains enabled, and private keys are neither
  bundled nor sent through the helper API. Adopted installations retain their
  existing authorization behavior.
- Refresh returned before its socket was listening. The helper now uses systemd
  readiness notification; its refresh command waits for the endpoint.
- An unauthorized/stale ADB transport could prevent reconnection from being
  reached. Startup now takes ownership, disconnects only the selected transport,
  and reconnects before checking it. It never restarts a shared ADB server.
- A boot-complete property and connected ADB did not prove Android's package
  service was usable. Startup now checks that service before inspecting or
  installing Clash, and reports a bounded readiness failure instead of assuming
  a missing game.
- A preparation marker could incorrectly skip readiness on later boots. Managed
  startup now waits for boot completion and the TCP listener on reboots too.
  Health probing uses the managed container directly and does not start an ADB
  server under a different user's identity.

## Limits

Software-emulated timings are not performance results for a normal installation.
Android's framework also produced SystemUI/DeadSystemException failures and an
unavailable package service during this run. Their cause has not been established;
working EGL and `sys.boot_completed=1` were insufficient evidence of a usable
Android framework. Full APK installation, rendered game startup, and unattended
Android readiness must pass before this is treated as fresh-install acceptance.
The final corrected reboot reached the intended bounded readiness error
(`Waydroid did not become ready`); it did not proceed to install or launch a game
against the unavailable framework. The VM was then shut down with its disk/logs
retained for diagnosis. A hardware-accelerated VM or separate supported computer
is needed for the next end-to-end check; extending timeouts alone is not a pass.
This VM cannot establish physical GPU/driver compatibility across computers,
other kernels/distributions, remote-browser video quality, or published
app-store installation. Existing-host live gameplay evidence remains separate.

APK installation requires a trusted compatible archive. Game sign-in requires
the account owner. Fresh calibration and army review remain explicit steps;
public unit icons do not provide every hero skin or navigation reference.

See [the package guide](CASAOS_PACKAGE.md) for installation and backup scope.

## Hardware-accelerated follow-up — October 18, 2026

After SVM was enabled on the physical host, `/dev/kvm` appeared and an
unprivileged test-container probe returned KVM API version 12. QEMU used
`-accel kvm -cpu host`, four vCPUs and 8 GiB guest RAM, retaining VirtIO 3D and
EGL-headless graphics. The previous VM disk was preserved. A second disk started
from the verified Ubuntu cloud image with no Docker, CasaOS, Waydroid or profile.

This clean run used source `ddf04bb` and the complete locally built image, with
no code bind mounts or repair image layers. Image transfer checksums and the
offline blank-profile acceptance check passed inside the guest. The actual
Compose setup service exited successfully after installing host prerequisites,
binder, Waydroid and fresh validated Android images. CasaOS and the bundled
dashboard started normally.

The normal dashboard flow reached **Import the Clash APK archive**, authenticated
the new Android device, accepted the trusted archive, and installed Clash
18.647.2. No production profile, Android account data or calibration was imported.
Gameplay automation remained stopped.

**Game compatibility is still an open acceptance gate.** Clash exited immediately
with the obfuscated exception `pmmvato.ay: 02` during native-library loading. A
fixed direct launch reproduced the failure. The working physical installation
and this guest both selected x86-64 and the same game version; those checks do
not explain the failure or establish an anti-VM/protection diagnosis.

A separate trial of Waydroid's documented SwiftShader/default-gralloc fallback
also failed to keep Clash running. That trial preserved and then restored the
original Waydroid configuration. Dashboard screenshot capture succeeded and was
visually checked: it showed a rendered Android launcher at 1853 × 1016, not a
running game. **Close Waydroid and Clash** successfully stopped the session.
Retry startup then reopened Android and attempted the installed game, reporting
the same bounded game-compatibility error.

A subsequent guest reboot brought back CasaOS, the healthy dashboard container,
host helper, headless display and Android session without desktop login. Android
reported boot completion, Package Manager was usable, and the installed Clash
package remained present. The private ADB identity, default configuration,
artwork manifest and test-profile sentinel matched their pre-reboot hashes.
No private calibration appeared and automation remained stopped. The game still
failed to remain running; the dashboard correctly reported that failure instead
of marking the runtime ready. The temporary guests were shut down afterward,
with their disks and diagnostic evidence retained.

The new Android image also briefly reproduced the SystemUI
`AppOpsControllerImpl` null-pointer crash reported in
[Waydroid issue 2428](https://github.com/waydroid/waydroid/issues/2428). Android
subsequently reached boot/package readiness; this observation does not establish
that SystemUI caused Clash's separate native-load exception. CPU acceleration
resolved the earlier speed limitation but did not establish game compatibility.

## Controlled startup comparisons — October 18, 2026

Further experiments used a child disk overlay of the stopped accelerated guest.
The baseline disk, production Android data and production profile were not used
as writable test storage. The guest had no game account or private calibration.

The installed Clash APK was byte-for-byte identical to the working host's APK
(18.647.2, native x86-64). Waydroid tools were version 1.6.2 on both machines.
Android API level, CPU ABI, native-bridge selection, secure/debug properties and
the inspected memory-mapping policies matched. These comparisons narrow the
differences; they do not establish that every runtime dependency is identical.

The working host used April 3 system and April 28 vendor images; the fresh guest
initially used September images. The older public images were downloaded from
the official distribution, their extracted hashes matched the working host's
base images, and they were installed with fresh guest Android user data. The
actual running April fingerprint was verified. Clash still exited during native
loading with `pmmvato.ay: 02`. Replacing the Android image pair did not fix it.
An initial harness attempt used `waydroid init -i` incorrectly as an image-input
option; only the corrected, hash-verified preinstalled-image trial is evidence
for this comparison. See Waydroid's
[custom image instructions](https://docs.waydro.id/faq/using-custom-waydroid-images).

Graphics remain an unresolved difference. The working host exposes AMD RADV
Vulkan. The original guest rendered Android through VirGL/OpenGL. A Lavapipe
selection trial also failed to keep Clash running, but Vulkan device enumeration
was not checked in that trial, so it does not prove software Vulkan was usable.

A separate Venus experiment used QEMU 10.2.1, Mesa 26.0.8 and virglrenderer 1.2,
with blob resources, a 2 GiB host-memory window, shared memfd RAM, the existing
host `/dev/udmabuf` device and an unlimited locked-memory allowance in the test
container. No physical-host permissions, kernel settings or GPU bindings changed.
Despite those changes, Android reported no Vulkan devices. A native Linux guest
probe also failed at `vkCreateInstance` with `ERROR_OUT_OF_HOST_MEMORY`; QEMU
reported `virgl blob create error: Invalid argument`. This is a failure of the VM
Vulkan path, not a successful hardware-Vulkan game test, and does not prove the
cause of Clash's obfuscated exception. The documented configuration references
are [QEMU VirtIO GPU](https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html)
and [Mesa Venus](https://docs.mesa3d.org/drivers/venus.html).

No game binary, installer identity, security checks or VM-identification
properties were modified. There is no demonstrated game-startup fix from these
experiments. Passing provisioning or rendering the Android launcher must not
be presented as end-to-end fresh-install acceptance.

The headless guest's successful display/session/capture checks demonstrate the
service architecture without a desktop, not game compatibility on every GPU.
For the existing working machine, the next useful headless test is a reversible
offscreen-compositor migration on bare metal while retaining its Waydroid owner,
Android user data and frame dimensions. See
[headless operation](CASAOS_PACKAGE.md#headless-operation). No production
headless migration was attempted during these diagnostics.

The final test guest shut down cleanly with exit code 0. Its disk overlays and
private diagnostic logs were retained; five redundant stopped diagnostic
containers were removed. Final production verification found all 34 protected
files and settings unchanged, a healthy dashboard container and a ready runtime.
Production automation remained stopped, as it was before testing. No update was
deployed, and no private APKs, screenshots, keys or VM disks were added to Git.
