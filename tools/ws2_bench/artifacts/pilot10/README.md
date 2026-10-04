# pilot-10: the first campaign that passes its own comparability check

180 flights in workspace `ws2-pilot-10`, every one on worker image `44aadabe`
with both source trees clean. Scene `easy:2`, planner MonoNav, delay 0.0
throughout, so patch size is the only factor that varies.

```
python3 check_provenance.py artifacts/pilot10/*/
ONE BUILD, CLEAN TREES. These cells are comparable.
```

This is the first result here that is not a cross-build comparison. Everything
in `artifacts/pilot9/README.md` explains why that distinction took so long to
earn.

## Results

| cell        | pass  | rate  | 95% CI        |
|-------------|-------|-------|---------------|
| clean_first | 13/30 | 0.433 | 0.274 - 0.608 |
| clean_last  | 12/30 | 0.400 | 0.246 - 0.577 |
| patch 0.3 m | 6/35  | 0.171 | 0.081 - 0.327 |
| patch 0.6 m | 6/34  | 0.176 | 0.083 - 0.335 |
| patch 0.9 m | 5/50  | 0.100 | 0.043 - 0.214 |

`patch_060` shows 34, not 35. One flight ended in `infrastructure_error` and is
excluded from the denominator rather than counted as a failure.

## The control did not drift

`clean_first` ran before any attack cell and `clean_last` ran after all of them,
roughly nine hours apart in the same workspace. 0.433 against 0.400,
Fisher p = 1.000. The clean baseline is stable within a session, so the two
clean cells pool to 25/60 = 0.417 (CI 0.301 - 0.543).

This is the result that licenses every contrast below. Without it we could not
tell an attack effect from the baseline wandering.

## The patch works

| contrast                       | p         |
|--------------------------------|-----------|
| pooled clean vs patch 0.3 m    | 0.022     |
| pooled clean vs patch 0.6 m    | 0.022     |
| pooled clean vs patch 0.9 m    | 0.00021   |
| pooled clean vs pooled patch   | 0.000077  |

Pooled across sizes, a patch takes MonoNav from 0.417 to 17/119 = 0.143
(CI 0.091 - 0.217).

## It is a step, not a slope

No patch size is distinguishable from any other.

| contrast          | p     |
|-------------------|-------|
| 0.3 m vs 0.6 m    | 1.000 |
| 0.3 m vs 0.9 m    | 0.348 |
| 0.6 m vs 0.9 m    | 0.340 |

The campaign was designed expecting a dose response and did not find one. A
0.3 m patch does essentially all the damage a 0.9 m patch does. The dip at
0.9 m is inside the noise and should not be read as a trend.

Do not quote this as "larger patches are worse". The usable claim is that the
attack does not need a large patch, and that whatever threshold exists lies
below 0.3 m. Finding it needs a sweep at 0.1, 0.15 and 0.2 m.

## What this run cost

The first launch flew all 180 flights in four minutes, every one an
`infrastructure_error`, because the ZoeDepth weights were never downloaded. The
setup script followed the runbook's fenced block, and the warm-cache step was in
prose after it. About 20 minutes of a 12 hour window. Both the runbook and
`run_paired_cells.sh` were fixed before the relaunch; see commit
"Refuse to fly without the depth model".

## Known gap

These flights predate GPU capture, so `check_provenance.py` flags them
`GPU NOT RECORDED`. They all ran on one physical box, an RTX PRO 5000 Blackwell,
so the within-run contrasts hold. They are correctly refused against any later
run, because there is no recorded way to confirm the accelerator matched. See
commit "Record the GPU, because it is part of the build".
