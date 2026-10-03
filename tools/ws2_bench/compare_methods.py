"""Summarise adaptive campaigns against a measured clean baseline.

A candidate is a pair where the clean control passed and the attacked flight
failed. That is only evidence of an attack if the clean control passes more
often than the attacked flight does. Because the measured clean baseline on
mononav easy:2 is well below 1.0, a raw candidate count is not interpretable on
its own, so every count here is reported next to what the baseline alone would
produce.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SUCCESSES = {"goal_reached", "completed_horizon"}


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize_campaign(root: Path):
    history = json.loads((root / "history.json").read_text()) if (root / "history.json").exists() else []
    config = json.loads((root / "config.json").read_text()) if (root / "config.json").exists() else {}
    rows = {"name": root.name, "policy": config.get("backend") or config.get("policy"),
            "clean_failure_policy": config.get("clean_failure_policy", "halt"),
            "rounds": len(history), "verdicts": {},
            "clean_pass": 0, "clean_n": 0, "attacked_pass": 0, "attacked_n": 0,
            "distinct_actions": set()}
    for entry in history:
        for pair in entry.get("pairs", []):
            v = pair.get("verdict")
            rows["verdicts"][v] = rows["verdicts"].get(v, 0) + 1
            for role, key in (("clean", "clean"), ("perturbed", "attacked")):
                result = pair.get(role)
                if not result:
                    continue
                rows[key + "_n"] += 1
                if result.get("outcome") in SUCCESSES:
                    rows[key + "_pass"] += 1
        action = entry.get("decision", {}).get("action")
        if action:
            rows["distinct_actions"].add(json.dumps(action, sort_keys=True))
    rows["distinct_actions"] = len(rows["distinct_actions"])
    rows["candidates"] = rows["verdicts"].get("autonomy_failure", 0)
    rows["invalid_clean"] = rows["verdicts"].get("invalid_clean_baseline", 0)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaigns", nargs="+", type=Path)
    ap.add_argument("--baseline-pass", type=int, default=25,
                    help="clean flights that passed in the measured baseline")
    ap.add_argument("--baseline-n", type=int, default=34,
                    help="clean flights in the measured baseline")
    args = ap.parse_args()

    base = args.baseline_pass / args.baseline_n if args.baseline_n else None
    lo, hi = wilson(args.baseline_pass, args.baseline_n)
    print(f"measured clean baseline: {args.baseline_pass}/{args.baseline_n} = {base:.3f} "
          f"(95% CI {lo:.3f}-{hi:.3f})\n")

    header = f"{'campaign':<30}{'pol':<13}{'rnd':>4}{'cand':>6}{'bad':>5}{'attacked pass':>16}{'clean pass':>14}{'uniq':>6}"
    print(header)
    print("-" * len(header))
    rows = []
    for path in args.campaigns:
        if not (path / "history.json").exists():
            print(f"{path.name:<30}(no history.json)")
            continue
        r = summarize_campaign(path)
        rows.append(r)
        ap_, an = r["attacked_pass"], r["attacked_n"]
        cp, cn = r["clean_pass"], r["clean_n"]
        astr = f"{ap_}/{an} = {ap_/an:.2f}" if an else "-"
        cstr = f"{cp}/{cn} = {cp/cn:.2f}" if cn else "-"
        print(f"{r['name']:<30}{str(r['policy'])[:12]:<13}{r['rounds']:>4}{r['candidates']:>6}"
              f"{r['invalid_clean']:>5}{astr:>16}{cstr:>14}{r['distinct_actions']:>6}")

    print("\nhow many candidates the clean baseline alone would produce:")
    for r in rows:
        n = r["attacked_n"]
        if not n:
            continue
        expected = n * (1 - base)
        print(f"  {r['name']:<30} {r['candidates']} observed vs {expected:.1f} expected "
              f"from {n} attacked flights at the baseline failure rate")
    print("\n'bad' = pairs whose clean control failed; verdict() excludes them from candidates.")
    print("'uniq' = distinct attack configurations the policy actually chose.")


if __name__ == "__main__":
    main()
