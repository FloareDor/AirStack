# Does a poster with no structure do the same thing?

The MonoNav patch effect was measured against no poster at all. This asks the
question that comparison could never answer.

## The gap this closes

MonoNav on `easy` seed 2, patch isolated from delay and noise:

| arm | n | pass |
|---|---|---|
| clean (no poster) | 203 | **58%** |
| learned patch | 263 | **38%** |

Fisher one-sided **p = 1.2e-05**. Two accounts fit that table equally well:

- **adversarial** -- the image carries structure optimised against a depth
  model, and enough transfers from FCRN to ZoeDepth to matter;
- **appearance** -- ZoeDepth reads any bright, saturated, high-contrast surface
  as further away than it is, and the route has a 5 cm margin, so a small
  perception error is sufficient.

Everything on record is consistent with both. The absent dose response and the
FCRN/ZoeDepth mismatch argue for appearance; neither rules out adversarial.
The comparison was always *patch vs nothing*, and "nothing" differs from the
patch in appearance and structure at once, so it cannot separate them.

A control poster holds appearance fixed and removes structure. The two accounts
then disagree: appearance predicts the control degrades MonoNav as much as the
patch, adversarial predicts it does not.

## The controls

`make_control_posters.py` derives all three from the learned patch itself, as a
pure function of its bytes and one seed, so each regenerates byte-identically
and its digest is checkable from a flight's provenance.

| poster | mean luminance | sd luminance | mean abs gradient | keeps |
|---|---|---|---|---|
| learned patch | 87.94 | 68.33 | 35.24 | -- |
| `phase_scrambled` | 87.94 | 76.08 | **53.29** | histogram + amplitude spectrum, phase replaced with noise |
| `pixel_shuffled` | 87.94 | 68.33 | **76.49** | histogram only |
| `flat_grey` | 87.81 | 0 | 0 | mean colour only |

Per-channel histograms of `phase_scrambled` and `pixel_shuffled` are *exactly*
the learned patch's, so mean and sd per channel match to the last bit; the
luminance sd differs only because the shared phase field changes how the
channels correlate.

**The controls carry more local edge energy than the patch, not less.** That
asymmetry is deliberate and it is what makes a null informative: if the learned
patch degrades MonoNav more than an image that is brighter-edged and equally
colourful, appearance alone does not explain the degradation. The controls are
never the gentler image, so they cannot flatter the patch.

## Why `easy` seed 2, and why the poster is genuinely seen

The poster hangs on the `-x` face of `WS2_column`. In `easy` seed 2 that puts
it at world `x = 0.82`, `y = -0.11`, `z = 1.2` -- within 11 cm of the flight
centreline, at exactly the 1.2 m flight height. The drone flies straight at it
from `x = -4`:

| drone x | range | bearing | angular size | px @1280/110deg |
|---|---|---|---|---|
| -4.0 | 4.82 m | 1.3 deg | 10.7 deg | 124 |
| **-2.5** | **3.32 m** | **1.9 deg** | **15.4 deg** | **179** |
| -1.0 | 1.83 m | 3.4 deg | 27.7 deg | 322 |

`x = -2.5` is where the collisions happen. The poster is dead ahead and about
180 px wide throughout the window in which the plant has to be perceived, so a
null here is a real null and not an exposure artefact. The corridor-checked
`generated` seed 42 layout was considered and rejected for this: its column
sits about 38 deg off-axis, where a null would be uninterpretable.

## The endpoint is not the pass rate

Separating 58% from 38% needs about **97 flights per arm** -- roughly three
workspace sessions. That cost is why this ablation has never been run.

MonoNav logs the per-frame RGB/depth edge correspondence (`zoe_corr`, MonoNav
`b8e5377`): the fraction of strong RGB edges that have a matching depth edge.
It falls precisely when ZoeDepth stops tracking scene structure, which is the
degradation both accounts are about, and it is continuous with tens to hundreds
of frames per flight.

Measured between-flight spread over 8 archived flights: mean **0.381**,
sd **0.0248**. At 12 flights per arm that resolves a shift of **0.030**
correspondence units, about 8% relative; the design flies **15**. So the
primary endpoint costs one session instead of three.

The unit of analysis is the **flight**. Frames within a flight are the same
scene a tenth of a second apart; pooling them would inflate n several
hundredfold and manufacture significance. `analyse_poster_ablation.py` compares
per-flight means with Mann-Whitney, checked against scipy in the tests.

Pass rates are recorded and reported as a **direction only**. Two interim
readings on this bench have already been withdrawn for being read as results at
low n.

## Design

Three arms -- `clean`, `fcrn_patch`, `phase_scrambled` -- 15 flights each, all
on `easy` seed 2 at patch size 0.9 m, interleaved round-robin with the order
rotating each round. Blocked arms cannot be told apart from a workspace
drifting under them, and this bench has already produced one effect
(pilot-10 `patch_090_timed`, p = 2e-08) that died against a time-adjacent
control. Rotating also stops one arm owning every first-flight-after-restart.
A part-finished run is balanced at every round boundary.

`pixel_shuffled` and `flat_grey` are registered and flyable but are not in the
default arm set; they are the follow-ups if `phase_scrambled` lands between
clean and the patch.

## This does not reopen the patch line

`patch_enabled` still means "run an adversarial patch against this planner's
depth model", is still gated behind `fcrn_patch`, and is still refused for
MonoNav. `a82d18182` is untouched, and a test asserts that granting the new
capability did not restore it.

`poster` is a separate axis that claims nothing about efficacy. It carries the
learned image only as one arm among its own controls, and a poster arm reported
without them would smuggle back exactly the claim the refusal exists to block.
A poster result is a **perception measurement**, not an attack result.

## How to read the outcome

| pattern | reading |
|---|---|
| control ~= clean, patch below both | structure matters; appearance does not explain it |
| control ~= patch, both below clean | appearance explains it; the patch does nothing an ordinary bright poster would not |
| all three ~= each other | no detectable perception effect at this exposure; the pass-rate difference needs another explanation |

## Results

Not yet flown. Campaign: `ws2-pilot-14`, `run_poster_ablation.sh`, output
`campaigns/poster_ablation`.
