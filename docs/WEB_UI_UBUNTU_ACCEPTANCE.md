# Ubuntu and LAN acceptance

Tested October 10, 2026, from a Windows computer on the same LAN as Ubuntu.
The migration was copied into a separate pilot directory. The existing desktop
bot, checkout, Python environment, and Android game were not replaced or stopped.

## Passed

- All 42 automated tests on Ubuntu with Python 3.14.
- Browser dependencies installed in a separate Python environment.
- Linux wheel build, isolated installation, imports, and bundled HTML/JS/CSS.
  Existing game dependencies were reused read-only; this was not a completely
  clean installation of all game dependencies.
- Real cross-computer LAN connection, browser sign-in, Start, second-tab status,
  and Stop. These operation tests used a fake bot with real ADB forbidden.
- Two independent HTTP sessions: authentication, rejected missing CSRF tokens,
  rejected foreign origins/hosts, settings revision conflicts, and logout.
- Authenticated event WebSocket disconnect/reconnect.
- Ten status requests averaged 1.1 ms, maximum 1.2 ms. Fake-worker Stop completed
  in 10.5 ms. These measure the interface, not live screenshots or game actions.
- Disposable copy of existing calibration/settings/templates loaded successfully:
  all 32 setup parts were available; 30 were configured; resolution 1853×1048.
- Existing production device lease correctly refused a competing controller.
- Original calibration, settings and templates retained identical SHA-256 hashes.

Browser evidence: [Ubuntu LAN dashboard](design/web-ui/ubuntu-lan-dashboard.jpg).

## Still pending

The existing desktop automation was running. Permission to pause it was requested
before live interaction tests; no live game commands were issued in this pass.

- Supervised real screenshot/viewer, calibration save/cancel, donation and farming.
- Live startup, capture, Stop/cancel latency and sustained resource measurements.
- Server restart/network interruption recovery under sustained operation.
- A phone or other additional client and a fully clean Linux installation.
- Video transport and rotation/input mapping on actual Waydroid.

The optional headless desktop smoke test could not run because `xvfb-run` is not
installed on Ubuntu. No system packages were installed to work around this.
The earlier Windows desktop smoke checks remain valid only for Windows.

## Live-game follow-up

Later on October 10, live tests were authorized. The desktop GUI process was
paused and the web server ran against a separate copy of its profile. Waydroid
and Clash remained open throughout.

Passed against the real device:

- ADB health check, 1853×1048 screenshots, and clan-chat/home recognition.
- Capture completed in approximately 1.7 seconds over LAN.
- Viewer frame delivery, exclusive ownership, disconnect cleanup, and a real
  coordinate tap closing the orange chat tab. Home was recognized afterward;
  navigation reopened clan chat successfully.
- Practice-mode Start/Stop: worker shutdown completed in approximately 220 ms.
- Standalone-farm cancellation before matchmaking: approximately 217 ms.
  This does not measure cancellation during deployment or an in-flight slow ADB command.
- Browser calibration Cancel left the revision unchanged. Saving screenshot size
  on the copied profile and restoring a backup recovered the exact original revision.
- One full unranked farm: opened Attack, found an opponent, executed the existing
  33-tap sequence, waited for the 200-second fallback, tapped Return Home, then
  confirmed home by opening clan chat. The observer did not trigger an early
  results exit in this run; only fallback completion is verified.
- Competing Start and capture were refused during farming.
- Original calibration/settings/templates were compared byte-for-byte with the
  restored copied profile and remained unchanged.

No Donate request was visible before or after the attack, so actual donation and
elixir-mode selection remain unverified. Long-duration operation, real device
failures, mid-battle cancellation and video transport are still acceptance gates.

A minor Diagnostics presentation issue exposed raw screenshot metadata; the
frontend now suppresses that output. TypeScript and the production build passed.

The live server was shut down and the original desktop GUI reopened using its
existing display authorization. Automation is stopped by default after reopening;
press Start in the desktop GUI to resume it. No production update, commit or push
was performed. Test screenshots/logs are kept outside the documentation assets.

The temporary LAN preview was shut down after the checks. Its known test password
must never be used for a live deployment. No firewall or router rules changed.
