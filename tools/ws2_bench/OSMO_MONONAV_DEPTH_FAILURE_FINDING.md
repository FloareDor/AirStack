# MonoNav depth-perception failure behind the WS2 plant collisions

Date: 2026-09-29
Planner: MonoNav
Layouts: `easy:2` (two instances), `easy:0` (one instance)

## Summary

Every candidate attack failure found across the three completed OSMO baselines
(random, guarded search, agent-guided search) was a collision with the same
Office object, `/World/Office/WS2_plant/SM_Plant01`. None reproduced on a
one-time confirmation rerun, which looked at first like ordinary flakiness.
Pulling the saved RGB/depth/TSDF visualization frame from the instant of
collision in three separate incidents shows this is not noise: it is two
distinct, identifiable weaknesses in MonoNav's perception pipeline, one of
which is deterministically reproducible on the same layout.

This is a MonoNav robustness finding, not a benchmark artifact. Switching the
qualified layout away from `easy:2` does not avoid it -- the same collision
reproduced immediately on a different layout (`easy:0`) for a different reason.

## Finding 1: degenerate ZoeDepth output at a specific viewpoint (reproducible)

Two independent collisions, from two different OSMO campaigns run on different
days, both on layout `easy:2`:

- Random baseline, round 2, attack flight, collision at sim time 9.18s
  (see `artifacts/mononav_depth_failure_evidence/random_round2_attack_easy2_collision.jpg`)
- Agent-guided search, round 3, clean-twin flight, collision at sim time 6.57s
  (see `artifacts/mononav_depth_failure_evidence/agent_round3_clean_easy2_collision.jpg`)

Both saved frames show the identical camera composition: a white support
column directly ahead, the plant to its right, a hallway to the left. Both
show the identical failure in the ZoeDepth panel: instead of a depth map that
matches the visible geometry, the model outputs a near-uniform, banded
left/right/middle gradient with no correspondence to the real scene. The
white column, clearly close in the RGB frame, does not register as a near
obstacle at all. The planner's own `blocked` flag reads `False` on this exact
frame in both incidents, and the chosen motion primitive drives straight
through the column/plant.

Because this is the same camera pose producing the same wrong depth output
across two unrelated campaign runs, it is a deterministic failure of the
ZoeDepth monocular depth model at this specific viewpoint/lighting
combination on `easy:2` -- not a one-off rendering glitch.

## Finding 2: TSDF treats unmapped space as free (different layout, different cause)

A third collision, from a qualification attempt on layout `easy:0` (2026-09-29,
`ws2_qualify_easy0_retry2`, pristine clean validation, collision at sim time
35.6s, `easy:0` is not one of the three baselines' layout and was being
tried specifically to sidestep the `easy:2` plant):
see `artifacts/mononav_depth_failure_evidence/qualify_easy0_clean_collision.jpg`.

Here the saved frame shows no obstacle at all in the RGB view -- a plain
reception-desk hallway that looks clear. The ZoeDepth output for this frame is
plausible (not degenerate). But the TSDF top-view panel shows the chosen
motion primitive heading directly into a sparse, low-density gap in the
accumulated point cloud. The planner's sliding-window TSDF prunes aggressively
every frame (see `worker.log`, which reports `pruned=` counts in the tens of
thousands on nearly every frame); this collision is consistent with the plant
sitting in a blind spot that was never mapped, or was mapped and then pruned,
with the planner treating that unmapped gap as navigable rather than unknown.

## Why this explains the "unreproducible" candidates

Every prior baseline treated these collisions as one-off candidates that
"didn't repeat" on a single confirmation flight, and concluded the sample was
too small to say more. That conclusion was about statistical confidence in an
attack effect; it was never a claim that the underlying mechanism was random.
The evidence above shows a real, identifiable mechanism: MonoNav's avoidance
logic has no notion of "the depth read for this frame is untrustworthy" or
"this region is unmapped, not clear." Bad or missing perception is treated
identically to confirmed-clear space. Layout, seed, and attack condition
determine whether the drone's flight path happens to cross one of these
failure points, which is why the failure looks intermittent at the campaign
level while being fully deterministic at the frame level (Finding 1) or
structurally expected (Finding 2).

## Recommendation

This should be raised with Mason directly as a MonoNav finding, separate from
the WS2 benchmark's own random/search/agent comparison work. Two independent,
different fixes would address the two mechanisms: some form of depth-quality
or depth-consistency check that rejects degenerate ZoeDepth frames rather than
trusting them (Finding 1), and treating unmapped TSDF regions as
not-yet-confirmed-clear rather than free space (Finding 2). Both are
MonoNav-side changes; the benchmark's job here was to surface the failure
with reproducible evidence, not to patch the planner.

## Evidence

