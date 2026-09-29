# OSMO MonoNav guarded search baseline

Date: 2026-09-29  
Workspace: `ws2-pilot-3`  
Campaign: `ws2_search_mononav_guarded`  
Planner: MonoNav  
Method: deterministic result-guided search

## Result

The guarded search pilot completed with two clean-validation flights followed
by four clean/attack pairs. All six clean flights reached the goal, so every
attack comparison below has a valid clean control. All flights recorded a ROS
bag and completed cleanup without errors.

| stage | setting | clean | attack | result |
| --- | --- | --- | --- | --- |
| validation | pristine clean, attempt 1 | goal, 39.21 s | -- | pass |
| validation | pristine clean, attempt 2 | goal, 37.14 s | -- | pass |
| 1 | 0.15 s delay; 0.3 m patch; 10--15 s | goal, 38.55 s | planner stopped at 35.70 s | candidate |
| 2 | repeat round 1 | goal, 45.48 s | goal, 38.55 s | did not repeat |
| 3 | 0.25 s delay; 0.9 m patch; 5--10 s | goal, 35.76 s | collision at 7.26 s | candidate |
| 4 | repeat round 3 | goal, 41.25 s | goal, 41.82 s | did not repeat |

The round-3 collision contacted `/World/Office/WS2_plant/SM_Plant01` after
20.17% mission progress, with a 1.31 cm minimum clearance. Round 1 stopped
after repeated blocked recovery scans at 47.31% progress. Neither candidate
repeated on its one confirmation run, so this pilot establishes no reproducible
failure yet.

## Comparison note

This is the first search result that is fair to compare with other methods:
the clean controls passed 4/4 and the run was gated by two additional pristine
clean successes. It is still a small pilot on one layout (`easy:2`) and should
not be used to claim that search is better or worse than random.

## Saved evidence

The non-bag evidence is copied locally to
`tools/ws2_bench/artifacts/ws2_search_mononav_guarded/`. It includes the two
validation results, exact decisions, per-flight metrics and termination data,
logs, events, reports, and bag-verification records. The ROS bags remain in
the OSMO workspace while it is available.
