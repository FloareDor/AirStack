#!/usr/bin/env bash
# Kim et al. (D3QN on FCRN depth) against the learned patch, with controls
# interleaved through the run rather than only at its ends.
#
# Why Kim matters: the patch was trained against config_depth_fcrn.yaml, and
# Kim runs --depth-source fcrn. Every MonoNav number we have is a transfer
# attack onto ZoeDepth. This is the matched target.
#
# Why interleaved: pilot-10 flew a clean control first and last, they agreed at
# p = 1.000, and a third clean cell flown later came back 0.750 against their
# 0.42. A cell flown outside the bracket inherited that as a fake effect. Ends
# alone cannot see a change outside the region they bracket.
#
# Kim is avoidance mode, not goal mode: success is completed_horizon, meaning
# it survived 120 s with enough travel. goal_reached is an error for Kim and
# audit_results.py rejects it.
#
# Run from /root/AirStack:
#     nohup bash tools/ws2_bench/run_kim_paired.sh > /root/kim.log 2>&1 < /dev/null &
set -u
CAMPAIGNS=/root/AirStack/robot/ros_ws/ws2_runtime/campaigns
LAYOUT_SEED="${KIM_LAYOUT_SEED:-}"
COMMON="--planner kim --layout easy"
BLOCK="${KIM_BLOCK:-12}"

# Preflight. A missing model does not fail loudly, it fails every flight in
# seconds as infrastructure_error. On 2026-10-04 that cost 180 MonoNav flights
# before anyone looked. Kim needs two: FCRN depth and the D3QN policy.
KIM_REPO=/root/Collision-avoidance
for f in airstack_models/NYU_FCRN-checkpoint/NYU_FCRN.ckpt.index save_model/D3QN_V_3_single.h5; do
    if [ ! -f "$KIM_REPO/$f" ]; then
        echo "[$(date -u +%H:%M)] ABORT: missing $KIM_REPO/$f"
        echo "Run: (cd $KIM_REPO && bash docker/download_models.sh)"
        exit 1
    fi
done
echo "[$(date -u +%H:%M)] Kim models present"

if [ -z "$LAYOUT_SEED" ]; then
    echo "[$(date -u +%H:%M)] ABORT: set KIM_LAYOUT_SEED from the qualification phase."
    echo "Kim has no qualified layout. Fly clean blocks on candidates first and"
    echo "pick one whose clean rate leaves room for an attack to show."
    exit 1
fi
COMMON="$COMMON --layout-seed $LAYOUT_SEED --delay-s 0.0"

cell () {
    local name=$1; shift
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
        if grep -q '"complete": true' "$CAMPAIGNS/$name/summary.json" 2>/dev/null \
           && [ "${usable:-0}" -gt 0 ]; then
            echo "[$(date -u +%H:%M)] $name already complete, skipping"
            return 0
        fi
        echo "[$(date -u +%H:%M)] $name has no usable flights, re-flying"
        rm -rf "$CAMPAIGNS/$name"
    fi
    echo "[$(date -u +%H:%M)] starting $name"
    python3 tools/ws2_bench/repeat_check.py --output "$CAMPAIGNS/$name" $COMMON "$@"
    echo "[$(date -u +%H:%M)] finished $name rc=$?"
}

# Alternating control and attack blocks. Seven of each at 12 flights is 168
# flights, and every attack block has a control block on both sides of it.
# If the run is cut short, it stops after a matched pair, never mid-bracket.
for i in 1 2 3 4 5 6 7; do
    cell "kim_clean_$i" --clean --repeats "$BLOCK" --seed "$((40 + i))" \
        --label "Kim clean control block $i"
    cell "kim_patch_$i" --patch --patch-size-m 0.9 --repeats "$BLOCK" --seed "$((140 + i))" \
        --label "Kim 0.9 m continuous patch block $i"
done
echo "[$(date -u +%H:%M)] done"
