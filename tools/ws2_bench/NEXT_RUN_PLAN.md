# Next OSMO run: the continuous-patch lead, with controls that hold

## Why this run exists

The factor cells in pilot-9 put the continuous patch at the bottom of every
contrast, but they reach only p = 0.059 against the other conditions pooled,
and they cannot be scored against a clean baseline at all because no clean
control was flown in that workspace. This run closes that gap.

## The design

One clean arm serves every attack cell. `repeat_check.py --clean` flies the
clean twin with delay and patch forced off, so the control does not depend on
which attack it is paired with. It is flown in two halves, first and last, so
drift across a 12 hour session shows up as a disagreement between them rather
than quietly contaminating the attack cells.

| cell          | flights | configuration                         |
|---------------|---------|---------------------------------------|
| `clean_first` | 30      | clean twin, seed 42                   |
| `patch_090`   | 50      | continuous patch 0.9 m, no delay      |
| `patch_060`   | 35      | continuous patch 0.6 m, no delay      |
| `patch_030`   | 35      | continuous patch 0.3 m, no delay      |
| `clean_last`  | 30      | clean twin, seed 777                  |

180 flights, about 9 hours at 3 minutes each, plus roughly 1.5 hours of
workspace setup. That leaves about 1.5 hours spare in the 12 hour window.
All on scene `easy:2`, delay fixed at zero so patch size is the only variable.

Run order matters. The control goes first so the run is scoreable even if the
workspace dies early, then the largest attack cell, then the dose response.
The cheapest cell to lose is the last one.

## What it can show

With the clean arm pooled at n = 60 and `patch_090` at n = 50, a true attack
rate of 0.425 is detected with about 95% power, and 0.50 with about 80%. Below
roughly 0.55 the run is underpowered, which is worth knowing in advance: a null
result here means the effect is smaller than we thought, not that it is absent.

The dose response is the part that does not depend on a single p-value. If pass
rate falls monotonically from 0.3 m to 0.6 m to 0.9 m against a shared control,
that is mechanistic evidence a lone comparison cannot give.

## Before submitting

1. Commit and push the bench code. The pilot-8 campaigns ran against a working
   tree with uncommitted edits and the tree changed again mid-run, so those
   flights can never be reproduced.
2. Confirm the workspace checked out the pushed commit.

## After it finishes

Run the build check before quoting any number:

```
python3 tools/ws2_bench/check_provenance.py \
    artifacts/pilotN/clean_first artifacts/pilotN/patch_090 \
    artifacts/pilotN/patch_060 artifacts/pilotN/patch_030 \
    artifacts/pilotN/clean_last
```

It exits non-zero if the cells do not share one build, or if they do but the
source tree was dirty. A non-zero exit means the cells cannot be compared, and
no amount of sample size fixes that.

Then check `clean_first` against `clean_last`. If they disagree, the session
drifted and the attack cells are suspect regardless of what the build check says.

## The precedent

The pilot-8 ranker campaign had its AirStack tree change halfway through, at
round 11 of 20. It survived, because it flew a clean control beside every
attacked flight: the separation holds independently in both halves, p = 0.0055
in rounds 1 to 10 and p = 0.0230 in rounds 11 to 20, with an identical 0.80
clean rate in each. That is what paired controls buy. The pilot-9 factor cells
had a perfectly stable build and are still unscoreable, because they had no
control flown beside them.
