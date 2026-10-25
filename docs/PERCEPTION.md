# Screen recognition and recovery

Current game actions use the bot's rule/template/OCR and action-specific
verification paths. The learned whole-screen classifier remains an optional
observer: it reports predictions without changing navigation, input, purchases,
or deployment decisions. Browser/CasaOS migration did not give it action authority.

## Shop, Settings and Clash Pass recovery

These pages have explicit `shop`, `settings` and `clash_pass` screen types. They can
interrupt either the donation or attack flow, so they are checked before the
older home, donation, and battle heuristics in every navigation mode.

The detector in `vision/auxiliary.py` checks small, fixed parts of the header:

- Shop: two of the current Shield, League and Treasure category icons. A selected
  tab enlarges its icon, so the other two provide evidence. The earlier header
  layout remains supported by its building, army and treasure templates.
- Settings: the Settings heading together with Music and Sound Effects labels.
  The Settings tab alone also appears on Inbox/Profile and is insufficient.
- Clash Pass: both the “Pass Rewards” and “Hoggy Bank” headings.

The small reference crops ship with the package in `vision/assets/`. No new
calibration or OCR installation is needed. Account details, purchases, season
names, reward contents, and currency balances are not part of these assets.
The current Shop and Settings crops were taken from the privately reviewed
`fresh_validation_20261024` development batch, resized to 960×540. They contain
only fixed category icons, labels and the close button; complete screenshots and
account details are not shipped with the application.
Captures are normalized to a small landscape reference size for matching;
the close button coordinates are converted back to the capture's actual size.
Portrait and very wide layouts are deliberately unsupported.

Recognizing a page does not automatically authorize a tap. A separate match
must find its red close X in the upper right, with a bright white X. This rejects
dimmed buttons underneath dialogs such as “Connection lost.” When the close
button is obscured or unverified, recovery takes up to three observations without
tapping, then logs that manual attention is needed. Conflicting page anchors
produce an uncertain observation. It does not click offers or purchase buttons.

`auxiliary_recovery.py` limits each recovery operation to three close attempts,
checks Stop immediately before a tap, and uses zero tap jitter. Navigation
treats Shop and Settings as provisional until the same page and close target
appear on two separately captured frames. Reusing the same image, changing
targets or persistent ambiguity cannot authorize input. Navigation
takes a new screenshot after each attempt and verifies the next screen before
opening chat or starting an attack. The same logic applies when returning from
an attack and confirming that clan chat can open.

This is a focused template-based fix, not a learned button detector. It has been
checked on the reviewed seed at the original size, 1280×720, and 1920×1080. A
future game redesign, different language, or rearranged header may require new
reference crops. The initial seed had only one reviewed Clash Pass example;
that historical coverage is not a count of the current private collection.

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

For visually reviewed screen labels and bounding boxes, use the
[annotation workflow](ANNOTATION_WORKFLOW.md). Its exports preserve source hashes
and sessions and explicitly distinguish AI-reviewed partial boxes from training
ground truth. Schema version 4 includes reward reveals, visited villages, army
confirmation/management, and upgrade menu, confirmation and in-progress states.

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

To compare a model in a source-launched browser server:

```bash
python -m coc_bot.web --screen-model data/models/screens.npz
```

Add the normal host/origin arguments for LAN use. To use the retained desktop:

```bash
python -m coc_bot.main --screen-model data/models/screens.npz
```

Activity messages such as `Screen observer (no actions): model=shop rules=shop
agree=True` appear at most once every five seconds. They go through the existing
rotating application log. The observer never changes the classifier's return
value, clicks, state transitions, or donation/attack decisions. A missing,
incompatible, or broken model disables observation while the normal rules
continue. Launch without `--screen-model` to leave observation disabled.

## Approved batches after a game update

Use `scripts/train_reviewed_screens.py` for a reviewed batch with image hashes,
recording sessions and a fixed UI version. First get approval of its screen labels.
Approval of screen labels does not approve partial object boxes for detector training.

```bash
python scripts/train_reviewed_screens.py \
  --batch data/labelstudio/review/REVIEW_current \
  --output data/models/EXPERIMENT \
  --ui-version YOUR_UI_VERSION \
  --approval-note "Screen labels reviewed and approved"
```