Three annotated collision-frame images (RGB input / ZoeDepth output / TSDF top
view, as saved by MonoNav's own `inference.jpg` visualization) are at:

- `artifacts/mononav_depth_failure_evidence/random_round2_attack_easy2_collision.jpg`
- `artifacts/mononav_depth_failure_evidence/agent_round3_clean_easy2_collision.jpg`
- `artifacts/mononav_depth_failure_evidence/qualify_easy0_clean_collision.jpg`

Full campaign evidence (configs, per-flight results, logs, bags where still
available) for the three underlying incidents is at:

- `artifacts/ws2_random_mononav_qualified/round_02/mononav/perturbed/attempt_0/`
- `artifacts/ws2_agent_mononav_guarded/round_03/mononav/clean/attempt_0/`
- `artifacts/ws2_qualify_easy0_retry2/clean_validation/attempt_0/`

## Addendum, 2026-10-08: the Finding 2 fix was flown and does not work

The Finding 2 recommendation above — treat unmapped TSDF regions as
not-yet-confirmed-clear — was implemented as `--max-unmapped-gap`, which
rejects a trajectory when any of its points has no observed voxel within the
gap. It was flown for the first time on 2026-10-08 against the three saved
scenarios, each with the gate on and off in the same workspace and build.

| scenario | gate off | gate on |
|---|---|---|
| `finding1_agent_round3` | `goal_reached` 93.8% | `planner_stopped` 0.0% |
| `finding1_random_round2` | `goal_reached` 93.9% | `planner_stopped` 0.2% |
| `finding2_easy0` | `collision` 22.3% | `planner_stopped` 0.0% |

The gate does prevent the one collision that reproduced, but it stopped every
flight at under 0.3 m travelled with all twelve yaw-scan recoveries consumed,
including the two that were about to succeed. A planner that never moves
cannot collide, so the apparent save on `finding2_easy0` is explained entirely
by the grounding and is not evidence that the gate recognised the hazard.

The mechanism is arithmetic. `known_tree` is built from weighted voxels, and
Open3D allocates blocks only in the +/-trunc band around an observed surface.
Here trunc is `trunc_voxel_multiplier * voxel_size = 8 * 3/64 = 0.375 m`, so an
observed voxel only ever exists near a surface, and "within 0.35 m of a mapped
voxel" means "within 0.725 m of a wall". Combined with `min_dist2obs = 0.5 m`
the two conditions admit only a 0.5 m < d < 0.725 m shell, and the open centre
of a 0.9 m corridor is rejected as unmapped precisely because it is open.

No value of the gap fixes this. The premise that distance to the nearest voxel
measures whether space has been observed is wrong, because the TSDF never
represents observed free space at all. The gate now defaults to 0 in both
`mission.defaults('mononav')` and the planner.

The recommendation itself still stands; only this implementation of it is
wrong. Observation should be tested against the depth image: project the
trajectory point into the current camera and require it to be inside the
frustum and nearer than the measured depth plus a margin. That is cheap and
does not conflict with `min_dist2obs`.

Two further notes from the same run:

- The Finding 1 degenerate-depth gate remains unexercised. Every frame of all
  six flights reported `depth_ok=True`, so that gate has still never been
  observed firing and is neither confirmed nor refuted.
- Two of the three saved collisions did not reproduce; their ungated flights
  reached the goal at ~94%. Single-flight replay cannot separate a fix from
  run-to-run variation, which is why `run_gate_validation.py` now defaults to
  three repeats. `finding2_easy0` did reproduce, and is a clean-condition
  collision with no patch and no delay, which makes it the most useful of the
  three.

Evidence: `artifacts/ws2_gate_validation/` (per-flight `result.json`,
`summary.json`, worker logs).

## Addendum, 2026-10-08: the Finding 1 gate was measured and carries no signal

The degenerate-depth gate never fired in 490 frames across the six-flight A/B,
including flights that collided, so it was neither confirmed nor refuted. The
detector computed its edge-correspondence value and logged only the verdict,
which made the gate unobservable; MonoNav `b8e5377` now logs the value, the
threshold, and the strong-edge pixel count.

Three flights of `finding2_easy0` with the gate on, 174 frames, all three
collided into `/World/Office/WS2_plant/SM_Plant01`:

| | probe_0 | probe_1 | probe_2 |
|---|---|---|---|
| correspondence min | 0.294 | 0.269 | 0.296 |
| median | 0.407 | 0.382 | 0.388 |
| max | 0.546 | 0.563 | 0.494 |
| frames below the 0.12 threshold | 0/74 | 0/71 | 0/29 |
| smallest margin above threshold | 2.4x | 2.2x | 2.5x |
| `zoe_edges` median | 46046 | 46041 | 46044 |

Three candidate explanations for the silence, and what the data says:

- **Opting out on low texture.** Ruled out. `min_edge_pixels` is 300 and these
  frames carry about 46,000 strong RGB edge pixels, so every frame was
  evaluated.
- **Mistuned threshold.** Ruled out. The smallest value seen is 0.269, more
  than twice the threshold. This is not a near miss.
- **The statistic carries no signal.** Supported. The correspondence does not
  dip at the failure: the last five frames before contact are 0.354-0.442,
  0.383-0.468 and 0.300-0.312, at or above each flight's own median. Frames
  driving into the plant look like frames flying down an empty corridor.

That is a stronger result than mistuning. Firing on the worst collision frame
needs a threshold above 0.269, while healthy frames in the same flights reach
0.563, so **no threshold separates the two**. Raising it to catch the collision
would reject most good frames; 0.12 catches nothing.

A whole-frame edge-correspondence statistic cannot detect a depth failure
confined to one object. The gate's own docstring names the intended target as
"a close column/plant", which is exactly a localized failure, so the
implementation does not match its stated purpose.

What would: a spatially local test. Either per-region correspondence, so a
block of the image that disagrees with its RGB raises a flag regardless of the
rest of the frame, or a per-primitive check that compares the depth measured
along a candidate trajectory against what the TSDF predicts there. Both are
local by construction. Neither has been implemented or flown.

The gate is left on at 0.12, because it demonstrably changes nothing and
removing it would be an unreviewed behaviour change, but it should not be
described as a mitigation for this failure.

Evidence: `artifacts/ws2_corr_probe/` (per-flight `result.json`, `worker.log`
with `zoe_corr` on every frame).
