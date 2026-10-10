# Screen recognition and recovery

The existing bot still decides what to click. The first perception prototype
only reports what screen it thinks it sees, so we can measure mistakes before
giving a learned model any control.

## Shop and Clash Pass recovery

These two pages have explicit `shop` and `clash_pass` screen types. They can
interrupt either the donation or attack flow, so they are checked before the
older home, donation, and battle heuristics in every navigation mode.

The detector in `vision/auxiliary.py` checks small, fixed parts of the header:

- Shop: at least two of the building, army, and treasure navigation icons.
- Clash Pass: both the “Pass Rewards” and “Hoggy Bank” headings.

The small reference crops ship with the package in `vision/assets/`. No new
calibration or OCR installation is needed. Account details, purchases, season
names, reward contents, and currency balances are not part of these assets.
Captures are normalized to a small landscape reference size for matching;
the close button coordinates are converted back to the capture's actual size.
Portrait and very wide layouts are deliberately unsupported.

Recognizing a page does not automatically authorize a tap. A separate match
must find its red close X in the upper right, with a bright white X. This rejects
dimmed buttons underneath dialogs such as “Connection lost.” When the close
button is obscured or unverified, recovery stops and logs that the covering
dialog needs manual attention. It does not click offers or purchase buttons.

`auxiliary_recovery.py` limits each recovery operation to three close attempts,
checks Stop immediately before a tap, and uses zero tap jitter. Navigation
takes a new screenshot after each attempt and verifies the next screen before
opening chat or starting an attack. The same logic applies when returning from
an attack and confirming that clan chat can open.

This is a focused template-based fix, not a learned button detector. It has been
checked on the reviewed seed at the original size, 1280×720, and 1920×1080. A
future game redesign, different language, or rearranged header may require new
reference crops. There is only one reviewed Clash Pass example so far.

## Inactivity dialog recovery

The English “Anyone there?” inactivity dialog is recognized before background
home, chat, shop, or battle anchors. `vision/idle_dialog.py` requires the title
and inactivity message together, plus a separate bright “Reload game” label
below them. Only those generic text crops are bundled; no account screenshots
are shipped. The detected button coordinates scale with the screenshot.

While automation is running, navigation taps Reload game with no jitter,
captures fresh frames, and resumes only after normal screen verification.
It waits at least ten seconds between attempts and allows at most three reloads
per two minutes per navigator. Stop cancels recovery; a stopped bot does not
monitor or reload the game. Reload also enables the existing short live-defense
watch window. No extra calibration or OCR dependency is required. Other
languages and substantially different Android dialog layouts need new anchors.

## First learned screen prototype

### Prepare reviewed examples

Label Studio is an optional, separate annotation tool; the bot does not install
or run it. A fresh clone does not include the private reviewed dataset or a
trained model. Start by [collecting useful screenshots](SMART_COLLECTION.md),
then export tasks with `python scripts/export_collection_tasks.py`.

For an existing Label Studio installation:

1. Enable local-file serving with its document root set to this project's
   absolute `data` folder. The task URLs use `/data/local-files/?d=...` paths
   relative to that folder. Keep access restricted because screenshots may
   contain player names and chat.
2. Generate the project's labeling configuration with
   `python scripts/preannotate.py --no-heuristics --limit 0`.
   Copy `data/labelstudio/label_config.xml` into the project's labeling setup.
   This uses the categories in `data/labels.yaml`.
3. Import `data/labelstudio/collection_tasks.json`. Check that images load, then
   review each image and select exactly one whole-screen label. Suggested labels
   are not verified answers.
4. Export the completed annotations as Label Studio JSON, keeping the original
   screenshot files in their existing folders. Keep session identifiers so
   evaluation can separate recording sessions.

Installing and configuring Label Studio itself is outside the bot's Linux
installer. Training needs at least two screen categories and benefits from
several independently recorded sessions.

`scripts/train_screen_model.py` trains a small regularized linear classifier using OpenCV and NumPy,
which are already project dependencies. It learns spatial color and edge
features from reviewed, whole-screen labels. It does not use the partial object
boxes, connect to the game, or require a GPU.

From the project folder with the virtual environment activated:

```bash
python scripts/train_screen_model.py \
  --tasks path/to/reviewed-screen-tasks.json
```

Replace the example path with your exported annotations. The original images
named by the local-file URLs must remain under `data`; legacy recordings use
`data/frames`, while smart collection uses `data/collection`. Use `--data-dir`
if those files live elsewhere. The optional historical export at
`data/labelstudio/review/curated/tasks_curated_screens_v2.json` is not shipped with
the repository. It introduced the explicit `clash_pass` label in place of `other`.

Training writes `data/models/screens.npz` and matching `screens.json` metadata.
The metadata contains the class counts, feature scaling, source export hash,
and evaluation results. These local training files are excluded from Git.

Validation holds out an entire recording session at a time. Categories absent
from the other sessions are listed as **unvalidated**, rather than being scored
as if they were learned. A good fit to the training images is not evidence of
reliable recognition on new sessions. The small AI-reviewed seed has limited
variation, and its battle examples are scouting screens rather than active
combat. Do not replace the navigation rules with this prototype.

In the initial historical 56-frame seed evaluation, the prototype correctly classified 39 of 54
eligible session-held-out examples (about 72%). The other two examples belonged
to categories absent from their training sessions: Attack menu and Clash Pass.
These results confirm that observation is the appropriate next step; they do
not establish reliability for controlling the game. The separate, fixed-header
Shop / Clash Pass recovery passed all 56 seed frames at three resolutions,
including refusal to tap the dimmed Shop X beneath a connection-loss dialog.

To compare the model while using the normal control window:

```bash
python -m coc_bot.main --screen-model data/models/screens.npz
```

Activity messages such as `Screen observer (no actions): model=shop rules=shop
agree=True` appear at most once every five seconds. They go through the existing
rotating application log. The observer never changes the classifier's return
value, clicks, state transitions, or donation/attack decisions. A missing,
incompatible, or broken model disables observation while the normal rules
continue. Launch without `--screen-model` to leave observation disabled.

## Offline checks

These checks do not issue ADB commands:

```bash
python scripts/verify_auxiliary_screens.py
python scripts/verify_farm_offline.py
python scripts/verify_screen_model.py
```

When the reviewed images are available, also run:

```bash
python scripts/verify_auxiliary_screens.py \
  --tasks path/to/reviewed-screen-tasks.json
```

The first script checks actual recognition, obscured-button refusal, retry
limits, Stop, fresh-frame confirmation, and recovery in both navigation flows.
The model checks cover training/reloading, isolated-session evaluation, and
failure handling without navigation changes.

The next useful data collection should cover additional Shop tabs, current
Clash Pass pages, different sessions/sceneries, active battles, and dialogs
covering those pages. Review the observer's disagreements against the saved
images, correct labels independently, and retain a separate test session before
considering any learned recognition for navigation.
