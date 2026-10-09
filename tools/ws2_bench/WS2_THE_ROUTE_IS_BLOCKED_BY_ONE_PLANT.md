# One plant on the centreline explains most of the bench

Asked where the first principles for the scene were, checked, and found the
course was never validated against the route it is flown on.

## The finding

`/World/Office/WS2_plant/SM_Plant01` accounts for **362 of ~410 recorded
contacts** -- about three quarters of every collision this project has logged.
Contacts cluster at world **x = -2.50** (1.5 m after a takeoff at x = -4) and
world **y = +0.04**: the centreline. 348 of 362 are inside `|y| <= 0.9`.

That is not a stray obstacle. In the catalogue layouts the plant's nearest face
sits at `|y| = 0.00` for `easy` seeds 0, 1 and 3, and `0.05` for seed 2 -- the
seed the pilots used. The drone's measured hull radius is 0.3482 m, so the
straight-line route intersects the plant geometrically. Flying the centreline is
a collision, not a risk.

## Why the corridor did not catch it

`generated_layouts.valid_box` enforces a protected corridor, and its docstring
is explicit that this is "a qualification aid, not a planner guarantee". But
`realized()` only runs `validate_placement` when `layout == 'generated'`. Every
other layout name -- `easy`, `medium`, `hard`, `furnished_a`, `furnished_b` --
is read straight out of the hand-authored `layouts.json` catalogue and never
sees the corridor check.

Essentially all MonoNav data is `easy`. So the protected corridor has never
applied to the layout nearly every MonoNav result was measured on.

**Correction.** An earlier version of this file said "603 flights, 47% pass".
That pooled attacked flights into a figure it called a pass rate. Split:

| mononav, layout easy | n | pass |
|---|---|---|
| clean | 201 | **59%** |
| attacked | 399 | 41% |

So the clean baseline to beat is 59%, not 47%.

## What passing actually requires

The Office is rotated -90 degrees about Z, so `world_y = -source_x`. For `easy`
seed 2 the plant spans `y` in `[0.05, 1.59]` and the column `[-0.62, 0.40]`, at
different points along the route. `mononav_airstack.py` takes `min_dist2obs`
from argparse with default **0.8 m**, and the bench never passes the flag, so
clearing the column needs roughly `y <= -1.42` and the plant `y <= -0.75`.

Passing demands a committed lateral excursion of about 1.4 m. It is not a
straight corridor flight and never was.

## The drift question, answered backwards

The hypothesis was that crashes follow excess drift. The data says the inverse.

| MonoNav | n | median max abs(y), whole flight | median max abs(y), first 1.8 m |
|---|---|---|---|
| goal_reached | 36 | **1.60 m** | 0.07 m |
| collision | 25 | **0.33 m** | 0.33 m |

Flights that reach the goal drift *five times further*, because the detour is
the solution. Flights that crash stay near the centreline -- straight into the
plant. Matched over the first 1.8 m, the picture sharpens: successful flights
run straight early (0.07 m) and commit to the detour later, while crashers are
already wandering (0.33 m) before they get there.

So drift does predict the outcome, with the sign reversed from the guess: the
failure is **not drifting enough**.

## What this costs

The ~33% MonoNav and ~66% Kim clean failure rates are substantially a property
of the course, not the planners and certainly not any attack. Any attacked-vs-
clean comparison on these layouts is measuring an attack against a background
where the dominant failure is a centreline obstacle.

Kim is worse placed again: `hard` 0/16, `medium` 1/8, `furnished_b` 2/14.

## Not established

- Whether the plant was deliberately placed on the route as the obstacle to
  avoid. It is an avoidance benchmark, so an obstacle on the path is the point;
  what is wrong is that no feasibility check was ever run for the catalogue
  layouts, and `min_dist2obs = 0.8` was never reconciled with the geometry.
- Whether a wider corridor or a lower `min_dist2obs` raises the clean pass rate.
  That is one cheap experiment and it has not been run.
- The difficulty tiers are not identical; they share the first three placements
  and add objects (11 / 15 / 19 for easy / medium / hard).

## Measured: enforcing the corridor removes the clean failures

Interleaved clean-only A/B on ws2-pilot-13, 15 pairs, same build, MonoNav.

