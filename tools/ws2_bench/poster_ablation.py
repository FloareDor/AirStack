"""Fly the learned patch against structure-free controls with matched appearance.

The question. MonoNav's pass rate on `easy` seed 2 fell from 58% (n=203) to 38%
(n=263) when the learned patch hung on the column, p = 1.2e-05. Two accounts fit
equally well:

  adversarial   the image carries structure optimised against a depth model and
                enough of it transfers from FCRN to ZoeDepth to matter, or
  appearance    ZoeDepth reads any bright, saturated, high-contrast surface as
                further away than it is, and the route has a 5 cm margin, so a
                small perception error is sufficient.

Nothing measured so far separates them, because the patch has only ever been
flown against *no poster at all*. These two accounts make different predictions
about an image with the same colours and contrast and no optimised structure:
appearance says it degrades MonoNav just as much, adversarial says it does not.
make_control_posters.py builds exactly those images. This flies them.

Design notes, each of which is load-bearing:

Interleaved, not blocked. Arms rotate flight by flight. A blocked run cannot
tell an arm effect from the workspace drifting under it, and this bench has
already produced one effect (pilot-10 `patch_090_timed`, p = 2e-08) that died
against a time-adjacent control. Round `r` flies every arm before round `r+1`
starts, so any drift hits all arms alike and a part-finished run is still
balanced.

The primary endpoint is not the pass rate. At 58% vs 38%, separating the two
accounts needs about 97 flights per arm -- roughly three workspace sessions,
which is why this has never been run. It is affordable because MonoNav logs the
per-frame RGB/depth edge correspondence (`zoe_corr`, MonoNav b8e5377), which is
a direct and continuous measure of the degradation both accounts are about.
Per-flight means of it need ~12 flights an arm, not ~97. analyse_poster_ablation
reads it. The pass rate is recorded and reported as a direction, never as a
result at this n -- see the two withdrawn interim readings in the project notes.

Flying this does not make the learned patch an attack on MonoNav. The bench
still refuses `patch_enabled` for MonoNav (model_adapters, a82d18182); the
poster axis claims nothing about efficacy, and a poster arm is only reportable
alongside its controls.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from conditions import POSTERS, validate
from episode import atomic, fingerprint, resolved, run_episode
from mission import SUCCESSES, defaults

ARMS = ('clean', *sorted(POSTERS))


def build_episode(arm, planner, layout, layout_seed, seed, patch_size_m, label):
    if arm not in ARMS:
        raise ValueError(f'unknown arm {arm!r}; choose from {ARMS}')
    condition = validate({'name': f'poster ablation: {arm}', 'layout': layout,
                          'layout_seed': layout_seed, 'seed': seed, 'light': 1800.,
                          'patch_size': patch_size_m,
                          'poster': None if arm == 'clean' else arm})
    return resolved({'name': f'{label}: {arm}', 'planner': planner,
                     'condition': condition, **defaults(planner)})


def schedule(arms, rounds):
    """Round-robin, rotating the order each round.

    Rotating matters as much as interleaving: a fixed order would give one arm
    every first-flight-after-restart in the session, and the first flight after
    a simulator restart is not drawn from the same distribution as the rest.
    """
    return [(r, arms[(i+r) % len(arms)]) for r in range(rounds) for i in range(len(arms))]


def run(output, arms, rounds, planner, layout, layout_seed, seed, patch_size_m,
        record_bags, label, max_flights=None):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    episodes = {arm: build_episode(arm, planner, layout, layout_seed, seed, patch_size_m, label)
                for arm in arms}
    atomic(root/'config.json', {
        'arms': list(arms), 'rounds': rounds, 'planner': planner, 'layout': layout,
        'layout_seed': layout_seed, 'seed': seed, 'patch_size_m': patch_size_m, 'label': label,
        'schedule': 'round-robin, rotating', 'primary_endpoint': 'per-flight mean zoe_corr',
        'configuration_hash': {arm: fingerprint(e) for arm, e in episodes.items()},
        'episode': episodes})
    flights, flown_here = [], 0
    for index, (round_index, arm) in enumerate(schedule(list(arms), rounds)):
        folder = root/f'{index:03d}_{arm}'
        saved = folder/'result.json'
        if max_flights is not None and flown_here >= max_flights and not saved.exists():
            # Chunk boundary. The pod's 48Gi cgroup OOM-kills isaac-sim partway
            # through a long campaign (exit 137, with OOMKilled false because
            # the kill is from the cgroup), and a dead sim blocks until the
            # workflow's exec timeout. The caller cycles the sim between chunks
            # and re-invokes; resume picks up exactly here. Stopping mid-round
            # is safe to resume but leaves the arms unbalanced until the round
            # completes, so analyse only at a round boundary.
            print(f'[chunk] flew {flown_here}; stopping before {folder.name} for a sim cycle', flush=True)
            break
        if saved.exists():
            result = json.loads(saved.read_text())
            if result['configuration_hash'] != fingerprint(episodes[arm]):
                raise ValueError(f'{folder} holds a different configuration than arm {arm}')
        else:
            result = run_episode(episodes[arm], folder, record_bag=record_bags)
            flown_here += 1
        flights.append({'index': index, 'round': round_index, 'arm': arm,
                        'outcome': result['outcome'], 'folder': folder.name,
                        'minimum_obstacle_clearance_m': result.get('metrics', {}).get('minimum_obstacle_clearance_m')})
        atomic(root/'flights.json', flights)
        atomic(root/'summary.json', summarize(flights, rounds, arms))
        print(f"[{index:03d}] round {round_index} arm {arm:<16} {result['outcome']}", flush=True)
    summary = summarize(flights, rounds, arms)
    atomic(root/'summary.json', summary)
    return summary


def summarize(flights, rounds, arms):
    by_arm = {}
    for arm in arms:
        own = [f for f in flights if f['arm'] == arm]
        usable = [f for f in own if f['outcome'] != 'infrastructure_error']
        passes = sum(f['outcome'] in SUCCESSES for f in usable)
        by_arm[arm] = {'flown': len(own), 'usable': len(usable), 'pass_count': passes,
                       'pass_rate': passes/len(usable) if usable else None,
                       'outcomes': {o: sum(f['outcome'] == o for f in own)
                                    for o in sorted({f['outcome'] for f in own})}}
    return {'arms': by_arm, 'flights': len(flights), 'rounds_requested': rounds,
            'complete': len(flights) == rounds*len(arms),
            'note': 'Pass rates here are a direction, not a result. The endpoint is '
                    'per-flight mean zoe_corr; run analyse_poster_ablation.py.'}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--arms', default='clean,fcrn_patch,phase_scrambled',
                   help=f'comma-separated, from {ARMS}')
    p.add_argument('--rounds', type=int, default=12, help='flights per arm')
    p.add_argument('--planner', default='mononav', choices=('mononav', 'kim'))
    p.add_argument('--layout', default='easy')
    p.add_argument('--layout-seed', type=int, default=2)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--patch-size-m', type=float, default=0.9)
    p.add_argument('--max-flights', type=int, default=None,
                   help='fly at most this many NEW flights, then exit for a sim cycle; '
                        're-invoke with the same arguments to resume')
    p.add_argument('--record-bags', action='store_true')
    p.add_argument('--label', default='poster ablation')
    a = p.parse_args()
    arms = [arm.strip() for arm in a.arms.split(',') if arm.strip()]
    if len(arms) < 2:
        p.error('an ablation needs at least a treatment and a control')
    if a.rounds < 2:
        p.error('--rounds must be at least 2; one flight per arm cannot measure anything')
    print(json.dumps(run(a.output, arms, a.rounds, a.planner, a.layout, a.layout_seed,
                         a.seed, a.patch_size_m, a.record_bags, a.label, a.max_flights), indent=2))


if __name__ == '__main__':
    main()
