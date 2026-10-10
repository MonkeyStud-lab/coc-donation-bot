# Automatic collection of useful screenshots

This optional recorder uses screenshots the bot already takes. It does not press
buttons, start extra attacks, upload images, change calibration, or train a model
automatically. Normal donation and farming rules still control every action.

## Start collecting

Activate the project's virtual environment, then start the app with:

```bash
python -m coc_bot.main --collect-smart
```

Press Start in the GUI. For terminal-only operation add `--no-gui`. To compare
an existing experimental model, also add `--screen-model path/to/screens.npz`.
Model predictions are logged and attached to screenshots; they never control taps.
The flag must be supplied whenever launching a new app process. It takes
precedence over the older `--record` mode, which remains available unchanged.

## What it keeps

- Visually different screens, including different layouts and appearances.
- Unfamiliar screens, conflicting rule classifications, and model disagreements.
- Examples of uncommon screens such as Shop, Clash Pass, popups and battle results.
- Failure incidents: up to two preceding screenshots, the failure screenshot,
  and the next two screenshots captured by the bot.

Image comparisons include the header, chat area and army bar so small interface
changes are less likely to disappear into unchanged scenery. Near-identical
screens are skipped across sessions, even if their classifications change.
Repeated incidents are counted rather than saving the same failure endlessly.
An existing reviewed `data/labelstudio/review/curated/tasks_curated_screens_v2.json`
dataset is also used for duplicate comparison when its source images are present.
This seed is optional; original files and annotations are never modified.

The first screen classification is stored as a *hint*, not a verified label.
Screens captured without a classification inherit the previous hint and are
explicitly marked `screen_inherited`. Action metadata records what was issued;
an issued tap alone is not proof that the game responded.

## Limits and responsiveness

Defaults are 200 saved images per UTC day, 5 GB for `data/collection`, 20 ordinary
examples of each screen per day, and 10 distinct failure windows per day. At most
120 images are routine/new-appearance examples, reserving capacity for more
useful cases. A 2% random sample tags some distinct ordinary examples as routine.
Incident context can exceed the per-screen limit, but not the total daily limit.
The daily count survives restarts. Quotas reset at midnight UTC.

```bash
python -m coc_bot.main --collect-smart --collection-daily-limit 100 --collection-storage-gb 2
```

Selection, PNG compression and gallery writing happen in a background worker.
The capture queue is bounded; overloaded collection drops samples instead of
blocking gameplay. Raw screenshot buffering has a 64 MB budget, with additional
small fingerprint/index memory. Stop waits at most one second for the worker;
the worker finishes queued writes while the app remains open. Closing the entire
app can interrupt remaining queued samples. A file lock prevents overlapping
writers during rapid Stop/Start operations.

Collection pauses at its storage cap or below its free-disk reserve (256 MB).
It never deletes older datasets, reviewed images or calibration. Free space or
raise the collection cap, then restart the bot to resume. Limits cover this new
collection, not existing `data/frames` or debug logs. Metadata/gallery size is
reserved conservatively; limits are not a filesystem quota.

The battle completion watcher takes bounded, best-effort screenshots during its
wait (see [battle completion](BATTLE_COMPLETION.md)). Collection reuses these
captures; it does not run a separate ADB capture thread. Failure context is a sequence of available captures,
not a guaranteed number of seconds before/after an event. No active exploration
of menus is performed.

## Review and use the data

In Tools, click **Review collected screenshots**, or open
`data/collection/review.html` in a browser on the bot computer. It groups the
latest 600 saved images by new appearances, disagreements, failures and ordinary
examples. Expand each image's details to see its action, phase and predictions.
`status.json` gives collection totals and any pause reason. `catalog.jsonl`
contains the complete image index; `incidents.jsonl` links already-saved context
frames to incidents. Each session also has its own metadata and image index.

To import new examples into the existing Label Studio workflow:

```bash
python scripts/export_collection_tasks.py
```

Import `data/labelstudio/collection_tasks.json`. Its image URLs use the existing
local-files setup rooted at the project's `data` folder. Suggested screen names
are metadata only: manually check each task and apply its correct label before
training. Do not treat bot rules or model guesses as ground truth. Screenshots
can contain player names and chat messages; inspect them before sharing.

Split training and evaluation by session so near-identical frames from one run
cannot make test results misleading. Keep an untouched test set and compare
accuracy separately for each screen type. Model updates remain a separate,
explicit task.

## Developer checks

Run `python scripts/verify_smart_collection.py`. These offline checks cover
cross-session duplicates, reviewed-seed comparison, failure context, persistent
quotas, storage protection, low disk space, action metadata, memory bounds,
single-writer protection and interrupted catalog tails. They do not contact ADB.

Integration hooks are in `vision/recorder.py`. `vision/collection.py` owns policy
and storage. Collection-hook failures must never block navigation or determine
which game action is safe.