| arm | layout | plant face off route | pass | median min clearance |
|---|---|---|---|---|
| control | `easy` seed 2, from `layouts.json` | 0.05 m | **9/15 = 60%** | **0.049 m** |
| checked | `generated` seed 42, corridor-enforced | 1.32 m | **15/15 = 100%** | **0.903 m** |

Fisher exact, one-sided **p = 0.0084**; a 40 point difference.

The control reproduced its own history: 60% live against **59% (118/201)**
clean historical flights on that layout. That matters more than the p-value --
the rig behaved as it always has, so the 15/15 is not an artifact of the build
that introduced the oriented-box clearance basis.

Every control failure was a collision at 18-23% progress, i.e. at the plant
1.5 m in. No control flight ever cleared by more than 0.12 m.

(The run script printed "47% over 603 flights" as the baseline. That figure is
wrong -- it pooled 399 attacked flights. Clean is 59%.)

## The feasibility check that exists is calibrated to the wrong number

`challenge_layouts.free_route` -- Mason's newer sensor-challenge path, and the
only layout code that checks a route is flyable at all -- inflates obstacles by
**0.35 m**. That is the drone's physical half-extent and correct for asking
"does this collide" (measured hull 0.3482 m).

But `mononav_airstack.py` refuses any primitive within **0.8 m** of a TSDF
obstacle. So `free_route` can certify a route that MonoNav will not fly. The
feasibility check is calibrated to the vehicle's body; the planner is
calibrated to its own safety margin; they differ by more than 2x.

Catalogue layouts get no check at all, which is the larger gap, but closing it
by reusing `free_route` unchanged would not be enough.

## What this does and does not establish

Establishes: on this layout and seed, roughly 4 in 10 MonoNav "clean failures"
are geometry rather than planner behaviour or any attack, and every
attacked-vs-clean comparison in this project sits on that background.

Does not establish: that the plant is wrongly placed. This is an avoidance
benchmark and an obstacle on the path is the point. The defect is that the
catalogue layouts were never feasibility-checked against the planner's own
clearance requirement, so "clean failure" has been silently mixing two
different causes. One layout, one seed, one planner; not yet generalised.

## The mechanism is perception, not geometry

In `easy` seed 2 the **column** face sits at `|y| = 0.00` and the **plant** face
at `0.05`. Both are on the centreline. Of 311 MonoNav collisions ever recorded:

| obstacle | on the centreline | collisions |
|---|---|---|
| column (solid) | yes | **0** |
| plant (foliage) | yes | **311** |

So `min_dist2obs` is binding against the **TSDF map, not ground truth**. The
column registers in depth and is avoided on every single flight. The plant never
enters the map, so the planner has nothing to avoid and flies through it at a
measured 0.049 m.

That reframes the corridor A/B. Moving the plant 1.32 m off route did not give
the planner room to avoid it -- it removed the need to see it. The 60% to 15/15
jump is real, but the underlying defect is that **MonoNav cannot perceive the
plant**, not that the course is too tight.

This is a different claim from the foliage one withdrawn on 2026-10-08. That was
about the oracle's `overlap_sphere` missing thin geometry when *measuring*
clearance, and it was refuted by the hull measurement. This is about ZoeDepth and
the TSDF failing to *map* the plant, and its evidence is the column/plant split
above: same geometry, opposite outcomes.

## Mason's challenge scenes cannot be planned

`scene_feasibility.py` runs `challenge_layouts.free_route` with the inflation
radius as a parameter and reports the widest clearance a route can keep.

| challenge | vehicle fits (0.348 m) | planner can plan (0.8 m) | widest clearance |
|---|---|---|---|
| offset_obstacle | yes | **no** | 0.64 m |
| slalom | yes | **no** | 0.64 m |
| offset_gap | yes | **no** | 0.39 m |

All three use columns, which MonoNav *can* see. So the predicted outcome is not
a collision and not an attack signal: the planner finds no admissible primitive
and stops, the `planner_stopped` outcome that already exists 11 times at about
0.10 m travelled.

Flying these as-is would measure the clearance rule. They need gaps of about
`2 * 0.8` plus the vehicle, or a `min_dist2obs` chosen to match the scene.
`min_dist2obs` is now passed explicitly at its existing 0.8 default so it appears
in the worker command and provenance rather than being an invisible default.
