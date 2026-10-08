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

## Why: the envelope is 0.098 m too small, and that is the whole story

**This section originally blamed foliage. That was wrong, and the measurement
below refutes it.** The first draft argued that `overlap_sphere` fails against
thin leaf triangles and converges on the trunk, making the error
object-dependent. Measuring the vehicle showed a simpler cause.

`SceneOracle` now measures the farthest extent of the drone's own colliders
from its root origin:

```
measured_hull_radius_m = 0.3482      nominal envelope = 0.25
```

Two validation flights, both ending in contact with the plant:

| flight | surface distance at contact | clearance at contact |
|---|---|---|
| `finding2_easy0` | 0.3497 m | +0.0997 |
| `finding1_agent_round3` | 0.2747 m | +0.0247 |

The first collides at a surface distance of 0.3497 m against a measured hull of
0.3482 m, agreeing to 1.5 mm, and `0.3482 - 0.25 = 0.0982` against an observed
`+0.0997`. So `overlap_sphere` is returning the correct distance and the
reported margin is simply offset by the difference between the vehicle and the
assumed sphere. No foliage-specific blindness is needed.

It also explains the spread. The hull is not a sphere: 0.3482 m is the farthest
extent, an arm tip, while a head-on body contact happens nearer 0.25 m. Which
part touches first depends on approach geometry, so `clearance_at_contact`
ranges from about 0.00 to +0.12 across collisions, and a glancing contact whose
closest point beats the nominal radius reads slightly negative.

The error is therefore bounded and mostly explicable, not object-dependent.
That makes the metric fixable rather than unusable, which is the opposite of
what the first draft of this document concluded.

## Consequence for the continuous objective

`agent_policies._pair_score` and `compare_policies.method_result` were changed
earlier the same day to score the clearance an attack removed, on the argument
that Surrealist and the SBFT competition rank tests by distance to the nearest
obstacle rather than by pass or fail. That change stands for the reason it was
made: a campaign where every flight passes scores zero on every binary column,
and a continuous quantity gives a gradient where there was none. A paired
difference also cancels any constant bias.

It also does not stand, *as currently reported*, as a measure of how close a
flight came to crashing: zero is the wrong origin by about 0.098 m, so a
contact reads as comfortably clear. That is a calibration error, not a blind
spot, and re-basing on the measured hull largely fixes it:

| flight | reported now | with a 0.3482 m envelope |
|---|---|---|
| plant contact | +0.0997 | +0.002 |
| `finding1_agent_round3` contact | +0.0247 | -0.073 |

Collisions then read at or below zero, as they should.

## What would fix it

- **Done:** report the contact-time clearance next to the minimum, so a flight
  that collided at +0.12 is visibly not a flight that stayed 0.12 m clear.
- **Done:** measure the drone's actual collision extent and report it, so the
  reported margin can be compared against the vehicle.
- **Not done:** switch the reported envelope from the nominal 0.25 m to the
  measured hull, or report surface distance as the primary number. This changes
  every historical clearance value, so it needs a decision rather than a quiet
  edit. Note the hull is anisotropic, so even the measured radius is the
  conservative end of a range, not a single correct number.
- Dropped: the proposed foliage-specific closest-point query. The measurement
  above shows sphere overlap was not the problem.

Until then, treat `minimum_obstacle_clearance_m` as a relative stress proxy
between paired flights and never as a statement about whether a flight was
safe.

Evidence: `artifacts/ws2_plant_probe/` (archived per-frame planner views,
`samples.json` with the approach to contact), plus the clearance columns of
`artifacts/ws2_gate_validation/`, `artifacts/ws2_zoe_ab_{1,2,3}/`,
`artifacts/ws2_corr_probe/`.
