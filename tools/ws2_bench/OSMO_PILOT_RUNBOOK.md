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
apt-get update && apt-get install -y python3-yaml unzip
python3 tools/ws2_bench/download_office_assets.py
docker exec isaac-sim mkdir -p /tmp/ws2_assets/Isaac/4.5
docker cp /tmp/ws2_assets/Isaac/4.5/. isaac-sim:/tmp/ws2_assets/Isaac/4.5
docker exec airstack-robot-desktop-1 bash -lc 'bws'
docker exec airstack-robot-desktop-1 bash -lc 'bws --packages-select mononav_bridge'
git clone --recursive --branch floaredor/osmo-smoke https://github.com/FloareDor/MonoNav.git /root/MonoNav
(cd /root/MonoNav && bash docker/build_image.sh)
docker run --rm --gpus all   -v mononav-torch-cache:/root/.cache/torch   -v /root/MonoNav:/workspace/planner -w /workspace/planner   mononav-demo:2.7.1-cu128   timeout 300 python mononav_airstack.py --headless --server http://127.0.0.1:1
docker stop --timeout 3 isaac-sim airstack-robot-desktop-1
```

For a run that uses Kim et al., clone and build it too, before stopping the
stack. `unzip` above is what extracts the FCRN checkpoint: without it
`download_models.sh` fetches 450 MB, verifies it, and then dies on line 22,
leaving `airstack_models/NYU_FCRN-checkpoint` empty. That happened on
`ws2-pilot-11`.

```bash
git clone --recursive https://github.com/engcang/Collision-avoidance.git /root/Collision-avoidance
(cd /root/Collision-avoidance && bash docker/build_image.sh && bash docker/download_models.sh)
ls /root/Collision-avoidance/airstack_models/NYU_FCRN-checkpoint/
# NYU_FCRN.ckpt.data-00000-of-00001  NYU_FCRN.ckpt.index  NYU_FCRN.ckpt.meta
ls /root/Collision-avoidance/save_model/D3QN_V_3_single.h5
```

`D3QN_V_3_single.h5` is tracked in the repository and needs no download. The
FCRN files are three, and an empty directory is the failure mode to look for.

The model download is part of setup, not an optional extra. Without it every
flight ends in `infrastructure_error` within seconds and a whole session can
burn out unattended. Confirm it before flying anything:

```bash
docker run --rm -v mononav-torch-cache:/c alpine   sha256sum /c/hub/checkpoints/ZoeD_M12_N.pt
# c97f94c4d53c5b788af46c5da0462262aebb37ea116fd70014bcbba93146c33b
```

The image pull can take several minutes. Check progress without starting another
copy:

```bash
docker ps --format '{{.Names}} {{.Status}}'
```

The warm-cache step above is what populates the shared model cache. It is
listed in the setup block rather than here because reading the block alone used
to leave the model missing.

```bash
docker run --rm --gpus all \
  -v mononav-torch-cache:/root/.cache/torch \
  -v /root/MonoNav:/workspace/planner -w /workspace/planner \
  mononav-demo:2.7.1-cu128 \
  timeout 300 python mononav_airstack.py --headless --server http://127.0.0.1:1
```

## 4. Run the qualified MonoNav random baseline

`easy:2` is currently the only clean-qualified MonoNav layout. The earlier
unrestricted random run showed that geometry validation alone does not make a
layout suitable for MonoNav; see `OSMO_SMOKE_RESULTS.md`.

The command first runs two pristine clean validation flights. They are recorded
separately and do not count toward the eight-flight paired budget. If either
fails, the campaign stops before it can run an unmatched attack flight.

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
