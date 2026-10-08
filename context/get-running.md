# getting WS2 running on OSMO

This is the shortest known-good path for a fresh OSMO GPU workspace. Run local
commands from WSL in the AirStack checkout. The OSMO workspace filesystem is
ephemeral: copy campaign evidence out before the workspace reaches its timeout.

## project context and goal

WS2 is the AirStack simulation benchmark for testing learning-based drone
obstacle avoidance under controlled sensor delay and visual-patch conditions.
The current target is MonoNav first; Kim can be added after the MonoNav pilot is
stable. The bench owns configuration validation, flight execution, metrics,
logs, bags, and saved evidence. It does not let an agent directly fly the
drone.

The immediate experiment compares three ways to choose tests under the same
flight budget:

- seeded random sampling;
- deterministic result-guided search;
- later, agent-guided search.

Each tested action can choose a saved obstacle layout, added sensor delay, and
patch enablement, size, and timing. A clean twin disables delay and the patch.
An attack outcome only counts when that clean twin reaches the goal. The guarded
campaign also requires two pristine clean successes before it starts the paired
budget.

The current goal is not to claim a general vulnerability from a few flights.
It is to find distinct candidate failures, repeat them, and compare how many
reproducible clean-pass/attack-fail cases each method finds with the same
budget. The existing pilots use `easy:2`, seed 42, and four clean/attack pairs
(eight scheduled flights) because that layout has a working MonoNav control.

## current state

- Random baseline: complete; four clean goals, two attack collisions. One
  candidate was repeated and then passed, so neither is yet reproducible.
- Guarded search baseline: complete; two clean validations and four paired clean
  goals. It found one planner stop and one collision, and both passed on their
  one confirmation run.
- Agent-guided search: not run yet. It needs the same guarded setup plus
  `WS2_AGENT_ENDPOINT`, `WS2_AGENT_API_KEY`, and `WS2_AGENT_MODEL` in the OSMO
  task environment. Do not commit those credentials.

## submit and connect

```bash
cd /path/to/AirStack
osmo workflow validate tools/ws2_bench/osmo_pilot.yaml
osmo workflow submit tools/ws2_bench/osmo_pilot.yaml
osmo workflow query WORKFLOW_ID
osmo workflow port-forward WORKFLOW_ID workspace --port 22039:22
ssh -p 22039 root@127.0.0.1
```

Wait until the workspace task is `RUNNING`. The entrypoint starts AirStack, so
do not run a second `airstack.sh up`. Check with:

```bash
docker ps --format '{{.Names}} {{.Status}}'
```

The expected container names are `isaac-sim` and
`airstack-robot-desktop-1`.

## fresh-workspace setup

Run this inside the OSMO workspace after its containers are up:

```bash
cd /root/AirStack
git pull --ff-only origin mason/adv-ws2
apt-get update && apt-get install -y python3-yaml
python3 tools/ws2_bench/download_office_assets.py
docker exec isaac-sim mkdir -p /tmp/ws2_assets/Isaac/4.5
docker cp /tmp/ws2_assets/Isaac/4.5/. isaac-sim:/tmp/ws2_assets/Isaac/4.5
docker exec airstack-robot-desktop-1 bash -lc 'bws'
git clone --recursive --branch floaredor/osmo-smoke https://github.com/FloareDor/MonoNav.git /root/MonoNav
(cd /root/MonoNav && bash docker/build_image.sh)
```

The checkout must include MonoNav `2e86c87` or later, which added the
depth-confidence gates. The bench passes `--max-unmapped-gap` and
`--zoe-degenerate-min-correspondence` on every MonoNav flight, so an older
checkout rejects the flags and the flight fails instead of quietly flying the
version that scored unreadable depth as clear. An existing workspace needs
`(cd /root/MonoNav && git pull --ff-only)` and an image rebuild.

`--max-unmapped-gap` now defaults to 0, which disables it. The 2026-10-08 A/B
found it grounds the planner instead of protecting it: it requires every
trajectory point to sit near a weighted voxel, but Open3D allocates blocks only
in the +/-0.375 m band around an observed surface, so the open centre of a
corridor is rejected for being open. Both gated flights stopped under 0.3 m
travelled with `depth_ok=True` while the ungated twin reached the goal. Do not
raise it again until the check is a frustum/depth test. The degenerate-depth
gate is unaffected and stays on.

The full ROS build is slow on a clean workspace. Wait for it to finish before
starting an episode. Its normal warnings are not failures. The Office download
should contain 910 files and `office.usd` should exist under
`/tmp/ws2_assets/Isaac/4.5/Isaac/Environments/Office/`.

Warm the shared model cache once after the MonoNav image build:

```bash
docker run --rm --gpus all \
  -v mononav-torch-cache:/root/.cache/torch \
  -v /root/MonoNav:/workspace/planner -w /workspace/planner \
  mononav-demo:2.7.1-cu128 \
  timeout 300 python mononav_airstack.py --headless --server http://127.0.0.1:1
```

Success ends with `ZoeDepth ready on cuda`. The first run downloads about 1.34
GB of model weights.

## run the guarded search baseline

```bash
cd /root/AirStack
nohup python3 tools/ws2_bench/agent_campaign.py \
  --policy search --planner mononav --budget 8 --seed 42 \
  --qualified-layout easy:2 --clean-validation-runs 2 \
  --record-bags --review-seconds 0 \
  --output robot/ros_ws/ws2_runtime/campaigns/ws2_search_mononav_guarded \
  >/tmp/ws2_search_mononav_guarded.log 2>&1 &
```

The two clean validation flights do not count toward the eight paired flights.
If either validation or a per-pair clean control fails, the guarded campaign
stops rather than treating an unmatched attack flight as evidence.

Check progress:

```bash
cat robot/ros_ws/ws2_runtime/campaigns/ws2_search_mononav_guarded/presentation.json
tail -40 /tmp/ws2_search_mononav_guarded.log
```

## copy results before timeout

Run this locally while the SSH tunnel is alive. It copies all campaign evidence
except the large ROS bags:

```bash
rsync -a --exclude 'bag/' \
  -e 'ssh -p 22039' \
  root@127.0.0.1:/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/ws2_search_mononav_guarded/ \
  tools/ws2_bench/artifacts/ws2_search_mononav_guarded/
```

## saved result locations

Committed summaries:

- `tools/ws2_bench/OSMO_SMOKE_RESULTS.md`
- `tools/ws2_bench/OSMO_RANDOM_BASELINE_RESULTS.md`
- `tools/ws2_bench/OSMO_SEARCH_BASELINE_RESULTS.md`

Local raw evidence (ignored by git):

- `tools/ws2_bench/artifacts/ws2_random_mononav_qualified/`
- `tools/ws2_bench/artifacts/ws2_search_mononav_qualified/` (old unguarded run; clean controls were unstable)
- `tools/ws2_bench/artifacts/ws2_search_mononav_guarded/`

OSMO campaign directories:

- `/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/ws2_random_mononav_qualified`
  on the expired `ws2-pilot-2` workspace
- `/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/ws2_search_mononav_qualified`
  on the expired `ws2-pilot-2` workspace
- `/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/ws2_search_mononav_guarded`
  on the current `ws2-pilot-3` workspace

The OSMO workspace page does not retain these result directories after timeout;
only normal task logs survive. The local artifact copies are the durable raw
evidence.
