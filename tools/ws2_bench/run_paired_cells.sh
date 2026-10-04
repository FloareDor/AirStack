#!/usr/bin/env bash
# Next OSMO run: measure the continuous-patch lead against a control flown in
# the same workspace.
#
# The clean twin forces delay and patch off, so one clean arm is the shared
# control for every attack cell here. It is flown in two halves, first and
# last, so drift across a 12 hour session shows up as a disagreement between
# them rather than contaminating the attack cells.
#
# Run from /root/AirStack on the workspace:
#     nohup bash tools/ws2_bench/run_paired_cells.sh > /root/paired.log 2>&1 < /dev/null &

set -u
CAMPAIGNS=/root/AirStack/robot/ros_ws/ws2_runtime/campaigns
COMMON="--planner mononav --layout easy --layout-seed 2 --delay-s 0.0"

# Preflight. A missing depth model does not fail loudly: it fails every flight
# in seconds with infrastructure_error, so a whole run can burn out before
# anyone looks. On 2026-10-04 that cost 180 flights. Check once, warm the cache
# if needed, and refuse to fly if it is still absent.
WEIGHTS=ZoeD_M12_N.pt
have_weights () {
    docker run --rm -v mononav-torch-cache:/c alpine         test -f "/c/hub/checkpoints/$WEIGHTS" 2>/dev/null
}
if ! have_weights; then
    echo "[$(date +%H:%M)] depth model missing, warming the cache"
    docker run --rm --gpus all         -v mononav-torch-cache:/root/.cache/torch         -v /root/MonoNav:/workspace/planner -w /workspace/planner         mononav-demo:2.7.1-cu128         timeout 300 python mononav_airstack.py --headless --server http://127.0.0.1:1         > /root/warm.log 2>&1
fi
if ! have_weights; then
    echo "[$(date +%H:%M)] ABORT: $WEIGHTS still missing. Every flight would be an"
    echo "infrastructure_error. Fix the model cache before flying."
    exit 1
fi
echo "[$(date +%H:%M)] depth model present"

cell () {
    local name=$1; shift
    # "complete" is not enough: a cell whose every flight was an
    # infrastructure_error writes a complete summary holding no usable data,
    # and skipping it would silently keep the hole.
    if [ -f "$CAMPAIGNS/$name/summary.json" ]; then
        local usable
        usable=$(python3 -c '
import json, sys
try:
    o = json.load(open(sys.argv[1])).get("outcomes", {})
except Exception:
    print(0); raise SystemExit
print(sum(n for k, n in o.items() if k != "infrastructure_error"))
' "$CAMPAIGNS/$name/summary.json" 2>/dev/null || echo 0)
        if grep -q '"complete": true' "$CAMPAIGNS/$name/summary.json" 2>/dev/null            && [ "${usable:-0}" -gt 0 ]; then
            echo "[$(date +%H:%M)] $name already complete, skipping"
            return 0
        fi
        echo "[$(date +%H:%M)] $name has no usable flights, re-flying"
        rm -rf "$CAMPAIGNS/$name"
    fi
    echo "[$(date +%H:%M)] starting $name"
    python3 tools/ws2_bench/repeat_check.py --output "$CAMPAIGNS/$name" $COMMON "$@"
    echo "[$(date +%H:%M)] finished $name rc=$?"
}

# Control first, so the run is scoreable even if the workspace dies early.
cell clean_first  --clean --repeats 30 --seed 42   --label "clean control, first half"

# The lead: leaving the patch on. Largest cell, flown while time is certain.
cell patch_090    --patch --patch-size-m 0.9 --repeats 50 --seed 42   --label "continuous patch 0.9"

# Dose response. A monotone trend is worth more than one p-value.
cell patch_060    --patch --patch-size-m 0.6 --repeats 35 --seed 101  --label "continuous patch 0.6"
cell patch_030    --patch --patch-size-m 0.3 --repeats 35 --seed 202  --label "continuous patch 0.3"

# Control again, to catch drift across the session.
cell clean_last   --clean --repeats 30 --seed 777  --label "clean control, second half"

echo "[$(date +%H:%M)] all cells done; checking they share one build"
python3 tools/ws2_bench/check_provenance.py \
    "$CAMPAIGNS/clean_first" "$CAMPAIGNS/patch_090" "$CAMPAIGNS/patch_060" \
    "$CAMPAIGNS/patch_030" "$CAMPAIGNS/clean_last"