This refuses mixed/legacy UI versions, changed images, exact duplicates and existing
output directories. It saves a hash-linked approval record, dataset provenance,
an observation-only model and an evaluation report. Validation holds out complete
sessions, then removes training frames whose 63-bit perceptual hashes are within
six bits of a test frame. Similarity filtering reduces leakage but cannot establish
that every visual relationship has been removed. Classes absent from a fold's
remaining training data are explicitly unvalidated. Report evaluation coverage and
per-class results alongside overall accuracy; frequent classes can dominate accuracy.

The October 17 current-UI baseline used 100 approved screenshots across 15 categories.
It classified 84 of 91 eligible held-out examples correctly. Six categories had no
eligible independent test examples. Loading was 0/3 and popups 3/6, so those remain
priorities for collecting new examples. This is an experimental result from one
device, not a guarantee for new installations or unseen screen types.

For passive comparison while the bot runs, without restarting it or issuing any
game inputs:

```bash
python scripts/watch_screen_model.py \
  --collection data/collection \
  --model data/models/EXPERIMENT/screens.npz \
  --output data/models/EXPERIMENT/observer-run \
  --duration 3600
```

The observer reads newly saved collector images, not every video frame. It ends
after the requested duration and rotates its private comparison log. Optional
`--backfill 5` checks five previously saved frames before watching new saves;
these are marked as backfilled, not fresh validation data. Collector hints can be
inherited or incorrect, so agreement is not accuracy and disagreements need review.
Neither trainer nor observer changes calibration, settings, purchases or navigation.
Keep all models, approvals, evaluation logs and screenshots in the ignored data folder.

## Donation calibration proposals

The browser Setup editor has an optional **Suggest area** action for the donation
title, elixir resource button, troop/spell areas and troop/spell grids. This uses
`vision/donation_calibration.py`, a reference-based localizer independent of saved
calibration. It matches the Donation Resource title, both section headings and
the gem icon, checks title brightness, and locates the inspected layout relative
to those anchors. Only generic text/icon crops ship in the package; no account,
chat, full screenshot or private annotations are bundled.

This is not the learned whole-screen classifier or a trained general object
detector. Its first supported layout is the English seven-column panel with two
troop rows and one spell row. Missing or obscured anchors, heavily dimmed panels, clipped
proposed areas, unsupported aspect ratios and uncertain matches return no
suggestion. Other variants, especially troop-only/no-spell requests, need manual
selection and more labeled examples. A foreground overlay that leaves the
anchors visible may still escape these checks; inspect the full preview.

Suggestions refer to an immutable capture and its calibration revision. A stale
or expired capture cannot supply a proposal. Previewing issues no ADB input and
saves no settings/templates. The user checks/edits the box and grid counts, then
uses the existing transactional Save for that part, including its safety backup
and ownership checks. Refresh creates a new editor selection rather than carrying
old coordinates into the new frame. There is no batch auto-save. The donation
executor can also use this localizer as described below, without saving its
coordinates. The selected resource-state template, chat controls and other
calibration remain separate. In particular, a located elixir button is never
treated as proof that elixir mode is selected. Slot eligibility uses actual
color saturation; legacy saved color swatches are not needed by that detector.

### Automatic donation geometry

`donation/layout.py` represents a supported panel in original screenshot pixels.
At the start of each donation, the executor requires two matching observations
before using automatic troop/spell grids and the elixir-button center. Those
coordinates exist only for that request. They do not overwrite `calibrated.yaml`,
reference images, or shared configuration. An unsupported initial layout keeps
the existing calibrated workflow. A recognized panel that changes during the
second observation is refused instead of falling through to saved coordinates.

During an automatic donation, every slot tap gets a fresh capture. The executor
checks the panel geometry, the separately calibrated selected-elixir indicator,
and whether that slot is still colored before tapping its current center with
zero jitter. Swipes also require a fresh matching layout. A lost panel, changed
resolution/position, or failed resource verification invalidates the session;
saved grid coordinates cannot take over midway. The next request starts a new
check. Stop is checked after captures and before input.

