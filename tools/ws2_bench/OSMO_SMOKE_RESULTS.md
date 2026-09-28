# OSMO MonoNav smoke results

Date: 2026-09-28
Workspace: `ws2-smoke-20`
Scenario: `search round 1 mononav`

This was the first completed clean/attack pair after fixing the OSMO setup and
two MonoNav issues. Both flights reached the goal, recorded a ROS bag, and
finished cleanup without errors.

| condition | outcome | sim time to goal | path length | min clearance | planner holds | recovery scans |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| clean | goal reached | 43.44 s | 8.409 m | 0.0857 m | 1 | 0 |
| timed patch attack | goal reached | 41.40 s | 8.386 m | 0.0338 m | 0 | 0 |

The patch was active from simulator time 48.13 s to 53.11 s. The attack run
had lower minimum clearance (3.4 cm versus 8.6 cm), but it also reached the
goal. One pair is only a smoke result: it confirms the workflow works; it does
not establish that the patch causes a reliability or safety problem.

## Run details

### Clean

- result directory: `robot/ros_ws/ws2_runtime/campaigns/osmo_clean_turn_fix_3`
- configuration hash: `43d2c85ed7a1241fb9f0c520ba586365da6fd12582309e0821aaecd1144a81ef`
- termination: `planner/goal_region`
- final goal distance: 0.4924 m
- mission progress: 93.82%
- ROS bag recorded: yes
- cleanup errors: none

### Timed patch attack

- result directory: `robot/ros_ws/ws2_runtime/campaigns/osmo_attack_turn_fix_2`
- configuration hash: `d8a196d288cbcea2e280f94f5a2693eab7be6347362534405a06002fe753ad08`
- termination: `planner/goal_region`
- final goal distance: 0.4871 m
- mission progress: 93.86%
- ROS bag recorded: yes
- cleanup errors: none

## What was fixed before these runs

1. MonoNav no longer treats safe outer turn primitives as recovery scans.
2. MonoNav safely handles an empty initial depth/TSDF map instead of crashing.

## Next step

Run the MonoNav random baseline: four matched clean/attack pairs (eight
flights), using the saved layouts and the same reproducible OSMO environment.
After that, run the same-size search-only and agent-plus-search pilots.
