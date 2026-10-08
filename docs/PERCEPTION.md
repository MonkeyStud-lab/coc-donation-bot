# Screen recognition and recovery

The existing bot still decides what to click. The first perception prototype
only reports what screen it thinks it sees, so we can measure mistakes before
giving a learned model any control.

## Shop and Clash Pass recovery

These two pages now have explicit `shop` and `clash_pass` screen types. They can
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

## First learned screen prototype

`scripts/train_screen_model.py` trains a small regularized linear classifier using OpenCV and NumPy,
which are already project dependencies. It learns spatial color and edge
features from reviewed, whole-screen labels. It does not use the partial object
boxes, connect to the game, or require a GPU.

From the project folder with the virtual environment activated:

```bash
python scripts/train_screen_model.py \
  --tasks data/labelstudio/review/curated/tasks_curated_screens_v2.json
```

The version 2 screen export identifies the reviewed Clash Pass page explicitly;
the earlier export called it `other`. The earlier exports and screenshots are
preserved. When importing this version into Label Studio, regenerate its
labeling configuration from version 2 of `data/labels.yaml` first so the new
`clash_pass` category is available. Training requires the original images named
in the export to be present under `data/frames/`.

Training writes `data/models/screens.npz` and matching `screens.json` metadata.
The metadata contains the class counts, feature scaling, source export hash,
and evaluation results. These local training files are excluded from Git.

Validation holds out an entire recording session at a time. Categories absent
from the other sessions are listed as **unvalidated**, rather than being scored
as if they were learned. A good fit to the training images is not evidence of
reliable recognition on new sessions. The small AI-reviewed seed has limited
variation, and its battle examples are scouting screens rather than active
combat. Do not replace the navigation rules with this prototype.

On the first 56-frame seed, the prototype correctly classified 39 of 54
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
  --tasks data/labelstudio/review/curated/tasks_curated_screens_v2.json
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