This removes the saved grid and elixir-button-coordinate dependency for the
supported layout, not all calibration. It does not supply a selected-elixir
reference or detect every possible overlay. Chat navigation, unsupported layouts,
and the resource-state reference still need their existing setup. Readiness and
the checklist retain the fallback calibration steps. The per-tap screenshot
checks add capture latency. A successful executor return still reports that taps
were sent, not independent proof of the amount donated; capacity-delta validation
is a remaining step toward fully verified actions.

The October 24 offline check used 230 distinct, hash-verified reviewed images:
all six supported panels were localized and all 224 other screens were refused.
No saved grid, color, or tap calibration was loaded into the parser. On the
fresh request image, the only proposed taps were the available Electro Dragon
and Ice Golem cards. Thirteen runtime tests cover two-frame agreement, missing
resource calibration, resource changes, panel closure, stop during capture,
resolution/position changes, unavailable slots, and calibrated fallback. This
includes a simulated request that closes after the second tap. These results
are offline evidence from one device/layout, including a reference-source image;
they do not replace a live donation test or establish cross-device reliability.

A subsequent isolated live test on October 24 verified this executor against an
active request with saved grid areas, grid dimensions and elixir-button tap
coordinates removed from the test's in-memory configuration. The existing
selected-elixir reference remained required and was confirmed before every unit
tap. An Electro Dragon and Ice Golem changed the request from 0/50 to 35/50 and
then 50/50; after two troop-bar swipes, a Wall Wrecker donation closed the panel.
No further input taps were sent. Gems stayed at 698; elixir decreased by 99,000
and dark elixir by 360, matching the displayed unit costs. All 18 protected
calibration/template files retained their hashes. The working CasaOS package was
not replaced by this isolated test. Evidence remains private under
`data/debug/donation-layout-live-20261024/`. This confirms one real request on the
supported layout; it does not test spell donations or recovery from gem-selected
mode in this live run.

The October 19 proposal evaluation used a private fixed batch of 108 screenshots:
five previously reviewed panels and 103 other screens, including eight new
collector hints visually corrected from donation panel to battle/results. All
five panels produced proposals; all 103 negatives were refused. Troop-grid union
box overlap exceeded 99%, spell-grid overlap exceeded 98%, and elixir-button
overlap exceeded 96% against the existing AI-reviewed annotations. Those boxes
are partial labels, not independent ground truth. One of the five panels supplied
the generic reference crops, and all positives come from one device/layout.
This is limited proposal evidence, not a generalization or calibration-free claim.
Ten resized positive copies at 1280/1920 pixels wide also produced proposals;
ten dimmed/spell-heading-covered copies were refused. These mutations do not
count as independent sessions. A reference-matcher scan of 227 newer captures
found no additional candidates; that scan does not establish their true labels
or prove that no other donation layouts are present.

The subsequent real-panel deployment check exposed an overly strict absolute
brightness cutoff: an unobscured Waydroid panel rendered white title pixels at
178 rather than 255. The proposal-only check now accepts that lower-brightness
case while still requiring all four anchors, refusing the half-brightness test
and refusing an obscured anchor. This is not permission to act through a popup;
the user must inspect the full preview before saving.

Evaluate a hash-verified private batch without Android or a model-training step:

```bash
python scripts/evaluate_donation_suggestions.py \
  --batch path/to/private-batch \
  --output path/to/new-evaluation-directory
```

The batch's `manifest.json` is an array with `id`, `image` (relative to `images/`),
`sha256`, `session`, `screen`, and partial `boxes` (`label`, pixel `xywh`). Mark the
reference image with `reference_source: true`. The evaluator refuses changed
images, paths outside the batch, duplicate IDs, missing sessions/unreviewed screen
labels and existing output directories. It records refusals/acceptances and box
union overlap; it never promotes partial annotations to approved training data.
The new private review batch preserves the original captures and reviews.

To progress to a learned control detector, collect the missing current layouts,
complete and approve all visible instances of a fixed class set (including
partial/disabled controls or explicit ignore regions), and reserve independent
recording sessions for evaluation. Include Trade, popups, resource-mode changes
and negative pages. Keep the present manual editor as a fallback until that
detector has been validated. The existing screen-label approval alone does not
approve this separate object-training work.

