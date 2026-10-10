# Reliability changes and verification

## What changes for users

- **Elixir confirmation:** Setup → Donation panel → Selected elixir indicator.
  Open clan chat, tap Donate, select the LEFT elixir button, then capture the
  entire selected button, including its highlight and background. The ordinary
  Elixir resource button tap must also be calibrated. Donations are skipped
  whenever either reference is missing or selection cannot be confirmed.
  Old calibration is preserved; add this part before using donations again.
- **Useful screenshots:** enable Screenshot collection in Settings, set daily
  and storage limits, then Stop/Start. Library shows the saved-image status and
  opens the local review gallery. Nothing is automatically uploaded or deleted.
  CLI collection options still override GUI defaults for that launch.
- **Interface profiles:** stop the bot, then Library → Saved calibrations → Save interface profile.
  Name it for the game update or screen layout. Switch restores its calibration
  and template images together. Rename/delete stored profiles from Library.
  Profiles do not automatically recognize game versions or guarantee compatibility.
- **Calibration checks:** Library checks required parts, files, coordinate bounds,
  and the latest screenshot size when available. Also verify that the images
  match the current interface. Practice mode skips donation taps but still sends
  navigation input; it is not an offline simulator.
- **Screenshot previews:** during operation, the preview shows the latest bot
  frame and its age. It does not launch a competing screenshot operation.
- **Stop and Quit:** Stop cancels active ADB commands and input settling. Quit
  waits for bot/farm workers to finish instead of destroying the window while
  they can still send input. Another bot cannot start on the same ADB serial.

## Developer behavior

Captures share a per-device lock and latest-frame cache. A normal capture has a
12-second total command budget; battle observations have a 3-second budget.
Failed captures no longer start a separate unbounded reconnect loop. The bot's
existing recovery handles reconnects. Device leases use OS file locks, released
on exit; stale lock files alone do not prevent a restart. Different aliases for
the same physical device are not automatically identified.

Calibration restores stage both YAML and images before swapping them. Failures
roll both back. A journal lets the next config load recover an interrupted
restore. Config reads and restores share a lock to prevent reading half a swap.
A failed safety backup aborts restoration. Recovery files are retained if
rollback cannot complete. This protects interrupted processes, not all storage
failures or abrupt hardware power loss.

Button-label OCR has a two-second subprocess budget and returns immediately on
a clear Donate/Trade result. Identical crops use a bounded cache; ambiguous reads
expire quickly. This improves speed without treating ambiguous text as evidence
that a button is safe. EasyOCR capacity parsing remains optional and separate.

Page builders live in `gui/page_views.py`; controller callbacks stay in
`gui/app.py`. Collection/profile controls live in `gui/data_tools.py`. The themes
and layouts are preserved. Further controller splitting can be incremental.

## Reproduce checks

From an activated environment:

```sh
python -m unittest discover -s tests -v
python scripts/verify_farm_offline.py
python scripts/verify_smart_collection.py
python scripts/verify_battle_completion.py
xvfb-run -a python scripts/verify_gui_offline.py
```

The GitHub workflow runs these checks on Python 3.12 and 3.14 without a connected
game. The GUI test builds every page/theme. The tests exercise restore failures,
capture concurrency, subprocess cancellation, device exclusion, OCR caching,
elixir confirmation, runtime corruption, and paused farm timers. They cannot
replace live verification of new sceneries and game updates.

`constraints/linux-py314.txt` records the direct versions tested on the Linux
host. On Python 3.14, use `bash scripts/setup_linux.sh --tested-deps` to request
those versions. Normal setup continues choosing compatible versions for your
Python. This project is installed from a source checkout; standalone wheel-only
installation does not yet include the setup scripts and configuration files.
