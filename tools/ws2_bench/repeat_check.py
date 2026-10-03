"""Fly one fixed configuration N times to measure how repeatable an outcome is.

The adaptive campaigns fly each configuration once and treat the outcome as the
property of that configuration. That is only valid if an identical configuration
produces an identical outcome. Repeat archive data shows it does not, so this
tool measures the flip rate directly instead of assuming it either way.

Unlike the campaign's clean validation, this never stops at the first failure.
A run that stops early cannot measure a rate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

from agent_schema import action_to_episode, validate_action
from campaign import clean_twin
from episode import atomic, fingerprint, resolved, run_episode
from mission import SUCCESSES, defaults


SPREAD_KEYS = ("minimum_obstacle_clearance_m", "mission_progress_percent", "path_length_m",
               "final_distance_to_goal_m", "time_to_goal_s", "mean_obstacle_clearance_m")


def build_episode(action, planner, seed, clean, label):
    episode = action_to_episode(action, planner, seed, label, defaults(planner))
    return clean_twin(episode) if clean else resolved(episode)


def summarize(results):
    outcomes = {}
    for result in results:
        outcomes[result["outcome"]] = outcomes.get(result["outcome"], 0) + 1
    passes = sum(count for outcome, count in outcomes.items() if outcome in SUCCESSES)
    spread = {}
    for key in SPREAD_KEYS:
        values = [r.get("metrics", {}).get(key) for r in results]
        values = [float(v) for v in values if isinstance(v, (int, float))]
        if len(values) < 2:
            continue
        spread[key] = {"n": len(values), "min": min(values), "max": max(values),
                       "spread": max(values) - min(values), "mean": statistics.fmean(values),
                       "sd": statistics.pstdev(values)}
    return {"flights": len(results), "outcomes": outcomes, "pass_count": passes,
            "pass_rate": passes / len(results) if results else None,
            "outcome_is_stable": len(outcomes) == 1, "metric_spread": spread}


def run_repeat(output, action, planner, seed, repeats, clean, record_bags, label):
    """Fly the same resolved episode `repeats` times, reusing any saved attempt."""
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    episode = build_episode(action, planner, seed, clean, label)
    expected = fingerprint(episode)
    atomic(root / "config.json", {"action": validate_action(action), "planner": planner, "seed": seed,
                                  "clean": clean, "repeats": repeats, "configuration_hash": expected,
                                  "episode": episode})
    results = []
    for index in range(repeats):
        folder = root / f"attempt_{index:02d}"
        saved = folder / "result.json"
        if saved.exists():
            result = json.loads(saved.read_text())
            if result["configuration_hash"] != expected:
                raise ValueError(f"{folder} holds a different configuration")
        else:
            result = run_episode(episode, folder, record_bag=record_bags)
        results.append(result)
        atomic(root / "summary.json", dict(summarize(results), configuration_hash=expected,
                                           complete=len(results) == repeats))
        print(f"attempt {index}: {result['outcome']} "
              f"clearance={result.get('metrics', {}).get('minimum_obstacle_clearance_m')} "
              f"progress={result.get('metrics', {}).get('mission_progress_percent')}", flush=True)
    summary = dict(summarize(results), configuration_hash=expected, complete=True)
    atomic(root / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--planner", choices=("mononav", "kim"), default="mononav")
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--layout", default="easy")
    parser.add_argument("--layout-seed", type=int, default=2)
    parser.add_argument("--delay-s", type=float, default=0.0)
    parser.add_argument("--patch-size-m", type=float, default=0.6)
    parser.add_argument("--patch-start-s", type=float, default=0.0)
    parser.add_argument("--patch-duration-s", type=float, default=0.0)
    parser.add_argument("--patch", dest="patch_enabled", action="store_true")
    parser.add_argument("--clean", action="store_true",
                        help="fly the clean twin: delay and patch forced off")
    parser.add_argument("--record-bags", action="store_true")
    parser.add_argument("--label", default="repeatability check")
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2; one flight cannot measure a rate")
    action = {"layout": args.layout, "layout_seed": args.layout_seed, "delay_s": args.delay_s,
              "patch_enabled": args.patch_enabled, "patch_size_m": args.patch_size_m,
              "patch_start_s": args.patch_start_s, "patch_duration_s": args.patch_duration_s}
    if not args.patch_enabled:
        action["patch_start_s"] = 0.0
        action["patch_duration_s"] = 0.0
    summary = run_repeat(args.output, action, args.planner, args.seed, args.repeats,
                         args.clean, args.record_bags, args.label)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