## Offline checks

### Comparing experiment batches

Keep the current candidate unchanged while testing a new feature representation,
data addition, or recognition rule. Hold out complete recording sessions and
creators, and remove near-duplicate training frames before evaluating each fold.
Do not randomly split adjacent video frames. Verify the UI visually: a recent
upload can still contain old footage, comparisons, or edited mockups. Preserve
the source URL, license evidence, timestamps, original dimensions, crop, and
image hashes alongside each external batch.

Compare candidates on the same images, labels, and session groups:

```bash
python scripts/compare_screen_evaluations.py \
  --baseline previous/evaluation.json \
  --candidate experiment/evaluation.json \
  --baseline-data previous/dataset.json \
  --candidate-data experiment/dataset.json \
  --output experiment/regression-gate.json
```

Evaluation reports contain `predictions` with `id`, `session`, `expected`, and
`predicted`. Dataset arrays contain `id`, `screen`, `session`, and `sha256`.
IDs must be nonempty strings. The gate rejects changed benchmark identities,
missing cases, and any previously correct case becoming incorrect. New cases
are reported separately, so adding easier images cannot hide a regression.
An abstention is not counted as correct. Exit status 0 means the comparison
passed; it does not mean the candidate improved or is ready for deployment.
Check `improves_without_regressions` for an actual improvement. Existing report
files are never overwritten.

Historical cases inspected during development are regression tests, not an
untouched accuracy estimate. Also compare each revision against the last passing
candidate, and reserve new sessions for a final independent audit. Screen-label
approval does not approve object boxes or authorize gameplay actions.

### Experimental text evidence

`scripts/screen_text_evidence.py` is an **offline experiment**, not part of the
running screen detector. Its `recognize(frame)` function accepts a BGR screenshot
and returns optional screen evidence plus OCR diagnostics. It uses English
Tesseract text and layout anchors together: army headers with an unambiguous
Attack/Battle button, a logo with a Loading label, or a Connection lost dialog
with its explanatory text. Missing, conflicting, or timed-out OCR evidence
leaves the visual prediction unchanged. The helper does not receive filenames
or expected labels and cannot tap, deploy troops, or spend resources.

