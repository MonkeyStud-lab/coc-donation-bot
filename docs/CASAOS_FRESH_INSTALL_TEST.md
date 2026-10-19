# Fresh CasaOS installation test

Test date: **October 18, 2026**. Candidate based on `90a97a3` plus the
fresh-install provisioning changes. This is a separate acceptance record from
the existing-host gameplay checks; it does not describe a production deployment.

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
