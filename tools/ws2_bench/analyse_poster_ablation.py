"""Read a poster ablation: does a structure-free control reproduce the patch?

Primary endpoint is the per-flight mean of MonoNav's `zoe_corr`, the fraction of
strong RGB edges that have a corresponding depth edge. It falls when ZoeDepth
stops tracking scene structure, which is the degradation both candidate accounts
in poster_ablation.py are about, and it is continuous with hundreds of frames a
flight rather than one bit.

The unit of analysis is the FLIGHT, not the frame. Frames within a flight are
strongly autocorrelated -- consecutive frames are the same scene a tenth of a
second apart -- so pooling them would inflate n by a factor of a few hundred and
manufacture significance out of nothing. Every test here is over per-flight
means, n = flights.

Reading the result:

  control ~= clean, patch < both      the structure matters; appearance alone
                                      does not explain the degradation
  control ~= patch, both < clean      appearance explains it; the learned patch
                                      is doing nothing an ordinary bright poster
                                      would not do
  all three ~= each other             no detectable perception effect at this
                                      exposure; the easy-2 pass-rate difference
                                      needs another explanation

Pass rates are printed because withholding them would be worse, but at the n an
ablation can afford they are a direction and are labelled as such.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path

from mission import SUCCESSES

# frame=... zoe_corr=0.431/0.120 zoe_edges=5512 ...
ZOE_CORR = re.compile(r'zoe_corr=([0-9.]+)/([0-9.]+)')
ZOE_EDGES = re.compile(r'zoe_edges=(\d+)')
# A frame with too few strong edges is not evaluated and reports 1.0 by
# convention (MonoNav b8e5377). Those frames carry no information about depth
# quality and would pull every arm's mean toward 1.0 by different amounts
# depending only on how much texture each arm's flight happened to fly past.
MIN_EDGE_PIXELS = 1


def frame_correspondences(worker_log, min_edges=MIN_EDGE_PIXELS):
    values, skipped = [], 0
    try:
        text = worker_log.read_text(errors='replace')
    except OSError:
        return values, skipped
    for line in text.splitlines():
        match = ZOE_CORR.search(line)
        if not match:
            continue
        edges = ZOE_EDGES.search(line)
        if edges and int(edges.group(1)) < min_edges:
            skipped += 1
            continue
        values.append(float(match.group(1)))
    return values, skipped


def flights(root):
    found = []
    for result_path in sorted(Path(root).glob('*/result.json')):
        folder = result_path.parent
        result = json.loads(result_path.read_text())
        scenario = folder/'scenario.json'
        arm = None
        if scenario.exists():
            condition = json.loads(scenario.read_text()).get('condition', {})
            # Absent is not the same as null. A flight recorded before the
            # poster axis existed has no key at all, and reading that as 'clean'
            # would quietly relabel archived patch flights as controls. Only a
            # condition that actually carries the field is evidence about it.
            if 'poster' in condition:
                arm = condition['poster'] or 'clean'
        if arm is None:
            arm = folder.name.split('_', 1)[-1]
        values, skipped = frame_correspondences(folder/'worker.log')
        found.append({
            'folder': folder.name, 'arm': arm, 'outcome': result.get('outcome'),
            'passed': result.get('outcome') in SUCCESSES,
            'frames': len(values), 'skipped_low_edge_frames': skipped,
            'mean_zoe_corr': statistics.fmean(values) if values else None,
            'p10_zoe_corr': sorted(values)[len(values)//10] if len(values) >= 10 else None,
            'minimum_obstacle_clearance_m': result.get('metrics', {}).get('minimum_obstacle_clearance_m'),
            'poster_sha256': _poster_digest(folder)})
    return found


def _poster_digest(folder):
    path = folder/'provenance.json'
    if not path.exists():
        return None
    return json.loads(path.read_text()).get('poster', {}).get('sha256')


def mann_whitney(a, b):
    """Two-sided Mann-Whitney U with a normal approximation and tie correction.

    Rank-based rather than a t-test: per-flight correspondence means are bounded
    in [0, 1] and visibly skewed, and n per arm is small enough that normality
    is an assumption rather than an observation.
    """
    if len(a) < 3 or len(b) < 3:
        return None
    combined = sorted([(v, 0) for v in a]+[(v, 1) for v in b])
    ranks, index, ties = [0.0]*len(combined), 0, 0
    while index < len(combined):
        stop = index
        while stop+1 < len(combined) and combined[stop+1][0] == combined[index][0]:
            stop += 1
        count = stop-index+1
        ties += count**3-count
        for position in range(index, stop+1):
            ranks[position] = (index+stop)/2.0+1
        index = stop+1
    rank_a = sum(r for r, (_, group) in zip(ranks, combined) if group == 0)
    n_a, n_b = len(a), len(b)
    u_a = rank_a-n_a*(n_a+1)/2.0
    u = min(u_a, n_a*n_b-u_a)
    mean = n_a*n_b/2.0
    total = n_a+n_b
    variance = n_a*n_b/12.0*((total+1)-ties/float(total*(total-1)))
    if variance <= 0:
        return None
    z = (u-mean+0.5)/math.sqrt(variance)
    return {'u': u, 'z': round(z, 3),
            'p': round(math.erfc(abs(z)/math.sqrt(2)), 6)}


def fisher_one_sided(a_pass, a_n, b_pass, b_n):
    """P(as few or fewer passes in arm b) -- hypergeometric tail, exact."""
    def choose(n, k):
        return math.comb(n, k) if 0 <= k <= n else 0
    total, total_pass = a_n+b_n, a_pass+b_pass
    denominator = choose(total, total_pass)
    if not denominator:
        return None
    return round(sum(choose(b_n, k)*choose(a_n, total_pass-k)
                     for k in range(0, b_pass+1))/denominator, 6)


def report(root):
    found = flights(root)
    arms = sorted({f['arm'] for f in found})
    summary = {}
    for arm in arms:
        own = [f for f in found if f['arm'] == arm]
        usable = [f for f in own if f['outcome'] != 'infrastructure_error']
        means = [f['mean_zoe_corr'] for f in usable if f['mean_zoe_corr'] is not None]
        summary[arm] = {
            'flights': len(own), 'usable': len(usable),
            'with_depth_log': len(means),
            'mean_zoe_corr': round(statistics.fmean(means), 4) if means else None,
            'sd_zoe_corr': round(statistics.pstdev(means), 4) if len(means) > 1 else None,
            'median_zoe_corr': round(statistics.median(means), 4) if means else None,
            'pass_count': sum(f['passed'] for f in usable), 'pass_n': len(usable),
            'distinct_poster_digests': sorted({f['poster_sha256'] for f in own if f['poster_sha256']}),
            '_means': means}
    comparisons = {}
    for i, left in enumerate(arms):
        for right in arms[i+1:]:
            key = f'{left} vs {right}'
            comparisons[key] = {
                'zoe_corr_mann_whitney': mann_whitney(summary[left]['_means'], summary[right]['_means']),
                'pass_rate_fisher_one_sided_right_worse': fisher_one_sided(
                    summary[left]['pass_count'], summary[left]['pass_n'],
                    summary[right]['pass_count'], summary[right]['pass_n'])}
    for arm in summary:
        summary[arm].pop('_means')
    return {'root': str(root), 'arms': summary, 'comparisons': comparisons,
            'unit_of_analysis': 'flight (per-flight mean zoe_corr); frames are autocorrelated and are not pooled',
            'pass_rate_caveat': 'Direction only at this n. Do not report as a result.',
            'flights': found}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('root', type=Path, help='a poster_ablation output directory')
    p.add_argument('--json', action='store_true', help='full machine-readable dump')
    a = p.parse_args()
    result = report(a.root)
    if a.json:
        print(json.dumps(result, indent=2))
        return
    print(f"{'arm':<18}{'n':>4}{'depth':>7}{'mean_corr':>11}{'sd':>8}{'pass':>9}")
    for arm, s in result['arms'].items():
        rate = f"{s['pass_count']}/{s['pass_n']}"
        print(f"{arm:<18}{s['usable']:>4}{s['with_depth_log']:>7}"
              f"{(s['mean_zoe_corr'] if s['mean_zoe_corr'] is not None else float('nan')):>11.4f}"
              f"{(s['sd_zoe_corr'] if s['sd_zoe_corr'] is not None else float('nan')):>8.4f}{rate:>9}")
    print()
    for key, c in result['comparisons'].items():
        mw = c['zoe_corr_mann_whitney']
        print(f"{key:<42} zoe_corr p={mw['p'] if mw else 'n/a':<10} "
              f"pass-rate p={c['pass_rate_fisher_one_sided_right_worse']} (direction only)")
    print('\n'+result['pass_rate_caveat'])


if __name__ == '__main__':
    main()
