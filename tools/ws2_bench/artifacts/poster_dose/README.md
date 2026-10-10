# poster_dose — does the degradation scale with contrast?

`ws2-pilot-14`, 2026-10-10, third arm set. MonoNav, `easy` seed 2, poster size
0.9 m, 48 flights, 12 per arm, interleaved. Same build and GPU as
`../poster_ablation` and `../poster_ablation_b`. Zero infrastructure errors.

The dose posters keep the learned patch's exact spatial structure and mean
colour and scale only the amplitude, so the spectrum's shape is untouched and
scaling toward the mean cannot clip.

| arm | contrast | mean `zoe_corr` | diff vs clean | 95% CI | p |
|---|---|---|---|---|---|
| clean | 0 | 0.3350 | — | — | — |
| `contrast_25` | 17.11 | 0.3300 | −0.0050 | [−0.0121, +0.0021] | 0.112 |
| `contrast_50` | 34.12 | 0.3253 | −0.0098 | [−0.0157, −0.0038] | **0.0043** |
| `fcrn_patch` | 68.33 | 0.3187 | −0.0163 | [−0.0231, −0.0095] | **0.00059** |

Monotone across the ladder. Pairwise: `contrast_25` vs `fcrn_patch` p = 0.010,
`contrast_50` vs `fcrn_patch` p = 0.035. Linear fit over all 48 flights:
`zoe_corr = 0.3343 − 2.37e−4 × contrast`, slope **t = −5.41**, R² = 0.39.

`contrast_25` alone is not individually significant. The claim is the trend.

## Why a dose series and not a band-pass series

An 8-bit image at fixed mean cannot carry the patch's 68.3 contrast inside one
octave: the largest unclipped contrast is 21.9 (1–4 cyc/img), 17.3 (4–16) and
10.6 (32–64). Matching across bands means matching at 10.6, a sixth of what
produced the measured effect, where every arm would likely read null — and
allowing the clipping spreads energy back across the bands the filter was meant
to separate. The dose series tests the same hypothesis without that problem.

## Session comparability

This session's clean arm (0.3350) agrees with campaign A's (0.3354, p = 0.83).
Campaign B's differs from A's (0.3294, p = 0.028). The drift is episodic, so it
cannot be corrected for, only controlled against — every comparison here is
against this session's own clean.
