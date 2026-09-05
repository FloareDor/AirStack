#!/usr/bin/env python3
"""Auditable, bounded facade for an LLM adversary.

This module intentionally exposes structured data methods only.  It does not
accept commands, paths, launch arguments, ROS topics, or a runner object from
the model.  The owning application supplies the fixed base scenario and uses
the same paired executor as random/TPE campaigns.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .paired import is_autonomy_failure, run_pair
from .run_trial import atomic_json, utc_now
from .threat_model import ThreatModel, ThreatModelError


PairRunner = Callable[[dict[str, Any], ThreatModel, Path, int], dict[str, Any]]


@dataclass(frozen=True)
class AdversaryLimits:
    max_trials: int
    max_wall_clock_s: float
    failure_repetitions: int = 3


class BoundedAdversary:
    def __init__(
        self,
        base_scenario: Mapping[str, Any],
        threat_model: ThreatModel,
        results_root: Path,
        audit_path: Path,
        *,
        limits: AdversaryLimits | None = None,
        pair_runner: PairRunner = run_pair,
    ) -> None:
        self._base = copy.deepcopy(dict(base_scenario))
        self._model = threat_model
        self._results_root = results_root
        self._audit_path = audit_path
        self._pair_runner = pair_runner
        self._limits = limits or AdversaryLimits(
            max_trials=int(threat_model.budgets.get("max_trials", 50)),
            max_wall_clock_s=float(threat_model.budgets.get("max_wall_clock_s", 14400)),
            failure_repetitions=int(
                threat_model.budgets.get("failure_repetitions", 3)
            ),
        )
        self._started = time.monotonic()
        self._audit: dict[str, Any] = {
            "schema_version": 1,
            "started_at_utc": utc_now(),
            "threat_model": threat_model.inspect(),
            "limits": self._limits.__dict__,
            "model_configurations": [],
            "proposals": [],
            "trials_used": 0,
        }
        self._checkpoint()

    def inspect_threat_model(self) -> dict[str, Any]:
        return self._model.inspect()

    def propose_batch(
        self,
        proposals: list[Mapping[str, Any]],
        *,
        rationale: str | None = None,
        model_configuration: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(proposals, list):
            raise ThreatModelError("proposals must be a list of parameter mappings")
        if model_configuration is not None:
            self._audit["model_configurations"].append(copy.deepcopy(dict(model_configuration)))
        decisions: list[dict[str, Any]] = []
        for values in proposals:
            record = {
                "proposal_id": f"llm-{len(self._audit['proposals']) + 1:05d}",
                "parameters": copy.deepcopy(dict(values)) if isinstance(values, Mapping) else values,
                "rationale": rationale,
                "validator": None,
                "pairs": [],
            }
            try:
                validated = self._model.validate(values)
                record["parameters"] = validated
                record["validator"] = {"accepted": True, "error": None}
            except (ThreatModelError, TypeError, ValueError) as exc:
                record["validator"] = {"accepted": False, "error": str(exc)}
            self._audit["proposals"].append(record)
            decisions.append(copy.deepcopy(record))
        self._checkpoint()
        return decisions

    def run_validated_campaign(self, proposal_ids: list[str]) -> list[dict[str, Any]]:
        """Run only already-accepted proposals within independent fixed budgets."""
        records = {record["proposal_id"]: record for record in self._audit["proposals"]}
        summaries: list[dict[str, Any]] = []
        for proposal_id in proposal_ids:
            if proposal_id not in records:
                raise ThreatModelError(f"unknown proposal {proposal_id}")
            record = records[proposal_id]
            if not record["validator"]["accepted"]:
                summaries.append({"proposal_id": proposal_id, "status": "rejected"})
                continue
            if record["pairs"]:
                summaries.append({"proposal_id": proposal_id, "status": "already_run"})
                continue
            self._ensure_budget()
            scenario = self._model.apply(
                self._base,
                record["parameters"],
                scenario_id=proposal_id,
                repetition=0,
            )
            pair = self._pair_runner(scenario, self._model, self._results_root, 0)
            record["pairs"].append(pair)
            self._audit["trials_used"] += 1
            if is_autonomy_failure(pair["perturbed"]):
                for repetition in range(1, self._limits.failure_repetitions):
                    self._ensure_budget()
                    replay = self._pair_runner(
                        scenario, self._model, self._results_root, repetition
                    )
                    record["pairs"].append(replay)
                    self._audit["trials_used"] += 1
                    if replay["verdict"] != "autonomy_failure":
                        break
            summaries.append(self._summarize(record))
            self._checkpoint()
        return summaries

    def inspect_results(self) -> list[dict[str, Any]]:
        return [self._summarize(record) for record in self._audit["proposals"]]

    def request_exact_replay(self, proposal_id: str) -> dict[str, Any]:
        records = {record["proposal_id"]: record for record in self._audit["proposals"]}
        record = records.get(proposal_id)
        if record is None or not record["validator"]["accepted"]:
            raise ThreatModelError(f"accepted proposal {proposal_id} is required")
        self._ensure_budget()
        repetition = len(record["pairs"])
        scenario = self._model.apply(
            self._base,
            record["parameters"],
            scenario_id=proposal_id,
            repetition=repetition,
        )
        pair = self._pair_runner(scenario, self._model, self._results_root, repetition)
        record["pairs"].append(pair)
        self._audit["trials_used"] += 1
        self._checkpoint()
        return self._summarize(record)

    def _ensure_budget(self) -> None:
        if self._audit["trials_used"] >= self._limits.max_trials:
            raise RuntimeError("LLM adversary trial budget exhausted")
        if time.monotonic() - self._started >= self._limits.max_wall_clock_s:
            raise RuntimeError("LLM adversary wall-clock budget exhausted")

    @staticmethod
    def _summarize(record: Mapping[str, Any]) -> dict[str, Any]:
        pairs = record.get("pairs", [])
        return {
            "proposal_id": record["proposal_id"],
            "validator": copy.deepcopy(record["validator"]),
            "pair_count": len(pairs),
            "verdicts": [pair["verdict"] for pair in pairs],
            "outcomes": [pair["perturbed"]["outcome"] for pair in pairs],
        }

    def _checkpoint(self) -> None:
        self._audit["elapsed_wall_s"] = time.monotonic() - self._started
        atomic_json(self._audit_path, self._audit)
