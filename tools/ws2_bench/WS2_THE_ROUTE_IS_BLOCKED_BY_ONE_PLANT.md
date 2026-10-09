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
