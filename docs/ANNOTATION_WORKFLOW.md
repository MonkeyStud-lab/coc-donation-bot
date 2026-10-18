# Screenshot annotation

Work on a fixed, copied batch rather than editing the live collector catalog.
Keep the original path, recording session and SHA-256 for every image. Screenshots
and exports remain private under `data/labelstudio/`; do not commit player names
or chat to GitHub.

## Review rules

Choose the screen by what is actually visible, not the collector's suggestion.
Use `reward_screen` for chest/reward reveals and `visiting_village` for another
player's village. Neither is a battle results screen. A popup is the primary
screen when it covers another page; its background controls are not actionable.

Use `army_confirmation` for the My Army screen with the final Attack action,
and `army_management` for the Cookbook/army editing page. The upgrade side menu
is `upgrade_menu`, a resource-start dialog is `upgrade_confirmation`, and an
already running upgrade with Finish Now is `upgrade_in_progress`. Recommended
entries alone do not prove a builder or the laboratory is available. Box the
visible builder/laboratory counters separately. Resource confirmation, magic-item
confirmation and gem-based Finish Now controls have distinct object classes.

Draw tight boxes around the visible button/control bounds, or the full panel for
an anchor. A disabled Donate button is still `btn_donate`; record its disabled
state in review notes. Do not box unseen controls at calibrated positions.
For layered dialogs, box only the foreground close button, not a dimmed X behind
it. `damage_indicator` is the overall-damage area; `star_indicator` is reserved
for actual stars.

The first pass labels recovery/navigation controls and selected screen anchors.
It deliberately does not label every army icon, resource number or purchase
button. These partial annotations must not be used as exhaustive object-training
labels: an unboxed object is not a confirmed negative.

## Export a reviewed batch

The batch contains `images/`, a `manifest.json` with image hashes, and
`annotations.json` with reviewed screen choices and pixel boxes:

```json
{"id":1,"screen":"home","boxes":[{"label":"btn_open_chat","xywh":[24,405,110,133]}]}
```

`annotations.json` is an array of these entries. Run with the project environment:

```bash
python scripts/export_reviewed_annotations.py --batch data/labelstudio/review/BATCH
```

This validates image hashes, schema labels and box bounds, then writes:

- `tasks_reviewed.json`: Label Studio screen choices and percentage-based boxes.
- `label_config.xml`: labeling interface matching the current schema.
- `previews/` and `review.html`: visual inspection of the boxes.
- `report.json`: coverage and corrected-suggestion counts.

Local-file URLs use the project's `data` directory as their document root.
When importing, keep source sessions intact. Split future training/evaluation by
recording session and image similarity, not randomly by adjacent screenshots.

## Game UI versions

Preserve pre-update work in a separate legacy batch; do not stretch old boxes onto
new screenshots or overwrite the old review. Each selected image should carry
`candidate_id`, `source`, `source_group`, `captured_at`, `ui_generation`
(`current` or `pre_update`) and a fixed `ui_version` (for example,
`2026-10-update`) in its manifest. The exporter preserves these fields
and the label schema version in Label Studio tasks and reports.

Keep current-layout and legacy exports separate. Start new UI evaluation with
the current batch. Legacy examples remain useful for regression checks and
unchanged semantic screens, but require an explicit compatibility check before
mixing them into a future training set. A game update date alone cannot decide
whether a particular screen is compatible.

Record corrected screen labels and selection/rejection reasons for every reviewed
candidate, including duplicates and animations. Leave the live collector catalog
and original images intact. Translucent donation-panel transitions should not
replace stable panels. A 1x speed control does not by itself establish a live
replay; inspect the rest of the battle HUD.

AI-reviewed batches explicitly retain `human_confirmed: false`,
`objects_complete: false` and `training_ready: false`. A human check and an
exhaustive pass over the chosen object classes are required before object training.
This exporter does not train a model, overwrite earlier labels or alter the bot.

The initial October 12 batch had 17 images and 48 boxes, with nine incorrect
screen suggestions corrected. The October 17 review adds positive donation-panel
and battle-results examples and the new upgrade screens. Continue prioritizing
normal/disabled Donate versus Trade, both resource modes, low-capacity donation
layouts, Surrender and Reload Game when collecting new examples. Missing variants
are coverage gaps, not confirmed negatives.
