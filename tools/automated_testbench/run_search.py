#!/usr/bin/env python3
"""Run resumable, equal-budget random or Optuna-TPE paired campaigns."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from automated_testbench.generators import (
        GridGenerator,
        OptunaTPEGenerator,
        UniformGenerator,
    )
    from automated_testbench.paired import is_autonomy_failure, run_pair
    from automated_testbench.run_trial import atomic_json, utc_now
    from automated_testbench.scenario import load_scenario, resolve_scenario
    from automated_testbench.threat_model import ThreatModel, ThreatModelError
else:
    from .generators import GridGenerator, OptunaTPEGenerator, UniformGenerator
    from .paired import is_autonomy_failure, run_pair
    from .run_trial import atomic_json, utc_now
    from .scenario import load_scenario, resolve_scenario
    from .threat_model import ThreatModel, ThreatModelError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_scenario", type=Path)
    parser.add_argument("--backend", choices=("grid", "random", "tpe"), required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--trial-budget", type=int)
    parser.add_argument("--wall-clock-budget-s", type=float)
    parser.add_argument(
        "--threat-model",
        type=Path,
        default=Path(__file__).resolve().parent
        / "threat_models"
        / "generic-ws2-v2.yaml",
    )
    parser.add_argument(
        "--results-dir", type=Path, default=Path("/home/ubuntu/airlab-data/trials")
    )
    parser.add_argument(
        "--campaign-dir",
        type=Path,
        help="resume this directory, or create it when it does not exist",
    )
    args = parser.parse_args()

    threat_model = ThreatModel.load(args.threat_model)
    trial_budget = args.trial_budget or int(threat_model.budgets.get("max_trials", 50))
    wall_budget = args.wall_clock_budget_s or float(
        threat_model.budgets.get("max_wall_clock_s", 14400)
    )
    repetitions = int(threat_model.budgets.get("failure_repetitions", 3))
    if trial_budget < 1 or wall_budget <= 0:
        parser.error("trial and wall-clock budgets must be positive")

    campaign_dir = args.campaign_dir
    if campaign_dir is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        campaign_dir = (
            args.results_dir / "search" / f"{args.backend}_seed{args.seed}_{stamp}"
        )
    campaign_dir = campaign_dir.resolve()
    state_path = campaign_dir / "search.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        _check_resume(state, args.backend, args.seed, threat_model.version)
    else:
        campaign_dir.mkdir(parents=True, exist_ok=False)
        state = {
            "schema_version": 1,
            "backend": args.backend,
            "seed": args.seed,
            "threat_model_version": threat_model.version,
            "base_scenario": str(args.base_scenario.resolve()),
            "trial_budget": trial_budget,
            "wall_clock_budget_s": wall_budget,
            "failure_repetitions": repetitions,
            "started_at_utc": utc_now(),
            "ended_at_utc": None,
            "elapsed_wall_s": 0.0,
            "attempts": 0,
            "pairs_run": 0,
            "proposals": [],
        }
        atomic_json(state_path, state)

    base = load_scenario(args.base_scenario)
    if base.get("seed") is None:
        # Search randomization must be replayable even when the stock base is used.
        editable = dict(base)
        editable.pop("resolved", None)
        editable["seed"] = args.seed
        base = resolve_scenario(editable)

    generator = _generator(args.backend, threat_model, args.seed, campaign_dir)
    if args.backend in {"grid", "random"}:
        for _ in range(int(state["attempts"])):
            try:
                generator.propose()
            except StopIteration:
                break

    run_started = time.monotonic()
    prior_elapsed = float(state.get("elapsed_wall_s", 0.0))
    max_attempts = max(trial_budget * 20, 100)
    while state["pairs_run"] < trial_budget and state["attempts"] < max_attempts:
        elapsed = prior_elapsed + (time.monotonic() - run_started)
        if elapsed >= wall_budget:
            break
        try:
            proposal = generator.propose()
        except StopIteration:
            break
        state["attempts"] += 1
        record: dict[str, Any] = {
            "proposal_id": proposal.proposal_id,
            "generator": proposal.generator,
            "parameters": proposal.parameters,
            "rationale": proposal.rationale,
            "validator": None,
            "pairs": [],
            "reproducible": False,
        }
        try:
            scenario = threat_model.apply(
                base,
                proposal.parameters,
                scenario_id=proposal.proposal_id,
                repetition=0,
            )
            record["validator"] = {"accepted": True, "error": None}
        except ThreatModelError as exc:
            record["validator"] = {"accepted": False, "error": str(exc)}
            state["proposals"].append(record)
            generator.observe(proposal, None)
            _checkpoint(state_path, state, prior_elapsed, run_started)
            continue

        state["proposals"].append(record)
        _checkpoint(state_path, state, prior_elapsed, run_started)

        while len(record["pairs"]) < repetitions:
            if state["pairs_run"] >= trial_budget:
                break
            elapsed = prior_elapsed + (time.monotonic() - run_started)
            if elapsed >= wall_budget:
                break
            repetition = len(record["pairs"])
            pair = run_pair(
                scenario, threat_model, args.results_dir, repetition=repetition
            )
            record["pairs"].append(pair)
            state["pairs_run"] += 1
            _checkpoint(state_path, state, prior_elapsed, run_started)
            if repetition == 0 and not is_autonomy_failure(pair["perturbed"]):
                break
            if pair["verdict"] in {
                "infrastructure_error",
                "invalid_clean_baseline",
            }:
                break

        if len(record["pairs"]) >= repetitions:
            outcomes = [pair["perturbed"]["outcome"] for pair in record["pairs"]]
            record["reproducible"] = (
                len(set(outcomes)) == 1
                and all(pair["verdict"] == "autonomy_failure" for pair in record["pairs"])
            )
        observed = (
            record["pairs"][0]["perturbed"]
            if record["pairs"] and record["pairs"][0]["verdict"] in {"pass", "autonomy_failure"}
            else None
        )
        generator.observe(proposal, observed)
        _checkpoint(state_path, state, prior_elapsed, run_started)

    state["elapsed_wall_s"] = prior_elapsed + (time.monotonic() - run_started)
    state["ended_at_utc"] = utc_now()
    atomic_json(state_path, state)
    print(json.dumps({"campaign_dir": str(campaign_dir), **state}, indent=2))
    return 0


def _generator(
    backend: str, threat_model: ThreatModel, seed: int, campaign_dir: Path
) -> Any:
    if backend == "random":
        return UniformGenerator(threat_model, seed)
    if backend == "grid":
        return GridGenerator(threat_model)
    database = (campaign_dir / "optuna.sqlite3").as_posix()
    return OptunaTPEGenerator(
        threat_model,
        seed,
        study_name=f"ws2-{campaign_dir.name}",
        storage_url=f"sqlite:///{database}",
    )


def _checkpoint(
    path: Path, state: dict[str, Any], prior_elapsed: float, run_started: float
) -> None:
    state["elapsed_wall_s"] = prior_elapsed + (time.monotonic() - run_started)
    atomic_json(path, state)


def _check_resume(
    state: dict[str, Any], backend: str, seed: int, threat_model_version: str
) -> None:
    expected = {
        "backend": backend,
        "seed": seed,
        "threat_model_version": threat_model_version,
    }
    mismatches = [key for key, value in expected.items() if state.get(key) != value]
    if mismatches:
        raise SystemExit("cannot resume: changed " + ", ".join(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
