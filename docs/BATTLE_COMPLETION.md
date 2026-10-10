# Recognizing a finished farm battle

After deploying the programmed army sequence, the bot now watches for the
results screen rather than always waiting for the entire timer.

It checks two fixed labels together: **Return Home** near the bottom centre,
and **Troops expended** above it. Both labels must match the bundled reference
images, have the expected relative positions, and the Return Home text must be
bright on a green control. This rejects a dimmed results screen under a popup.
The same target must appear in two consecutive successful observations, at
least one second apart. A missing or failed observation resets confirmation.

The detector is used only after a farm deployment. It does not change general
screen classification, donation recognition, matchmaking or startup navigation.
It does not use scenery, silhouettes, generic classifier guesses or the
experimental model to decide that an attack is over. It does not need OCR.

When results are confirmed, the bot taps the detected Return Home label with
no jitter, then uses the existing home/clan-chat confirmation. The log says:
`Battle results confirmed on two screenshots`.

If recognition fails, **Battle results fallback (seconds)** in Settings remains
the maximum wait from the original first-deploy timestamp. Its existing saved
value is preserved. At the deadline the bot still taps the calibrated Return
Home coordinates, regardless of the generic screen classifier. The log says:
`Battle timer done — forcing Return Home coordinates`.

Observations run on the attack's existing thread, approximately every five
seconds plus capture time. Each observation has one shared three-second ADB
budget, uses screenshot-and-pull, and never starts reconnects or retries. No
observation starts in the final four seconds before the fallback deadline.
Stop is checked before captures and taps, between ADB commands, and throughout
waiting. An in-progress ADB command can take up to the remaining capture budget
to return. Ordinary fallback capture and home confirmation retain their existing
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

The current corpus contains two real victory results screens and 54 non-results
screens; they passed at original resolution, 1280×720 and 1920×1080. The label
test does not depend on the Victory banner, but defeat and other results layouts
still need real examples. Different languages, UI scaling or a game UI update
may prevent a match. In those cases the timer fallback remains available.

To validate live, watch one manual farm attack in the GUI. Confirm the new log
appears only after the actual results screen, and that home/clan chat are reached.
Keep examples of both wins and losses for future offline checks. This initial
implementation has been tested offline; it is not a claim that every results
layout has been validated in a live battle.
