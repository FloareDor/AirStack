#!/usr/bin/env python3
"""Detect a baseline that moves during a run.

pilot-10 flew a clean control first and last, they agreed at p = 1.000, and a
third clean cell flown later still came back 0.750 against their 0.42. Two
controls at the ends of the region you sampled cannot see a change outside it,
and a cell flown outside the bracket inherits the drift as a fake effect.

This orders every flight by provenance started_at_utc, splits the clean flights
into blocks, and reports the pass rate per block with the spread between the
best and worst. Interleave clean blocks through the run and this will show a
drifting baseline wherever it starts.

Usage:
    python3 check_drift.py artifacts/pilot10/clean_first artifacts/pilot10/clean_last
"""
import argparse
import datetime
import json
import math
import pathlib
import random
import sys

SUCCESSES = {"goal_reached", "completed_horizon"}


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def flights(cells):
    found = []
    for cell in cells:
        for result in cell.rglob("result.json"):
            provenance = result.parent / "provenance.json"
            started = None
            if provenance.exists():
                started = json.loads(provenance.read_text()).get("started_at_utc")
            if started is None:
                # Pre-dates started_at_utc. mtime is a weaker stand-in and is
                # labelled as such rather than silently mixed in.
                started = datetime.datetime.fromtimestamp(
                    result.stat().st_mtime, datetime.timezone.utc).isoformat(timespec="seconds")
                exact = False
            else:
                exact = True
            outcome = json.loads(result.read_text()).get("outcome")
            if outcome == "infrastructure_error":
                continue
            found.append((started, outcome in SUCCESSES, cell.name, exact))
    return sorted(found)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cells", nargs="+", type=pathlib.Path)
    parser.add_argument("--block", type=int, default=10,
                        help="flights per block (default 10)")
    args = parser.parse_args(argv)

    found = flights(args.cells)
    if not found:
        print("no usable flights found", file=sys.stderr)
        return 2
    if not all(f[3] for f in found):
        print("WARNING: some flights predate started_at_utc; order is from file")
        print("mtime and is indicative only.")
        print()

    print("%-6s %-18s %-18s %-9s %s" % ("block", "from", "to", "pass", "95% CI"))
    print("-" * 72)
    rates = []
    for index in range(0, len(found), args.block):
        chunk = found[index:index + args.block]
        if len(chunk) < max(3, args.block // 2):
            continue
        k = sum(1 for f in chunk if f[1])
        rates.append(k / len(chunk))
        lo, hi = wilson(k, len(chunk))
        print("%-6d %-18s %-18s %-9s %.3f-%.3f"
              % (index // args.block + 1, chunk[0][0][5:16], chunk[-1][0][5:16],
                 "%d/%d" % (k, len(chunk)), lo, hi))

    print()
    if len(rates) < 2:
        print("Only one block. Fly more control flights, spread through the run.")
        return 0

    # A fixed spread threshold flags noise as drift: at 15 flights a true rate
    # of 0.42 gives block spreads of 0.3 to 0.4 by chance alone. Ask instead
    # whether THIS ordering separates the blocks better than a random one of
    # the same flights would, which is what drift means.
    observed = max(rates) - min(rates)
    labels = [f[1] for f in found]
    blocks = [range(i, min(i + args.block, len(labels)))
              for i in range(0, len(labels), args.block)
              if len(range(i, min(i + args.block, len(labels)))) >= max(3, args.block // 2)]
    rng = random.Random(0)
    trials = 20000
    hits = 0
    for _ in range(trials):
        rng.shuffle(labels)
        shuffled = [sum(labels[i] for i in b) / len(b) for b in blocks]
        if max(shuffled) - min(shuffled) >= observed - 1e-12:
            hits += 1
    pvalue = (hits + 1) / (trials + 1)

    print("blocks %d  low %.3f  high %.3f  spread %.3f" % (len(rates), min(rates), max(rates), observed))
    print("permutation p = %.4f  (%d shuffles of the same flights)" % (pvalue, trials))
    print()
    if pvalue < 0.05:
        print("BASELINE MOVED DURING THE RUN.")
        print("Attack cells are only comparable to control flights adjacent to")
        print("them in time. Do not pool these controls into one arm.")
        return 1
    print("No drift detected. The spread is consistent with chance, so these")
    print("controls can be pooled. Absence of a signal at this block size is")
    print("not proof of stability outside the window the controls cover.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
