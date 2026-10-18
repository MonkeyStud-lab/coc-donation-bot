# ReDroid evaluation for the CasaOS package

Tested October 11, 2026. **Recommendation: retain Waydroid. Do not migrate to the tested ReDroid images.** Android 13 booted with AMD graphics and working ADB, but Clash crashed on both launches and browser video failed acceptance. Android 16 failed to complete boot. Lower passive resource use does not establish a useful replacement for the working game installation.

## Host and isolation

Ubuntu host: Ryzen 5 5500GT, 12 logical CPUs, approximately 30.2 GiB RAM, AMD Renoir graphics / amdgpu, kernel 7.0.0-31-generic. SSH: 100.121.41.45; LAN: 192.168.4.64. The user enabled Docker group access for the SSH account after the initial inspection was blocked.

Trials used `/home/server/Projects/coc-redroid-evaluation`, separate containers and named data volumes, localhost-only ADB port 5556 and no automatic restart. Waydroid images, Android data and production bot profiles were not mounted into either container. Only the five installed game APK files were copied; no account data or credentials were copied. No kernel modules, Binder mounts, firewall rules or Docker daemon settings changed.

Both trial containers and the copied-profile browser server were stopped after testing. Evidence, APK copies, images and trial volumes remain available for review. Production servers on ports 8765 and 8772 were left running.

This was a runtime evaluation for a prospective package, **not CasaOS installation acceptance**. No active CasaOS service or deployed package was found in checked locations. `/var/lib/casaos` exists, but `/etc/casaos` was absent. CasaOS installation, launcher and restart behavior remain untested.

## Exact images and configuration

- Android 13: official `redroid/redroid:13.0.0-latest`, digest `sha256:41e5f0c1ff27a4a474c474e5595168cedf6c40fc5dd102c5617f48c80f511e9e`, created May 27, 2024. Container `coc-redroid-evaluation`.
- Android 16: official `redroid/redroid:16.0.0-latest`, digest `sha256:d89f520484bd16aac244e9832a150f72a8b9296f0b4439f3667c8181d1f3b77f`, created June 27, 2025. Container `coc-redroid-evaluation-16`.

Both requested memfd, explicit host GPU mode, `/dev/dri/renderD128`, 1853 x 1048, density 180 and 30 fps. Versions ran sequentially with separate data volumes. The Android 13 Compose file is pinned to the tested digest in `experiments/redroid/compose.yaml`. Image and APK manifests are saved alongside it.

## Clash of Clans: failed on Android 13

Installed the exact five APKs from Waydroid using `adb install-multiple`: version 18.600.7, version code 180600008, primary ABI x86_64. Installation succeeded. This particular installation does not require ARM translation.

Two launches crashed before the game appeared. Android exit history records APP CRASH(EXCEPTION) for both. The exception starts with `cnsbodqak.ah: 02` during Runtime.nativeLoad / System.loadLibrary, before the application factory initializes. The underlying cause is unresolved. No protected game code, device identity or integrity checks were changed to work around it.

Village loading, account login, gameplay and sustained game operation could not be verified. Evidence: `crash-13.log`, `exit-13.txt`, `apk-manifest.json`, and local `redroid-first-launch.png`.

## Android 16: boot failed

ADB and SurfaceFlinger started, but the system server/zygote repeatedly restarted. Boot completion never reached 1 and ActivityManager was absent. Its crash log reports `Failed to create ashmem: No such file or directory` from ApplicationSharedMemory.nativeCreate despite `androidboot.use_memfd=true`. Stopped the trial without changing host memory drivers. Clash was not installed or tested on this image. Evidence: `crash-16.log`.

These results apply to these pinned images on this host/configuration, not every possible ReDroid build.

## GPU: hardware rendering passed; encoding was software

Waydroid reports AMD Radeon Graphics / radeonsi / Renoir, OpenGL ES 3.2, Mesa 26.0.5. ReDroid Android 13 reports the same AMD renderer with Mesa 24.0.8 and GPU mode host. Settings and launcher rendered correctly. Android 16 also reported the AMD renderer before boot failed.

The project's real pinned scrcpy 3.3.3 transport produced eleven decodable H.264 frames at 1280 x 720. First decoded frame: approximately 0.41 seconds. Its logs identify `OMX.google.h264.encoder`, a software encoder. AMD rendering therefore does not mean AMD video encoding.

The bounded transport probe ended after about 6.4 seconds when a static launcher stopped producing packets and its five-second packet deadline expired. This is not a sustained FPS benchmark. Evidence: `scrcpy-13.json` and `probe_scrcpy.py`.

