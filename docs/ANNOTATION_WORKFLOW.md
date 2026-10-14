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

AI-reviewed batches explicitly retain `human_confirmed: false`,
`objects_complete: false` and `training_ready: false`. A human check and an
exhaustive pass over the chosen object classes are required before object training.
This exporter does not train a model, overwrite earlier labels or alter the bot.

The initial October 12 batch has 17 images and 48 boxes, with nine incorrect
screen suggestions corrected. It has no confirmed positive donation-panel or
battle-results example; prioritize those in the next batch rather than relying
on mislabeled reward screenshots. Include normal/disabled Donate, Trade,
elixir/gem selection, low-capacity donation layouts, Surrender and Reload Game.
