# OSMO MonoNav qualified random baseline

Date: 2026-09-29  
OSMO workspace: `ws2-pilot-2`  
Campaign: `ws2_random_mononav_qualified`  
Planner: MonoNav  
Policy: random, with the built-in one-time confirmation of a clean-pass / attack-fail condition

## Result

The eight-flight pilot completed: four matched clean/attack pairs on the
clean-qualified `easy:2` layout, with seed 42. Every clean control reached the
goal. Two of the four attacked flights collided with the same Office plant early
in the flight. All eight flights recorded a ROS bag and completed cleanup with
no campaign or infrastructure errors.

| round | attack setting | clean | attacked | verdict |
| --- | --- | --- | --- | --- |
| 1 | 0.9 m patch, 10--15 s | goal, 44.28 s | goal, 43.53 s | pass |
| 2 | 0.3 m patch, 5--15 s | goal, 43.41 s | collision at 9.18 s | candidate failure |
| 3 | repeat round 2 | goal, 44.28 s | goal, 44.55 s | did not repeat |
| 4 | 0.9 m patch, 5--10 s | goal, 49.32 s | collision at 9.21 s | candidate failure |

All runs used zero added sensor delay and no RGB/depth noise. The collision
object was `/World/Office/WS2_plant/SM_Plant01` in both failures. The two
attacked collisions reached about 21% mission progress; their minimum measured
clearance was 0.76 cm and 1.31 cm respectively.

## Interpretation

This establishes a working, clean-qualified random baseline: the controls are
valid (4/4 goal reached), and the random policy found two attack conditions
that deserve follow-up. It does **not** establish general attack effectiveness
or reproducibility: the sample is four pairs on one fixed layout, and the
round-2 repeat passed. A later search-only run should use the same layout,
seed, and eight-flight budget; promising failures should then be repeated in a
separate confirmation run.

## Saved evidence

The non-bag campaign evidence was copied locally to
`tools/ws2_bench/artifacts/ws2_random_mononav_qualified/`. It includes the
campaign history, reports, configuration, per-round decisions, event logs,
metrics, and bag-verification records. The original ROS bags remain in the
OSMO workspace while it is available.

Exact action records and result JSON files are in the copied campaign
directory. The campaign output path on OSMO was:

`/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/ws2_random_mononav_qualified`
