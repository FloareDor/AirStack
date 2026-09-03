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

## Scenario contract

Each leaf scenario may `extend` one relative YAML file. The saved
`scenario.yaml` is always fully expanded and includes:

- the scenario ID and seed;
- MonoNav method, depth source, image, bridge, and planner arguments;
- the fixed spawn, 1.2 m takeoff, relative 8 m goal, and 1 m radius;
- randomization bounds plus every resolved obstacle pose and size;
- timeout, sampling, AirStack launch, and Docker/ROS settings;
- the measured post-takeoff start and resulting world-frame goal.

The obstacle resolver intentionally mirrors the exact `random.Random` call
order in `example_one_px4_pegasus_launch_script.py`. An empty seed preserves
the legacy stock geometry.

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
`planner_stopped`, and `infrastructure_error`. Docker, Isaac Sim, PX4, ROS 2,
bridge, takeoff, or stale-telemetry failures are infrastructure errors; a
healthy planner that exhausts recovery is `planner_stopped`.

Path length integrates 3-D odometry at the configured sample rate. Time to goal
uses ROS message (simulation) time. The current obstacle minimum-clearance and
collision fallback treats the Iris as a sphere and the three known cubes as
axis-aligned boxes. PhysX contact becomes the authoritative collision oracle
when that signal is integrated in a later milestone.

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