The [official ReDroid documentation](https://github.com/remote-android/redroid-doc) documents software rendering as the default and explicit host rendering; its own WebRTC integration is described as planned. Browser delivery needs separate verification.

## ADB control: passed on Android 13

Verified boot completion, shell access, APK installation, screenshots, disconnect/reconnect, Settings launch, a coordinate tap opening Apps, Back, a swipe scrolling Settings and Home returning to the launcher. Before/after screenshots were inspected. All input explicitly targeted 127.0.0.1:5556; no Waydroid input was sent.

Successful swipe: (500,900) to (500,350), 600 ms, after a one-second Settings transition wait. An earlier swipe immediately after Back did not visibly scroll. Evidence: `adb-control.json` and local `adb-*.png` screenshots.

## Browser live view: failed acceptance

Ran the existing web viewer from copied source and an isolated ReDroid profile on localhost port 8773, accessed from Windows through an SSH tunnel. No bot or farming actions were started.

Two in-app-browser attempts opened Live view. The first reported a disconnected stream. A second, while Settings/Home transitions generated changing content, still showed no verified video and reported a live-view timeout. A Live badge alone is not proof of decoded frames. Browser Take control and sustained video remain unverified.

The source/decoder probe proves Android emits H.264; it does not prove browser decoding or WebRTC transport. The browser failure's cause is unresolved. The SSH tunnel carries HTTP/WebSocket TCP, not WebRTC media UDP; network traversal and the in-app browser limit this result. Chrome/Firefox and direct LAN browser tests were not performed. No firewall rules were changed. Local screenshot: `experiments/redroid/browser-13-timeout.png`.

## CPU and RAM: passive states, not equivalent workloads

The standard-library probe reads cgroup-v2 counters every two seconds for 60 seconds. CPU 100% means one logical CPU. Memory is memory.current, with anonymous and file memory separately reported. Waydroid scope is its Android payload; ReDroid scope is its Docker container. These exclude the Linux compositor, web server and client browser. Existing host workloads remained running.

Waydroid, game resumed, no test viewer:

- Mean CPU: 39.64% of one core (about 3.30% of the 12-CPU host).
- Mean total memory: 3820.91 MiB (3.73 GiB).
- Mean anonymous memory: 1296.06 MiB (1.27 GiB).
- Mean file memory: 2393.73 MiB (2.34 GiB, includes cache).

ReDroid Android 13, launcher after game crash, no test viewer:

- Mean CPU: 0.20% of one core.
- Mean total memory: 1504.49 MiB (1.47 GiB).
- Mean anonymous memory: 496.85 MiB (0.49 GiB).
- Mean file memory: 852.44 MiB (0.83 GiB, includes cache).

The Waydroid screenshot after sampling showed an inactivity dialog; it was not observed continuously during sampling. ReDroid had no running game. These workloads are **not comparable as gameplay performance**. No percentage savings or migration benefit is claimed. Docker's displayed memory excludes some cache and cannot be compared directly with Waydroid memory.current. Android 16's boot loop was not benchmarked.

Raw evidence: `waydroid-baseline.json`, `redroid-13-passive.json`. Tool: `scripts/probe_android_runtime.py`.

## Preservation and integration hazards

Waydroid remained installed and ADB-reachable throughout. Its service remained active and payload freeze counter was 0 at final verification. Before/after SHA-256 checks matched for:

- `/var/lib/waydroid/waydroid.cfg`: 021731607dbfb0d7fbeaf093d20935236791fc849097b366190a7c7730d1a1fb
- Production `config/default.yaml`: a1604a2d2b4367fee215a873f94eedc255d96f1e634d1b071fe39111e9f1e4b5
- Production `data/calibrated.yaml`: f32484297719a2da3410f4b0683ca21cc2838ff3281a12d381cad0dfba675782

No production source, profile, service or Android setting was intentionally changed. Evidence: `preservation-after.json`.

Source inspection found two migration hazards: AppController.launch opens Waydroid whenever its executable is installed, regardless of selected ADB device; DebugSession.close_waydroid stops the user's Waydroid session even when its game force-stop targeted another device. These need runtime-specific guards before a ReDroid package can share a host with Waydroid. Production code was left unchanged.

## Migration gate

Keep Waydroid. Reconsider only after a documented, reproducible ReDroid configuration boots on this kernel, runs the unchanged current game and passes real browser video/control tests. Then compare matched connected-village and live-view workloads with the same game version, scene, display and stream settings: warm up, collect at least three matched 60-second windows and include compositor/web-server costs. Actual CasaOS install/restart acceptance is a separate gate.
