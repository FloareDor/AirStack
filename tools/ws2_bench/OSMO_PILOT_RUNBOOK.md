# WS2 OSMO pilot runbook

Use this for a fresh GPU workspace and the MonoNav qualified-layout pilot.
Run these commands from WSL, from the AirStack checkout.

## 1. Submit the 12-hour workspace

```bash
cd /path/to/AirStack
osmo workflow validate tools/ws2_bench/osmo_pilot.yaml
osmo workflow submit tools/ws2_bench/osmo_pilot.yaml
```

The submission prints a workflow ID such as `ws2-pilot-2`. Check it with:

```bash
osmo workflow query ws2-pilot-2
```

Wait until the `workspace` task is `RUNNING`.

## 2. Open an SSH tunnel

Keep this command running in its own terminal:

```bash
osmo workflow port-forward ws2-pilot-2 workspace --port 22038:22
```

Use a different unused local port when another workspace is active. In a second
terminal, connect to the task:

```bash
ssh -p 22038 root@127.0.0.1
cd /root/AirStack
git log -1 --oneline
```

The checkout should be on `mason/adv-ws2` from the user's fork.

## 3. One-time setup on a fresh workspace

Run these steps in order. Do not start a second `airstack.sh up` while the first
one is still pulling images.

```bash
cd /root/AirStack
AUTOLAUNCH=false ./airstack.sh up isaac-sim robot-desktop
python3 tools/ws2_bench/download_office_assets.py
docker cp /tmp/ws2_assets/Isaac/4.5/. isaac-sim:/tmp/ws2_assets/Isaac/4.5
docker exec airstack-robot-desktop-1 bash -lc 'bws --packages-select mononav_bridge'
docker stop --timeout 3 isaac-sim airstack-robot-desktop-1
```

The image pull can take several minutes. Check progress without starting another
copy:

```bash
docker ps --format '{{.Names}} {{.Status}}'
```

## 4. Run the qualified MonoNav random baseline

`easy:2` is currently the only clean-qualified MonoNav layout. The earlier
unrestricted random run showed that geometry validation alone does not make a
layout suitable for MonoNav; see `OSMO_SMOKE_RESULTS.md`.

```bash
cd /root/AirStack
python3 tools/ws2_bench/agent_campaign.py \
  --policy random \
  --planner mononav \
  --budget 8 \
  --seed 42 \
  --qualified-layout easy:2 \
  --record-bags \
  --review-seconds 0 \
  --output robot/ros_ws/ws2_runtime/campaigns/ws2_random_mononav_qualified
```

Check progress from another SSH session:

```bash
cd /root/AirStack
sed -n '1,160p' robot/ros_ws/ws2_runtime/campaigns/ws2_random_mononav_qualified/presentation.json
find robot/ros_ws/ws2_runtime/campaigns/ws2_random_mononav_qualified -name result.json | sort
```

## 5. Copy results out before the workspace ends

From the local machine, while the SSH tunnel is alive:

```bash
scp -r -P 22038 root@127.0.0.1:/root/AirStack/robot/ros_ws/ws2_runtime/campaigns/ws2_random_mononav_qualified ./ws2_random_mononav_qualified
```

Copy after every completed pair if the workspace is near its deadline. The OSMO
task filesystem is ephemeral; normal workflow logs do not contain campaign
results, and rsync was not enabled for the earlier smoke workspace.

## 6. Run the other two methods

Use new output directories, the same layout list, seed, model, and eight-flight
budget:

```bash
python3 tools/ws2_bench/agent_campaign.py --policy search --planner mononav --budget 8 --seed 42 --qualified-layout easy:2 --record-bags --review-seconds 0 --output robot/ros_ws/ws2_runtime/campaigns/ws2_search_mononav_qualified
python3 tools/ws2_bench/agent_campaign.py --policy agent_search --planner mononav --budget 8 --seed 42 --qualified-layout easy:2 --record-bags --review-seconds 0 --output robot/ros_ws/ws2_runtime/campaigns/ws2_agent_mononav_qualified
```

Agent mode also needs `WS2_AGENT_ENDPOINT`, `WS2_AGENT_API_KEY`, and
`WS2_AGENT_MODEL` in the task environment before it starts. Do not put those
credentials in this repository.
