# The clearance metric says "clear" on most collisions

Date: 2026-10-08. Workspace OSMO `ws2-pilot-12`. 28 flights, MonoNav, Office.

## The measurement

`minimum_obstacle_clearance_m` at its lowest point in each flight, split by
whether PhysX reported contact:

| | n | min | median | max |
|---|---|---|---|---|
| collided | 14 | -0.0223 | +0.0320 | **+0.1199** |
| did not collide | 14 | +0.0186 | +0.0378 | +1.0238 |

**12 of the 14 collisions reported a positive clearance.** The five plant
collisions report +0.114 to +0.120, meaning the oracle placed the nearest
surface 0.364 to 0.370 m from the drone's centre at the moment physics
reported contact with `/World/Office/WS2_plant/SM_Plant01`.

The medians are indistinguishable (+0.032 vs +0.038), and the ordering is
wrong in both directions: a flight reached **+0.019 without colliding**, while
others **collided at +0.12**.

## Why

`SceneOracle.clearance()` binary-searches `overlap_sphere` and subtracts a
nominal 0.25 m radius; its own `clearance_method` string says "not exact hull".
Two things follow, and both are true at once:

- The 0.25 m sphere is smaller than the vehicle's effective collision extent,
  so a positive margin is not a gap.
- `WS2_plant` is a reference copy of `/Root/SM_Plant8` with
  `MeshCollisionAPI` approximation `"none"`, an exact triangle collider. A
  sphere overlap test against thin leaf triangles fails to register at small
  radii, so the search converges on the trunk or pot further away while the
  real contact is with a leaf. That is why plant collisions report a *larger*
  clearance than wall collisions: the metric is measuring a different object
  from the one being hit.

So the error is not a constant offset that cancels. It is object-dependent,
and it is largest for the object that causes most collisions.

## Consequence for the continuous objective

`agent_policies._pair_score` and `compare_policies.method_result` were changed
earlier the same day to score the clearance an attack removed, on the argument
that Surrealist and the SBFT competition rank tests by distance to the nearest
obstacle rather than by pass or fail. That change stands for the reason it was
made: a campaign where every flight passes scores zero on every binary column,
and a continuous quantity gives a gradient where there was none. A paired
difference also cancels any constant bias.

It does **not** stand as a measure of how close a flight came to crashing.
Clearance is blind to foliage, and foliage is the dominant collision object
for both MonoNav and Kim (see the `WS2_plant` hits throughout
`artifacts/kim_flyable/history.json`). A search that maximises clearance loss
would steer away from the failures that matter most. The wording in the code
and in the comparison output was too strong and has been corrected.

## What would fix it

- Report the contact-time clearance next to the minimum, so a flight that
  collided at +0.12 is visibly not a flight that stayed 0.12 m clear.
- Measure the drone's actual collision extent and use it as the envelope
  instead of a nominal 0.25 m, or report raw surface distance and stop
  implying a safety margin.
- For foliage, prefer a closest-point query against the triangle mesh over a
  sphere overlap search, or give leaves a small collision thickness.

Until then, treat `minimum_obstacle_clearance_m` as a relative stress proxy
between paired flights and never as a statement about whether a flight was
safe.

Evidence: `artifacts/ws2_plant_probe/` (archived per-frame planner views,
`samples.json` with the approach to contact), plus the clearance columns of
`artifacts/ws2_gate_validation/`, `artifacts/ws2_zoe_ab_{1,2,3}/`,
`artifacts/ws2_corr_probe/`.
