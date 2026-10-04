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

cell () {
    local name=$1; shift
    if [ -f "$CAMPAIGNS/$name/summary.json" ] \
       && grep -q '"complete": true' "$CAMPAIGNS/$name/summary.json" 2>/dev/null; then
        echo "[$(date +%H:%M)] $name already complete, skipping"
        return 0
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
