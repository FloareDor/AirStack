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
    from automated_testbench.paired import (
        is_autonomy_failure,
        reproducibility_label,
        run_pair,
    )
    from automated_testbench.threat_model import ThreatModel
    from automated_testbench.locking import try_lock, unlock
    from automated_testbench.reporting import write_campaign_report
else:
    from .run_trial import TrialRunner, atomic_json, utc_now
    from .scenario import load_scenario
    from .paired import is_autonomy_failure, reproducibility_label, run_pair
    from .threat_model import ThreatModel
    from .locking import try_lock, unlock
    from .reporting import write_campaign_report


def main() -> int:
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
    manifest_path = document.get(
        "threat_model", "../threat_models/generic-ws2-v1.yaml"
    )
    threat_model = ThreatModel.load((campaign_path.parent / manifest_path).resolve())
    paired = document.get("paired", True)
    if not isinstance(paired, bool):
        parser.error("campaign.paired must be boolean")
    failure_repetitions = document.get(
        "failure_repetitions", threat_model.budgets.get("failure_repetitions", 3)
    )
    if (
        isinstance(failure_repetitions, bool)
        or not isinstance(failure_repetitions, int)
        or failure_repetitions < 1
    ):
        parser.error("campaign.failure_repetitions must be a positive integer")
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    campaign_dir = args.results_dir / "campaigns" / f"{campaign_id}_{started}"
    campaign_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 2,
        "campaign_id": campaign_id,
        "threat_model_version": threat_model.version,
        "paired": paired,
        "failure_repetitions": failure_repetitions,
        "started_at_utc": utc_now(),
        "ended_at_utc": None,
        "trials": [],
    }
    atomic_json(campaign_dir / "campaign.json", manifest)
    lock_path = args.results_dir / ".trial.lock"
    args.results_dir.mkdir(parents=True, exist_ok=True)
    had_infrastructure_error = False
    with lock_path.open("a+", encoding="utf-8") as lock:
        if not try_lock(lock):
            print("another AirStack trial is already running", file=sys.stderr)
            return 3
        try:
            for scenario_entry in document["scenarios"]:
                if not isinstance(scenario_entry, str):
                    parser.error("campaign scenario entries must be paths")
                scenario_path = (campaign_path.parent / scenario_entry).resolve()
                scenario = load_scenario(scenario_path)
                if paired and not threat_model.is_clean(scenario):
                    pairs = [run_pair(scenario, threat_model, args.results_dir, 0)]
                    if is_autonomy_failure(pairs[0]["perturbed"]):
                        for repetition in range(1, failure_repetitions):
                            pairs.append(
                                run_pair(
                                    scenario,
                                    threat_model,
                                    args.results_dir,
                                    repetition,
                                )
                            )
                    entry = {
                        "scenario_id": scenario["scenario_id"],
                        "pairs": pairs,
                        "reproducibility": reproducibility_label(
                            pairs, failure_repetitions
                        ),
                    }
                    had_infrastructure_error |= any(
                        pair["verdict"] == "infrastructure_error" for pair in pairs
                    )
                else:
                    trial_dir, result = TrialRunner(
                        scenario, args.results_dir, teardown_stack=True
                    ).run()
                    entry = {
                        "scenario_id": scenario["scenario_id"],
                        "result_dir": str(trial_dir),
                        "outcome": result["outcome"],
                        "termination": result.get("termination"),
                        "metrics": result.get("metrics", {}),
                    }
                    had_infrastructure_error |= (
                        result["outcome"] == "infrastructure_error"
                    )
                manifest["trials"].append(entry)
                atomic_json(campaign_dir / "campaign.json", manifest)
                write_campaign_report(manifest, campaign_dir)
        finally:
            unlock(lock)
    manifest["ended_at_utc"] = utc_now()
    atomic_json(campaign_dir / "campaign.json", manifest)
    write_campaign_report(manifest, campaign_dir)
    print(json.dumps({"campaign_dir": str(campaign_dir), **manifest}, indent=2))
    return 2 if had_infrastructure_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
