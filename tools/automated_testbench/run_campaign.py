#!/usr/bin/env python3
"""Run a list of AirStack scenarios sequentially with one summary manifest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from automated_testbench.run_trial import TrialRunner, atomic_json, utc_now
    from automated_testbench.scenario import load_scenario
else:
    from .run_trial import TrialRunner, atomic_json, utc_now
    from .scenario import load_scenario


def main() -> int:
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument(
        "--results-dir", type=Path, default=Path("/home/ubuntu/airlab-data/trials")
    )
    args = parser.parse_args()
    campaign_path = args.campaign.resolve()
    document = yaml.safe_load(campaign_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(
        document.get("scenarios"), list
    ):
        parser.error("campaign YAML must contain a scenarios list")
    campaign_id = document.get("campaign_id", campaign_path.stem)
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    campaign_dir = args.results_dir / "campaigns" / f"{campaign_id}_{started}"
    campaign_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "started_at_utc": utc_now(),
        "ended_at_utc": None,
        "trials": [],
    }
    atomic_json(campaign_dir / "campaign.json", manifest)
    lock_path = args.results_dir / ".trial.lock"
    args.results_dir.mkdir(parents=True, exist_ok=True)
    had_infrastructure_error = False
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another AirStack trial is already running", file=sys.stderr)
            return 3
        for scenario_entry in document["scenarios"]:
            if not isinstance(scenario_entry, str):
                parser.error("campaign scenario entries must be paths")
            scenario_path = (campaign_path.parent / scenario_entry).resolve()
            scenario = load_scenario(scenario_path)
            trial_dir, result = TrialRunner(
                scenario, args.results_dir, teardown_stack=True
            ).run()
            manifest["trials"].append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "result_dir": str(trial_dir),
                    "outcome": result["outcome"],
                }
            )
            had_infrastructure_error |= result["outcome"] == "infrastructure_error"
            atomic_json(campaign_dir / "campaign.json", manifest)
    manifest["ended_at_utc"] = utc_now()
    atomic_json(campaign_dir / "campaign.json", manifest)
    print(json.dumps({"campaign_dir": str(campaign_dir), **manifest}, indent=2))
    return 2 if had_infrastructure_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
