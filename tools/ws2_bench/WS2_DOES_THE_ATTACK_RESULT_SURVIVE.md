# Does the MonoNav patch result survive the plant finding?

Partly. The rate difference is real and large. Its causal pathway is not what
"transfer attack" implies.

## The comparison is not confounded by the plant

The plant is present in both arms, so a constant background cannot by itself
produce a clean/attacked difference. Restricted to MonoNav, layout `easy`,
isolating the patch from delay and noise:

| arm | n | pass |
|---|---|---|
| clean (no patch, delay or noise) | 203 | **58%** |
| patch only | 263 | **38%** |
| patch + delay and/or noise | 110 | 42% |
| delay and/or noise, no patch | 27 | 63% |

Fisher exact one-sided **p = 1.2e-05**, a 20 point drop. Delay and noise without
the patch do nothing (63%, n=27). The patch is doing the work.

## But every failure is the same object

| planner | collisions | at `WS2_plant/SM_Plant01` |
|---|---|---|
| MonoNav | 311 | **310 (100%)** |
| Kim | 81 | 52 (64%) |

Every arm fails in the same place, at the same point on the route:

| arm | collisions | at the plant | median contact x |
|---|---|---|---|
| clean | 81 | 81 | -2.46 |
| patch only | 158 | 157 | -2.54 |
| patch + delay/noise | 62 | 62 | -2.46 |
| delay/noise only | 10 | 10 | -2.54 |

The patch does not create a failure mode. It changes how often the vehicle
loses one gap, and the measured median clearance through that gap is **0.049 m**
(corridor A/B, control arm). The attack is an amplifier on a knife edge.

## No dose response

| patch size | n | pass |
|---|---|---|
| 0.30 m | 62 | 34% |
| 0.60 m | 34 | 18% |
| 0.90 m | 167 | **44%** |

Non-monotonic: the largest patch is the least harmful. An adversarial patch
should worsen with apparent size. **Caveat:** the search policies chose sizes
adaptively rather than randomising them, so cross-size comparison is confounded
by whatever else the policy varied. Suggestive, not conclusive.

## Taken together

- The patch was trained against FCRN (`config_depth_fcrn.yaml`), and MonoNav
  runs ZoeDepth. See `assets/patch_manifest.json`, which also declines to infer
  efficacy from the image.
- ZoeDepth is independently known to read bright near surfaces as far.
- There is no dose response.
- 100% of MonoNav collisions are one plant, cleared by about 5 cm when cleared.

The simplest account is: a bright, high-contrast object perturbs ZoeDepth a
little, and on a route where 5 cm decides the outcome, a little is enough. That
is a real and reportable effect. It is not evidence of an adversarial patch
defeating a planner, and it should not be presented as one.

## The decisive test cannot currently be run

The experiment that would settle it is the patch on a corridor-checked layout,
where clean passes 15/15 with ~0.9 m of margin. If the effect survives there it
is about the planner; if it vanishes it was about the gap.

That run is blocked by the capability model: from `a82d18182` the bench refuses
MonoNav with `patch_enabled`, because the patch is Kim's. Both positions are
defensible and they conflict. Resolving it is a decision, not an analysis:
either MonoNav+patch is a legitimate transfer experiment and the adapter should
permit it, or the MonoNav patch line of work is closed and the attack question
moves to Kim.

Kim is the matched target but is not ready for it: 64% of its collisions are the
same plant, and its clean failure rate is 66%.
