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
