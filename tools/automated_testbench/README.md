# AirStack automated trial runner

This runner turns the deterministic three-box Isaac Sim scene into isolated,
replayable MonoNav trials. A scenario is data; the execution layer owns stack
lifecycle; and result scoring is kept separate from later scenario search.

That division follows the useful boundary in Aerialist and Surrealist: the
runner executes and records one scenario, while a future generator may choose
new scenarios without gaining control over Docker, ROS 2, or PX4 lifecycle.
The implementation uses AirStack's existing non-interactive `airstack.sh`,
Docker, ROS domain, takeoff action, and timestamped-results conventions.

## Run one trial

From the AirStack checkout on the simulator host:

```bash
python3 tools/automated_testbench/run_trial.py \
  tools/automated_testbench/scenarios/medium_seed1.yaml
```

Validate and inspect the fully expanded scenario without changing the running
stack:

```bash
python3 tools/automated_testbench/run_trial.py \
  tools/automated_testbench/scenarios/medium_seed1.yaml \
  --resolve-only
```

## Run the initial campaign

```bash
python3 tools/automated_testbench/run_campaign.py \
  tools/automated_testbench/campaigns/initial.yaml
```

Trials run sequentially because this milestone uses one GPU, one PX4 instance,
and one executing external planner. A filesystem lock rejects overlapping
campaigns or individual runs.

Each perturbation has a clean twin with the same scene seed, mission, and
planner. Candidate autonomy failures are replayed three times before being
labeled reproducible; infrastructure errors are never autonomy failures.

## Random and TPE search

The read-only public WS2 bounds are in `threat_models/generic-ws2-v2.yaml`
(the current default). Generators see only this manifest and return typed
parameter maps; they never receive Docker, ROS, PX4, scoring, or cleanup
capabilities. Replace the file with CyLab's approved manifest when it is
handed off.

Each parameter declares a `role`: `scene` parameters (obstacle jitter, spawn
pose) are shared by both arms of a clean/attack pair, so the pair compares the
same scene with only the attack switched on or off; `attack` parameters
(lighting, sensor noise/delay) are reset to their `clean:` value in the clean
run. A parameter with no `role` defaults to `attack` (the conservative,
fail-safe choice). `threat_models/generic-ws2-v1.yaml` is kept, frozen, for
replaying older results — it predates `role` and every parameter behaves as
`attack` there, i.e. the clean twin resets obstacle positions too.

```bash
python3 tools/automated_testbench/run_search.py \
  tools/automated_testbench/scenarios/stock.yaml \
  --backend random --seed 17 --trial-budget 20

python3 -m pip install -r tools/automated_testbench/requirements-search.txt
python3 tools/automated_testbench/run_search.py \
  tools/automated_testbench/scenarios/stock.yaml \
  --backend tpe --seed 17 --trial-budget 20
```

TPE uses a SQLite study in the campaign directory, so running the same command
with `--campaign-dir <that-directory>` resumes it.

## Scenario contract

Each leaf scenario may `extend` one relative YAML file. The saved
`scenario.yaml` is always fully expanded and includes:

- the scenario ID and seed;
- MonoNav method, depth source, image, bridge, and planner arguments;
- the fixed spawn, 1.2 m takeoff, relative 8 m goal, and 1 m radius;
- an optional `scene` field (default `slalom`); randomization bounds plus
  every resolved obstacle pose and size (not applicable for scenes without an
  obstacle preset, e.g. `office`, which resolves with no obstacles);
- timeout, sampling, AirStack launch, and Docker/ROS settings;
- mission, planner adapter, clean environment, perturbations, repetition,
  oracle settings, threat-model version, and a canonical configuration hash;
- the measured post-takeoff start and resulting world-frame goal.

## Collision detection

The PhysX contact reporter watches every contact on the drone body, not a
per-scene obstacle allowlist, so it works unchanged in any scene once the
scene mesh has colliders (Isaac catalog scenes, including Office, get these
automatically at load via `scene_prep.add_colliders`). It arms once the drone
climbs above `oracle.collision.arm_altitude_m` (default `0.3` m, must stay
below `flight.takeoff_height_m`) so resting on the spawn floor isn't reported
as a collision; contact after arming — floor included — is a real crash.

**Known limitation:** scenes with no obstacle preset (currently `office`)
resolve with `obstacles: []`, so `minimum_obstacle_clearance_m` is always
`None` and the geometry-fallback oracle can never fire there. Collision
detection in those scenes is PhysX-only, with no clearance metric.

The obstacle resolver intentionally mirrors the exact `random.Random` call
order in `ws2_slalom_launch_script.py`. An empty seed preserves the legacy
stock geometry.

## Trial lifecycle and isolation

The runner performs these gates in order:

1. Verify the Docker daemon, MonoNav image, and both source checkouts.
2. Remove only the named old worker, bring the previous AirStack compose
   project down, and start a fresh Isaac Sim + robot stack with scenario env.
3. Require live containers, Isaac Sim, PX4, MAVROS, fresh odometry, and exactly
   one takeoff action server.
4. Start a fresh bridge and require advancing synchronized-frame sequence IDs.
5. Execute the takeoff action and require fresh post-action odometry.
6. Start a dedicated telemetry stream and headless MonoNav worker.
7. Monitor goal, geometry collision, planner terminal events, bridge health,
   telemetry freshness, and timeout.
8. Request hover, stop owned processes, collect current-run logs, and tear the
   stack down even after an error.

The fresh compose cycle, advancing timestamps, unique directory, owned process
handles, and Docker `logs --since` boundary prevent stale telemetry and log
reuse.

## Results

The default root is `/home/ubuntu/airlab-data/trials`. Every trial directory
contains:

- `scenario.yaml` — fully expanded input and resolved geometry;
- `result.json` — one outcome and computed metrics;
- `events.jsonl` — timestamped lifecycle, odometry, and planner events;
- `airstack.log`, `isaac-sim.log`, `robot.log`, `bridge.log`, `mononav.log`,
  `takeoff.log`, and probe/cleanup logs where applicable.

The only outcomes are `goal_reached`, `collision`, `timeout`,
`planner_stopped`, and `infrastructure_error`. Every schema-version 3 result
also has a `termination` object with a stable `source` and `reason`, the raw
terminal detail, and planner-specific context when available. For example,
planner stops distinguish `altitude_deviation` from `recovery_exhausted`.
Docker, Isaac Sim, PX4, ROS 2, bridge, takeoff, or stale-telemetry failures are
infrastructure errors; a healthy planner that exhausts recovery is
`planner_stopped`.

Path length integrates 3-D odometry at the configured sample rate. Time to goal
uses ROS message (simulation) time. Results capture AirStack/MonoNav commits,
container image IDs, seed, repetition, and configuration hash. PhysX contact
with a named test obstacle is authoritative whenever its ROS 2 heartbeat is
available. Geometry-derived clearance remains a metric and documented fallback
with configurable 0.1 m collision padding.

## Validation

Fast tests do not start Docker:

```bash
python3 -m pytest tests/test_automated_testbench.py -q
```

The two deliberate failure scenarios are excluded from the normal campaign:

```bash
python3 tools/automated_testbench/run_trial.py \
  tools/automated_testbench/scenarios/validation_bridge_unavailable.yaml

python3 tools/automated_testbench/run_trial.py \
  tools/automated_testbench/scenarios/validation_short_timeout.yaml
```

The first must produce `infrastructure_error`; the second must produce
`timeout`. Both still produce a complete result directory.
