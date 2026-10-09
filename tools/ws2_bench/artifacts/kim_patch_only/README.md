
> **Correction, 2026-10-09.** The MonoNav patch result referred to below is
> withdrawn as an attack finding. The patch is Kim's: `assets/patch_manifest.json`
> records it as trained against `config_depth_fcrn.yaml` (FCRN), MonoNav runs
> ZoeDepth, and the bench now refuses MonoNav with `patch_enabled` (`a82d18182`).
> The rate difference is real (clean 58%/203 vs patch-only 38%/263,
> p = 1.2e-05) but **310 of 311 MonoNav collisions ever recorded are the single
> plant `WS2_plant/SM_Plant01`**, cleared by a measured 0.049 m when cleared, and
> the dose response is non-monotonic. The effect is a bright object perturbing
> ZoeDepth on a route where 5 cm decides the outcome -- not a patch defeating a
> planner. Kim's null below stands and is now the only patch result on the model
> the patch was made for. See `WS2_DOES_THE_ATTACK_RESULT_SURVIVE.md` and
> `WS2_THE_ROUTE_IS_BLOCKED_BY_ONE_PLANT.md`.

# Isolated patch cell for Kim (pilot-11, 2026-10-05)

8 pairs in which the learned patch is the **only** difference between the arms.
**Null.** Clean 3/8, attacked 2/8, discordant b=3 d=2, McNemar p = 1.000.

## Why this run exists

`kim_flyable` closed null at 30 pairs, but its cleanest cell was its smallest.
The random policy rarely draws `delay = 0`, so only 8 of its 30 pairs changed
the patch alone; every other perturbed arm moved the patch *and* the sensor
delay, and could never attribute an effect to the patch by itself. The specific
white-box claim therefore rested on 8 pairs.

`campaign.py --profile patch` zeroes `rgb_noise`, `depth_noise` and `delay`
(`campaign.py:42`), leaving the patch as the sole difference. The analysis
script checks this per pair rather than trusting the flag, and warns if anything
beyond `patch_enabled`/`patch_size` moved. No warning fired for any pair here.

## Result

```
000 easy:3  sz=0.68  clean=collision          pert=collision
001 easy:3  sz=0.85  clean=collision          pert=collision
002 easy:4  sz=0.89  clean=completed_horizon  pert=collision
003 easy:3  sz=0.51  clean=collision          pert=completed_horizon
004 easy:4  sz=0.62  clean=collision          pert=collision
005 easy:3  sz=0.80  clean=collision          pert=completed_horizon
006 easy:3  sz=0.76  clean=completed_horizon  pert=collision
007 easy:1  sz=0.54  clean=completed_horizon  pert=collision

clean  3/8 [0.14,0.69]      attack 2/8 [0.07,0.59]
discordant b=3 d=2          McNemar p = 1.0000
```

Patch sizes span 0.51 to 0.89 m, so this is not a single-size probe.

## Pooled with the isolated pairs from kim_flyable

`check_provenance.py` reports both runs on one build, one GPU and identical tree
hashes, so they compare directly.

```
                     n     clean    attack   b   d   McNemar p
kim_flyable          8     2/8      3/8      0   1   1.0000
kim_patch_only       8     3/8      2/8      3   2   1.0000
pooled              16     5/16     5/16     3   3   1.0000
```

Sixteen pairs in which only the adversarial patch differs, splitting exactly
evenly in both directions. This is as clean a null as this bench can produce at
this n.

## What it does and does not establish

It does establish that on the model the patch was trained against, with the
confound removed, there is no detectable effect at n=16, and that the earlier
`kim_flyable` hint of a delay-driven mechanism has nothing left to explain.

It does not establish that the patch is inert. n=16 bounds the effect loosely;
a small true effect would not be visible here. It also runs only on `easy`, with
a clean baseline of 3/8, so headroom is adequate but not generous.
`furnished_a` would have been the better family (7/13 in `kim_flyable`) but
`campaign.py --difficulty` draws its choices from `DIFFICULTY_COUNTS` and cannot
name it; widening that enum is the obvious next fix, since `DIFFICULTY_COUNTS`
does double duty as an object-count map and needs care.

## Bottom line

Across `kim_flyable` (30 pairs, all perturbation types) and this cell (8 pairs,
patch alone), Kim shows no measurable degradation from the patch it was the
training target for. The MonoNav result formerly called the only significant attack result in this
series is withdrawn; see the correction above.
