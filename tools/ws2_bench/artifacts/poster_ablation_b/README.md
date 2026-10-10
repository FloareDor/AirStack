# poster_ablation_b — is it appearance, or structured contrast?

`ws2-pilot-14`, 2026-10-10, second arm set. MonoNav, `easy` seed 2, poster size
0.9 m, 45 flights, 15 per arm, interleaved. Same build and GPU as
`../poster_ablation`. Zero infrastructure errors.

Campaign A showed the learned patch and a phase-scrambled control degrade
ZoeDepth equally. The natural reading was "appearance explains it". **This arm
set refutes that reading.**

| arm | n | mean `zoe_corr` | diff vs clean | p | pass |
|---|---|---|---|---|---|
| clean | 15 | 0.3294 | -- | -- | 10/15 |
| `flat_grey` | 15 | 0.3315 | +0.0022 | 0.41 | 6/15 |
| `pixel_shuffled` | 15 | 0.3311 | +0.0017 | 0.51 | 4/15 |

Both null. `pixel_shuffled` carries the **identical per-channel histogram** to
the learned patch — same mean, same sd, same native RMS contrast (68.33) — and
does nothing. Identical colour statistics are therefore not sufficient.

The statistic that does predict the outcome is contrast surviving at the depth
network's sampling scale (~72 px of a 512-wide input):

| poster | native | 72 px | 32 px | degrades |
|---|---|---|---|---|
| learned patch | 68.33 | 60.44 | 48.45 | yes |
| `phase_scrambled` | 76.08 | 63.68 | 48.65 | yes |
| `pixel_shuffled` | 68.33 | 41.62 | 17.29 | no |
| `flat_grey` | 0 | 0 | 0 | no |

## Do not pool this with campaign A

The clean arms differ: 0.3354 (A) vs 0.3294 (B), **p = 0.028**, a gap 28% the
size of the patch effect. Same build, different sim restarts. Compare each arm
only against its own session's clean.

## One discrepancy

`pixel_shuffled` passed 4/15 against clean's 10/15 (Fisher p = 0.033) with no
`zoe_corr` effect. Pass rates here are direction only, and this is the shape of
the two interim readings already withdrawn on this bench. Recorded, not
claimed.
