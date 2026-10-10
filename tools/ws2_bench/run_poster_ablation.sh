#!/usr/bin/env bash
# Fly the learned patch against structure-free controls. See poster_ablation.py
# for what the experiment is and why the pass rate is not its endpoint.
#
# Run from /root/AirStack on the workspace, detached so it survives the local
# session dying:
#     setsid nohup bash tools/ws2_bench/run_poster_ablation.sh > /root/poster.log 2>&1 < /dev/null &
#
# Writes /root/POSTER_DONE when it finishes, so a waiter can key on a marker
# the script writes itself rather than on pgrep -- `pgrep -f poster_ablation`
# also matches the ssh command line carrying that string, which has already
# cost this project an 80-minute spin and one self-SIGTERM.

set -u
CAMPAIGNS=/root/AirStack/robot/ros_ws/ws2_runtime/campaigns
OUT=$CAMPAIGNS/poster_ablation
ARMS=${ARMS:-clean,fcrn_patch,phase_scrambled}
ROUNDS=${ROUNDS:-12}
LAYOUT=${LAYOUT:-easy}
LAYOUT_SEED=${LAYOUT_SEED:-2}
PATCH_SIZE=${PATCH_SIZE:-0.9}
# One round per chunk: a sim cycle between rounds keeps every arm on the same
# side of each restart, and leaves the campaign balanced at every stop point.
CHUNK=${CHUNK:-3}
rm -f /root/POSTER_DONE

say () { echo "[$(date +%H:%M:%S)] $*"; }

# --- preflight: the two failures that silently burn a whole session ----------
# 1. A missing depth model fails every flight in ~8s as infrastructure_error.
#    On 2026-10-04 that cost 180 flights before anyone looked.
WEIGHTS=ZoeD_M12_N.pt
have_weights () {
    docker run --rm -v mononav-torch-cache:/c alpine \
        test -f "/c/hub/checkpoints/$WEIGHTS" 2>/dev/null
}
if ! have_weights; then
    say "depth model missing, warming the cache"
    docker run --rm --gpus all \
        -v mononav-torch-cache:/root/.cache/torch \
        -v /root/MonoNav:/workspace/planner -w /workspace/planner \
        mononav-demo:2.7.1-cu128 \
        timeout 300 python mononav_airstack.py --headless --server http://127.0.0.1:1 \
        > /root/warm.log 2>&1
fi
if ! have_weights; then
    say "ABORT: $WEIGHTS still missing; every flight would be infrastructure_error"
    exit 1
fi
say "depth model present"

# 2. MonoNav must be new enough to LOG the per-frame correspondence, because
#    that value is this experiment's primary endpoint. An older checkout flies
#    perfectly well and produces a campaign with no endpoint in it, which would
#    not be discovered until analysis.
if ! grep -q 'zoe_corr=' /root/MonoNav/mononav_airstack.py; then
    say "ABORT: /root/MonoNav does not log zoe_corr (needs MonoNav b8e5377 or later)."
    say "Fix with: (cd /root/MonoNav && git pull --ff-only) && bash docker/build_image.sh"
    exit 1
fi
say "MonoNav logs per-frame zoe_corr"

# 3. The control posters must be the ones the manifest records. episode.py
#    re-checks this per flight; checking once here fails in seconds instead of
#    at the first poster flight.
cd /root/AirStack || exit 1
if ! python3 tools/ws2_bench/make_control_posters.py --check > /root/posters.json 2>&1; then
    say "ABORT: control posters are not reproducible"; cat /root/posters.json; exit 1
fi
say "control posters match their manifest"

assets_ok () {
    [ "$(docker exec isaac-sim sh -c 'find /tmp/ws2_assets -type f 2>/dev/null | wc -l')" -ge 900 ]
}
repair_assets () {
    # docker cp puts the Office files in the container's own /tmp, not a volume,
    # so any container RECREATION drops all 910 of them and every episode then
    # fails 360s later with a readiness timeout that looks like a slow sim.
    say "re-copying Office assets"
    docker exec isaac-sim mkdir -p /tmp/ws2_assets/Isaac/4.5
    docker cp /tmp/ws2_assets/Isaac/4.5/. isaac-sim:/tmp/ws2_assets/Isaac/4.5
}

# --- fly, one chunk at a time ------------------------------------------------
TOTAL=$(python3 -c "print(len('$ARMS'.split(','))*$ROUNDS)")
say "target $TOTAL flights: arms=$ARMS rounds=$ROUNDS layout=$LAYOUT:$LAYOUT_SEED patch_size=$PATCH_SIZE"

for pass_index in $(seq 1 200); do
    if [ -f "$OUT/summary.json" ] && grep -q '"complete": true' "$OUT/summary.json"; then
        say "campaign complete"; break
    fi
    if ! docker ps --format '{{.Names}}' | grep -q '^isaac-sim$'; then
        say "isaac-sim is not running (likely a cgroup OOM kill); bringing it back"
        (cd /root/AirStack && ./airstack.sh up -d) > /root/airstack_up.log 2>&1
        sleep 60
        repair_assets
    fi
    assets_ok || repair_assets
    say "chunk $pass_index"
    python3 tools/ws2_bench/poster_ablation.py \
        --output "$OUT" --arms "$ARMS" --rounds "$ROUNDS" \
        --planner mononav --layout "$LAYOUT" --layout-seed "$LAYOUT_SEED" \
        --patch-size-m "$PATCH_SIZE" --max-flights "$CHUNK" \
        --label "poster ablation" || say "chunk $pass_index returned rc=$?"
    # dmesg is the only honest OOM signal here: docker inspect reports
    # OOMKilled false because the kill comes from the pod cgroup.
    dmesg 2>/dev/null | tail -40 | grep -i 'oom-kill\|out of memory' && say "(OOM seen this chunk)"
done

say "checking every flight shares one build"
python3 tools/ws2_bench/check_provenance.py "$OUT" || say "provenance check reported differences"

say "analysis"
python3 tools/ws2_bench/analyse_poster_ablation.py "$OUT" | tee /root/poster_result.txt
python3 tools/ws2_bench/analyse_poster_ablation.py "$OUT" --json > /root/poster_result.json

touch /root/POSTER_DONE
say "done"
