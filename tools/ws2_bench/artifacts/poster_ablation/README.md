# poster_ablation — does a structure-free poster do the same thing?

`ws2-pilot-14`, 2026-10-10. MonoNav, `easy` seed 2, poster size 0.9 m,
45 flights, 15 per arm, interleaved round-robin with the order rotating each
round. One build, one GPU, **zero infrastructure errors**.

Full writeup and method: `../../WS2_DOES_A_CONTROL_POSTER_DO_THE_SAME.md`.

## Result

| arm | n | mean `zoe_corr` | sd | pass |
|---|---|---|---|---|
| clean | 15 | 0.3354 | 0.0065 | 8/15 |
| `fcrn_patch` (the learned patch) | 15 | 0.3138 | 0.0058 | 3/15 |
| `phase_scrambled` (control) | 15 | 0.3172 | 0.0069 | 6/15 |

Mann-Whitney over per-flight means: clean vs patch **p = 3e-06**, clean vs
control **p = 1.1e-05**, patch vs control **p = 0.245**.

Differences, 95% CI: clean−patch +0.0216 [+0.0170, +0.0262]; clean−control
+0.0182 [+0.0132, +0.0232]; **control−patch +0.0034 [−0.0013, +0.0082]**.

**The structure-free control reproduces 84% of the learned patch's
degradation and the remainder is indistinguishable from zero.** Appearance,
not adversarial structure, accounts for the effect. At least 62% is appearance
alone on the CI's conservative end.

## Reading this directory

- `analysis.json` — the authoritative result. Per-arm statistics, all pairwise
  comparisons, and **the per-flight `mean_zoe_corr` values the whole finding
  rests on**. The raw per-frame lines live in each flight's `worker.log`, which
  is not committed per the artifacts convention, so this file is what preserves
  the endpoint.
- `summary.json`, `config.json`, `flights.json` — campaign-level records,
  including the per-arm `configuration_hash` and the flight order actually
  flown.
- `NNN_<arm>/result.json`, `provenance.json`, `scenario.json` — per-flight
  audit trail. `provenance.poster` names the texture and its sha256, so any
  flight can be checked against the image it actually rendered.

## What makes this readable as evidence

Each poster arm used **exactly one** texture digest across all 15 flights:
`fcrn_patch` = `5b152747…` (the registered Rui patch), `phase_scrambled` =
`31e96753…` (regenerable byte-identically via `make_control_posters.py
--check`). The clean arm recorded `poster: null`.

Every flight ran with `patch_enabled: false`. The posters were flown on the
non-attack `poster` axis; the `fcrn_patch` attack capability remains refused
for MonoNav. **Nothing here is an attack result.**

The clean arm passed 53% against 58% over 201 archived clean flights on this
layout, so the rig behaved normally. Pass rates are a direction only at this n
and are not the endpoint.