The October 24 offline experiment improved the fixed expanded development
benchmark from 247/260 to 251/260, with no previously correct cases becoming
incorrect. Three feature experiments and two data-addition experiments were
rejected because they introduced regressions. A separate set of 30 current-UI
frames from [Mythonz's October 18 video](https://www.youtube.com/watch?v=YHimtfaSq8c)
improved from 22/30 to 24/30 with the text helper. Those frames were inspected
before rule development, so that final result is not a blind validation score.
Their labels are assistant-reviewed, with no completed object annotations.
The source's displayed Creative Commons Attribution license and crop metadata
are retained in the private review batch.

OCR took a median 0.36 seconds and a 95th percentile of 0.68 seconds across 296
images in the constrained evaluation container (two CPUs, one GB RAM,
`OMP_THREAD_LIMIT=1`). That cost is additional to visual classification. The
experiment remains offline; it needs fresh-session validation and bounded,
selective invocation before any consideration for live use. The retained model,
calibration, and live navigation were not replaced by these experiments.

The subsequent October 24 live-server validation froze the helper and model
before collecting 35 new captures. Labels were visually reviewed and frozen
before inference. Both the visual model and the text-assisted candidate scored
31/34 identifiable frames, with no regressions and no improvements. One fully
black reload-transition frame was retained and marked unidentifiable before
scoring. Both versions recognized the real donation panel and army confirmation,
but missed two Shop layouts and classified Settings as a generic popup.

After grouping near-duplicates within that batch, both scored 23/26. Restricting
further to frames more than six perceptual-hash bits from the training set gave
14/17 distinct cases. No exact training-image duplicates were present. This is
one English-language device session, not broad validation; it includes no fresh
battle/results, matchmaking, live-replay, or reward-screen positives. OCR added
a median 0.39 seconds per frame. Deployment was held because this independent
batch showed no gain and exposed unresolved screen distinctions. The private
`fresh_validation_20261024` review batch preserves every image, hashes, frozen
labels/code, predictions, duplicate analysis, and the decision. It is validation
data, not automatically approved training data. If used to develop the next
candidate, reserve another untouched session for that candidate's final audit.

### Targeted recovery validation, 24 October 2026

The missed Shop/Settings frames became development data for fixed-anchor fixes,
not additional classifier training. The updated text-plus-anchor experiment
retained 251/260 historical predictions and 24/30 external-creator predictions,
with no correct-to-incorrect regressions; the 34 scorable development frames
improved from 31/34 to 34/34. No false Shop/Settings close targets were found in
those batches.

A newly captured 14-frame session improved from 10/14 visual-only labels to
13/14 with the first candidate. The remaining selected-Shield-tab miss prompted
the two-of-three category check. Five further screenshots were then captured
and labeled before inference, including Treasure and League Shop: the frozen
second candidate scored 5/5 versus 2/5 visual-only. This small, same-device sample
is a targeted regression check, not evidence of universal accuracy. It does not
establish performance on new languages, accounts or battle layouts.

Only the fixed menu recognition/recovery and home-camera recovery changes were
deployed. The learned model weights are unchanged and retain no action authority;
the experimental OCR combination remains offline. Real server tests verified
two-observation closing of Shop and Settings, home/clan-chat recovery and a
subsequent donation. The observed gem balance stayed at 698. Calibration and
settings hashes were checked against a verified pre-deployment backup.

Private evidence is retained under `recovery_validation_20261024` in the review
library, with candidate hashes, label freezes, development versus final-test
membership, regression reports and live-test logs. Full screenshots remain
outside Git. None of these assistant-reviewed labels automatically authorizes
adding the images to a training set.

### Screen-model retraining, 24 October 2026

After the targeted fixes, a separate offline run trained two new classifier
candidates. The existing 266-image current-UI dataset was hash-verified and its
247/260 session-held-out baseline reproduced before either candidate was scored.
The data additions were fixed in advance: three recent Shop/Settings frames,
then all 34 identifiable frames from the earlier live validation. The black
transition frame was excluded. New labels remain assistant-reviewed; the user's
training request does not turn them into independently human-verified labels.

The 269-image menu candidate retained 247/260 historical cases. On the 19 reserved
recovery captures it improved from 12/19 to 17/19, but newly confused the Inbox
page with Settings. On 30 external-creator frames it improved from 22/30 to 24/30
without a regression. The 300-image candidate improved recovery recognition to
18/19 but regressed on four historical cases (three upgrades in progress and one
popup), while fixing two others: the same historical cases fell to 245/260.
External-creator recognition stayed at 22/30.

Neither candidate passed all per-case regression checks, so neither replaced the
retained model. These are learned-model scores without the experimental OCR or
fixed-anchor overrides; do not compare them directly to the hybrid 251/260 score.
Whole recording groups were held out during cross-validation, with training
frames within six perceptual-hash bits of a held-out frame removed. All 49
recovery/creator evaluation images stayed outside final model training.

Those holdouts were previously inspected, and the recovery captures share a
device/day with the added training data. They are not a new blind accuracy test.
After excluding visually similar holdout frames, the menu candidate's recovery
score was 7/9 versus 6/9 before; the broader candidate scored 5/6 versus 3/6 before.
The differing denominators reflect different training sets, not deleted failures.

Candidate weights, metadata, frozen input hashes, runner and per-image reports
are stored privately under `data/models/screen_retrain_20261024`; screenshots and
weights stay outside Git. The run used an isolated container limited to two CPUs
and 1 GB RAM, with no network or write access to the live profile. No calibration,
gameplay configuration, observer selection or live model was changed. The next
training data should distinguish Settings from Inbox and upgrade confirmations
from upgrades already in progress, across independent recording sessions.

### Targeted collection and retraining, 24 October 2026

A follow-up collected and visually labeled 51 current-UI screenshots on the live
server. The first pass contains 34 captures, with 15 useful training examples
selected before fitting; navigation frames and redundant captures are preserved
but not automatically included. Examples distinguish Settings, Inbox/Social,
upgrade confirmations, and upgrades already in progress. No upgrade, purchase,
instant finish, or game-setting change was performed during collection.

Three data additions were frozen before training. The selected `targeted_core`
candidate uses 280 images: the existing 266, three earlier Shop/Settings captures,
and 11 new targeted examples. It improved the same 260 historical cases from
247 correct to 248, the 19 recovery cases from 12 to 18, and the 30 external-creator
cases from 22 to 24. None of those checks introduced a correct-to-incorrect
regression. Whole capture groups remain held out during cross-validation, and
perceptually similar training frames are purged from each fold.

After training inputs were frozen, a second pass collected 17 validation images,
including a different hero preview and another Builder's Hut upgrade level.
Their labels were frozen before inference and none entered training. The core
candidate improved from 14/17 to 15/17 without regressions. Both remaining errors
are More Settings pages. Among the 12 frames more than six perceptual-hash bits
from that candidate's training set, both models scored 10/12. Thus the new pass
supports a narrow menu improvement, not a demonstrated gain on visually distinct
screens. It shares an account and capture day with training and does not establish
accuracy across independent installations or battle layouts.

The 284-image and 315-image alternatives each scored 17/17 on the new pass, but
both regressed on historical and external-creator cases and were rejected. A
perfect score on one small batch does not override failures on existing cases.
All new labels are assistant-reviewed, not independently human-confirmed; this
is screen classification, not completed bounding-box annotation.

The selected candidate remains offline and observation-only. No live model or
navigation rule was changed. The bot was resumed, and hashes of 21 calibration,
configuration and template files matched their pre-collection values. Training,
reload, observer isolation and regression-gate checks passed. Private images and
labels are preserved under `data/labelstudio/review/targeted_training_20261024`;
weights, frozen inputs, scripts and per-image reports are under
`data/models/targeted_training_20261024`. These assets stay outside Git. Further
work should target More Settings versus generic popups while retaining all
existing regression checks and reserving a new capture session for final testing.

### More Settings refinement, 24 October 2026

The next collection added 36 visually reviewed screenshots across three passes:
More Settings at multiple scroll positions, main Settings, Inbox, Social and
navigation context. Nine first-pass examples were eligible for training. The
three initial candidates used two, seven or nine of them. All unrestricted
replacements introduced regressions, including a previously correct popup
becoming `loading`, and were rejected.

The retained experiment uses the previous 280-image `targeted_core` model as its
baseline and the new 287-image `spread` model as an optional refinement.
`scripts/screen_settings_refinement.py` permits only `popup` -> `settings` when
the refinement predicts Settings. All other baseline decisions are preserved;
an optional refinement failure also preserves the baseline. This constraint
does not prevent a real popup from being mislabeled as Settings, so popup
regression checks remain required. The wrapper is offline research code and is
not connected to screen classification, navigation or automatic dismissal.

Compared with `targeted_core`, the retained combination preserved every correct
case in the expanded historical check (257/276), recovery check (18/19) and
external-creator check (24/30). The earlier B pass improved from 15/17 to 17/17.
A new D pass improved from 5/9 to 8/9; three repeated menu-end captures had been
excluded before inference. One notification-settings view remained a popup.

That failure was explicitly promoted to development/training data for one final
candidate, ending D's status as untouched validation. The follow-up regressed
an older popup and was rejected. A separate 12-frame E pass, captured after the
models were frozen and labeled before inference, scored 12/12 for the retained
combination versus 7/12 for `targeted_core`. Among eight E frames more than six
perceptual-hash bits from its training set, recognition improved from 4/8 to
8/8. The retained model still misses D009; the perfect small E score does not
erase that known failure or establish reliability across accounts and languages.

Sixteen training, regression-gate and refinement tests passed. The private
`data/models/more_settings_20261024/retained_bundle` contains both model files,
metadata, the wrapper and a prediction entry point; it is not a single drop-in
`ScreenModel` file. Full candidate reports and rejected experiments are retained
alongside it. The 36 images and labels are preserved under
`data/labelstudio/review/more_settings_20261024`, outside Git. New labels remain
assistant-reviewed with no object boxes. The live model was not replaced. The
bot was resumed and all 21 protected configuration/template hashes matched.

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
