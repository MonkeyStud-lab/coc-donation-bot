# Recognizing a finished farm battle

After deployment, the programmed, planner and automatic attack methods watch
for the results screen rather than always waiting for the entire timer.

It checks two fixed labels together: **Return Home** near the bottom centre,
and **Troops expended** above it. Both labels must match the bundled reference
images, have the expected relative positions, and the Return Home text must be
bright on a green control. This rejects a dimmed results screen under a popup.
The Troops expended reference uses only the title's 13-pixel-high text region
at normalized resolution. A gold-color mask and small blur tolerate subpixel
text edges. Village scenery and army portraits below the text are excluded;
their changes previously caused genuine victory and defeat screens to be missed.
The same target must appear in two consecutive successful observations, at
least one second apart. A missing or failed observation resets confirmation.

The detector is used while waiting for an entered farm battle to finish,
including safe cleanup when a survey cannot authorize deployment. It does not change general
screen classification, donation recognition, matchmaking or startup navigation.
It does not use scenery, silhouettes, generic classifier guesses or the
experimental model to decide that an attack is over. It does not need OCR.

When results are confirmed, the bot taps the detected Return Home label with
no jitter, then uses the existing home/clan-chat confirmation. The log says:
`Battle results confirmed on two screenshots`.

If recognition fails, **Battle results fallback (seconds)** in Settings remains
the maximum wait from the recorded deployment-start timestamp. The saved value
is preserved. Planned and automatic attacks measure this
deadline from the first verified deployment (or the first uncertain tap), while
the legacy sequence records its start before replay. At the deadline the bot still taps the calibrated Return
Home coordinates, regardless of the generic screen classifier. The log says:
`Battle timer done — forcing Return Home coordinates`.

Observations run on the attack's existing thread, approximately every two
seconds plus capture time, with a one-second confirmation interval after a
possible result is found. Each observation has one shared three-second ADB
budget, uses screenshot-and-pull, and never starts reconnects or retries. No
observation starts in the final four seconds before the fallback deadline.
Stop is checked before captures and taps, between ADB commands, and throughout
waiting. Active ADB subprocesses also poll for cancellation and are terminated
when Stop is requested; the shared capture budget bounds failed observations.
Ordinary fallback capture and home confirmation retain their existing
timeouts. The two polling intervals mean early completion is not instantaneous.

## Validation and limitations

Run:

```bash
python scripts/verify_battle_completion.py
```

For the reviewed dataset, add `--tasks path/to/tasks.json --data-dir data`.
Checks include simultaneous labels, brightness, green scenery, missing labels,
two-frame confirmation, transient results, the fallback deadline with slow or
failed captures, Stop, and bounded capture behavior. No game commands are sent.

The initial reviewed corpus contained two real victory results screens and 54 non-results
screens; they passed at original resolution, 1280×720 and 1920×1080. The label
test does not depend on the Victory banner. The current lettering fix also covers
the real defeats described below. Different languages, UI scaling or a game UI update
may prevent a match. In those cases the timer fallback remains available.

To validate live, watch one manual farm attack in the GUI. Confirm the new log
appears only after the actual results screen, and that home/clan chat are reached.
Keep examples of both wins and losses for future offline checks. The lettering
fix passes recent real victory/defeat examples at three resolutions and rejects
a real reward popup. The expanded reviewed corpus passes two results and 195
non-results screens at three resolutions. Additional layouts and languages still
need validation.

The October 18, 2026 live check confirmed results on two fresh screenshots and
tapped Return Home approximately 46 seconds before the configured fallback.
Home, camera zoom restoration and clan chat were subsequently confirmed. Earlier
test runs exposed the scenery-dependent label failure and sparse-home matching
problems; those failures were not counted as successful acceptance runs.

Each completed wait keeps one `data/debug/battle-end-confirmed.png` or
`battle-end-fallback.png`. A visible Return Home label with conflicting evidence
can also overwrite `battle-end-uncertain.png`. DEBUG events explain rejected
observations. These files are bounded diagnostics, not a growing video archive.

If the fallback tap misses, recalibrate **Setup → Farm → Return Home** on a real
results screen. Extending the timer will not correct a misplaced tap.

Interrupted-attack recovery uses the same two-label results detector but never
the timer fallback. It waits up to four minutes and pauses if results cannot be
verified. See [attack recovery and storage](ATTACK_REBUILD.md#interrupted-attacks-and-diagnostic-storage).
