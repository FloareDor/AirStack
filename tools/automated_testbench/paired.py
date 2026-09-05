#!/usr/bin/env python3
"""Clean-twin execution and reproducibility rules shared by all campaigns."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .run_trial import TrialRunner
from .scenario import configuration_hash
from .threat_model import ThreatModel


AUTONOMY_FAILURES = frozenset({"collision", "planner_stopped", "timeout"})
RunnerFactory = Callable[..., TrialRunner]


def is_autonomy_failure(result: dict[str, Any]) -> bool:
    return result.get("outcome") in AUTONOMY_FAILURES


def pair_verdict(clean: dict[str, Any], attacked: dict[str, Any]) -> str:
    if "infrastructure_error" in {clean.get("outcome"), attacked.get("outcome")}:
        return "infrastructure_error"
    if clean.get("outcome") != "goal_reached":
        return "invalid_clean_baseline"
    if is_autonomy_failure(attacked):
        return "autonomy_failure"
    return "pass"


def prepare_pair(
    attacked: dict[str, Any], threat_model: ThreatModel, repetition: int
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    proposal = threat_model.extract(attacked)
    attack_id = str(attacked["scenario_id"])
    resolved_attack = threat_model.apply(
        attacked, proposal, scenario_id=attack_id, repetition=repetition
    )
    clean = threat_model.clean_twin(attacked, repetition=repetition)
    stable = json.dumps(
        {"scenario_id": attack_id, "seed": attacked.get("seed"), "proposal": proposal},
        sort_keys=True,
        separators=(",", ":"),
    )
    pair_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    for role, scenario in (("clean", clean), ("perturbed", resolved_attack)):
        scenario["pair"] = {
            "pair_id": pair_id,
            "role": role,
            "repetition": repetition,
        }
        scenario["resolved"]["configuration_hash"] = configuration_hash(scenario)
    return pair_id, clean, resolved_attack


def run_pair(
    attacked: dict[str, Any],
    threat_model: ThreatModel,
    results_root: Path,
    repetition: int,
    *,
    runner_factory: RunnerFactory = TrialRunner,
) -> dict[str, Any]:
    pair_id, clean, perturbation = prepare_pair(attacked, threat_model, repetition)
    clean_dir, clean_result = runner_factory(
        clean, results_root, teardown_stack=True
    ).run()
    attack_dir, attack_result = runner_factory(
        perturbation, results_root, teardown_stack=True
    ).run()
    return {
        "pair_id": pair_id,
        "repetition": repetition,
        "clean": _trial_reference(clean_dir, clean_result),
        "perturbed": _trial_reference(attack_dir, attack_result),
        "verdict": pair_verdict(clean_result, attack_result),
    }

def reproducibility_label(pairs: list[dict[str, Any]], required: int = 3) -> str:
    if len(pairs) < required:
        return "unconfirmed"
    selected = pairs[:required]
    if any(pair["verdict"] == "infrastructure_error" for pair in selected):
        return "infrastructure_error"
    outcomes = [pair["perturbed"]["outcome"] for pair in selected]
    if (
        all(pair["verdict"] == "autonomy_failure" for pair in selected)
        and len(set(outcomes)) == 1
    ):
        return "reproducible"
    return "not_reproducible"


def _trial_reference(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_id": result["scenario_id"],
        "result_dir": str(path),
        "outcome": result["outcome"],
        "termination": copy.deepcopy(result.get("termination")),
        "metrics": copy.deepcopy(result.get("metrics", {})),
    }
