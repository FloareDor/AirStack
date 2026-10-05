# Kim paired campaign on flyable layouts (pilot-11, 2026-10-04/05)

32 pairs, 65 flights, one build, one GPU. **The result is null.** The learned
patch does not measurably degrade Kim et al. on the layouts Kim can actually
fly.

This is the matched target. The patch was trained against `config_depth_fcrn.yaml`
and Kim runs `--depth-source fcrn`, so this is the white-box case where the
attack should work best. MonoNav, where the attack does reach p = 0.000077, runs
ZoeDepth and is therefore a transfer setting.

## What was flown

`agent_campaign.py --policy random --planner kim --budget 64 --seed 43`, drawing
from `furnished_a`, `furnished_b`, `easy` (seeds 0-7). Each round flies the same
layout twice, clean and perturbed, so layout difficulty cancels within the pair.
Analysis is by pair. Pooling flights would reintroduce the confound the paired
design exists to remove.

Ran 22:56 to 04:43 UTC on `ws2-pilot-11`.

## Result

```
                        n     clean           attack          b   d   McNemar p
ALL                    30   12/30 [.25,.58]  11/30 [.22,.54]  5   4   1.0000

easy                   10    5/10 [.24,.76]   3/10 [.11,.60]  2   0   0.5000
furnished_a            13    7/13 [.29,.77]   6/13 [.23,.71]  3   2   1.0000
furnished_b             7    0/7  [.00,.35]   2/7  [.08,.64]  0   2   0.5000

patch only (delay=0)    8    2/8  [.07,.59]   3/8  [.14,.69]  0   1   1.0000
patch + delay          21   10/21 [.28,.68]   8/21 [.21,.59]  5   3   0.7266

continuous patch        7    3/7              4/7             1   2   1.0000
timed patch            22    9/22             7/22            4   2   0.6875
```

`b` = clean passed and the attack failed. `d` = the reverse. Only discordant
pairs carry information. Intervals are Wilson score. Two pairs were dropped and
are reported, not hidden: one had an `infrastructure_error` arm, one had
identical arms.

Clean 0.40 against attacked 0.37, with b and d almost equal, is nothing.

## An interim reading that did not survive

At 18 pairs this run showed b=5, d=1, p=0.22, and the attribution split showed
all discordance in pairs that also perturbed sensor delay, with every
patch-isolated pair concordant. That looked like a delay effect masquerading as
a patch effect.

The following 11 pairs contributed b=0, d=3 and erased it. `patch + delay` ended
at p = 0.73, so there is no effect to attribute to anything. **The 18-pair
reading and the delay story built on it are both withdrawn.** They are recorded
here because the interim was reported, and a retraction that is not written down
is not a retraction.

This is the second time in this campaign series that a directional interim
dissolved. The first was the `patch_090_timed` cell in pilot-10. The general
lesson is that at these n, a two-to-one discordant split is routine noise.

## Why this is a real null and not a broken run

`check_provenance.py`: one build across all 65 flights, one GPU (RTX PRO 5000
Blackwell), so no cross-build swing. Exit 0.

`check_drift.py`: six time-ordered blocks of clean flights spanning the whole
run, pass rates 0.300 to 0.500, permutation p = 0.9883 over 20000 shuffles. The
clean baseline did not move. Exit 0. A drifting baseline cannot explain this
null, and that mattered: it is exactly what invalidated the pilot-10 timed cell.

The trees are **dirty**: this run carries the layout action-space fix that was
uncommitted when it launched. That fix is now committed, so a clean checkout at
or after `a3ac19060` should reproduce the code, but the recorded
`diff_sha256` will not match a clean tree and the run is not bit-reproducible as
recorded.

## Caveats that limit the claim

- **`furnished_b` has no headroom.** Clean 0/7. Seven of 30 pairs could not have
  shown an attack effect. Object counts in `layouts.json` order the families
  furnished_a(6) < furnished_b(7) < easy(11), so `furnished_b` was expected to be
  easy and is not. Geometry matters more than object count, and the earlier
  `kim_layout_audit` ordering should not be trusted as a difficulty proxy.
- **`patch only` is n=8.** The cleanest test of the actual white-box claim is
  the smallest cell here, because the random policy rarely draws delay = 0. This
  is the gap worth closing: `campaign.py --profile patch` zeroes noise and delay
  and would fill it directly, though `--difficulty` cannot currently select
  `furnished_a`, which is the only family with a solidly live baseline.
- A null at n=30 bounds the effect; it does not prove its absence. The interval
  on the paired difference is wide.

## Honest one-line summary

On the model the patch was trained against, there is no measurable attack
effect at n=30 pairs; the significant MonoNav result is a transfer attack on a
different depth backbone.
