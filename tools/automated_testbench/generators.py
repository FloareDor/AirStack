#!/usr/bin/env python3
"""Bounded scenario generators; generators never receive runner capabilities."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .threat_model import ThreatModel


@dataclass(frozen=True)
class GeneratedProposal:
    proposal_id: str
    parameters: dict[str, Any]
    generator: str
    rationale: str | None = None


class ScenarioGenerator(Protocol):
    def propose(self) -> GeneratedProposal: ...

    def observe(
        self, proposal: GeneratedProposal, result: Mapping[str, Any] | None
    ) -> None: ...


class UniformGenerator:
    """Uniform, deterministic sampling over every declared manifest parameter."""

    def __init__(self, threat_model: ThreatModel, seed: int) -> None:
        self.threat_model = threat_model
        self.seed = seed
        self._rng = random.Random(seed)
        self._sequence = 0

    def propose(self) -> GeneratedProposal:
        self._sequence += 1
        values = {
            name: _uniform_value(self._rng, spec)
            for name, spec in self.threat_model.parameters.items()
        }
        return GeneratedProposal(
            proposal_id=f"random-{self.seed}-{self._sequence:05d}",
            parameters=values,
            generator="uniform",
        )

    def observe(
        self, proposal: GeneratedProposal, result: Mapping[str, Any] | None
    ) -> None:
        del proposal, result


class GridGenerator:
    """Deterministic one-factor-at-a-time grid around the clean configuration."""

    def __init__(self, threat_model: ThreatModel) -> None:
        clean = {
            name: _clean_value(spec)
            for name, spec in threat_model.parameters.items()
        }
        self._proposals: list[dict[str, Any]] = []
        for name, spec in threat_model.parameters.items():
            for value in _grid_values(spec):
                if value == clean[name]:
                    continue
                proposal = dict(clean)
                proposal[name] = value
                self._proposals.append(proposal)
        self._sequence = 0

    def propose(self) -> GeneratedProposal:
        if self._sequence >= len(self._proposals):
            raise StopIteration("one-factor grid exhausted")
        parameters = self._proposals[self._sequence]
        self._sequence += 1
        return GeneratedProposal(
            proposal_id=f"grid-{self._sequence:05d}",
            parameters=dict(parameters),
            generator="one_factor_grid",
        )

    def observe(
        self, proposal: GeneratedProposal, result: Mapping[str, Any] | None
    ) -> None:
        del proposal, result


class OptunaTPEGenerator:
    """Optuna TPE backend with resumable SQLite-backed studies."""

    def __init__(
        self,
        threat_model: ThreatModel,
        seed: int,
        *,
        study_name: str,
        storage_url: str | None = None,
    ) -> None:
        try:
            import optuna
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "Optuna is required for the TPE backend; install requirements-search.txt"
            ) from exc
        self._optuna = optuna
        self.threat_model = threat_model
        self._study = optuna.create_study(
            study_name=study_name,
            storage=storage_url,
            load_if_exists=True,
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=seed),
        )
        self._pending: dict[str, Any] = {}

    def propose(self) -> GeneratedProposal:
        trial = self._study.ask()
        values = {
            name: _optuna_value(trial, name, spec)
            for name, spec in self.threat_model.parameters.items()
        }
        proposal_id = f"tpe-{trial.number:05d}"
        self._pending[proposal_id] = trial
        return GeneratedProposal(
            proposal_id=proposal_id,
            parameters=values,
            generator="optuna_tpe",
        )

    def observe(
        self, proposal: GeneratedProposal, result: Mapping[str, Any] | None
    ) -> None:
        trial = self._pending.pop(proposal.proposal_id)
        if result is None:
            self._study.tell(trial, state=self._optuna.trial.TrialState.FAIL)
            return
        score = adversarial_score(result)
        if score is None:
            self._study.tell(trial, state=self._optuna.trial.TrialState.FAIL)
        else:
            self._study.tell(trial, score)


def _uniform_value(rng: random.Random, spec: Mapping[str, Any]) -> Any:
    kind = spec["type"]
    if kind == "float":
        return rng.uniform(float(spec["min"]), float(spec["max"]))
    if kind == "int":
        return rng.randint(int(spec["min"]), int(spec["max"]))
    if kind == "categorical":
        return rng.choice(list(spec["categories"]))
    if kind == "bool":
        return bool(rng.getrandbits(1))
    raise ValueError(f"unsupported parameter type: {kind}")


def _clean_value(spec: Mapping[str, Any]) -> Any:
    if "clean" in spec:
        return spec["clean"]
    kind = spec["type"]
    if kind in {"float", "int"}:
        return spec["min"]
    if kind == "categorical":
        return spec["categories"][0]
    if kind == "bool":
        return False
    raise ValueError(f"unsupported parameter type: {kind}")


def _grid_values(spec: Mapping[str, Any]) -> list[Any]:
    kind = spec["type"]
    if kind == "float":
        low, high = float(spec["min"]), float(spec["max"])
        return list(dict.fromkeys((low, (low + high) / 2.0, high)))
    if kind == "int":
        low, high = int(spec["min"]), int(spec["max"])
        return list(dict.fromkeys((low, (low + high) // 2, high)))
    if kind == "categorical":
        return list(spec["categories"])
    if kind == "bool":
        return [False, True]
    raise ValueError(f"unsupported parameter type: {kind}")


def _optuna_value(trial: Any, name: str, spec: Mapping[str, Any]) -> Any:
    kind = spec["type"]
    if kind == "float":
        return trial.suggest_float(name, float(spec["min"]), float(spec["max"]))
    if kind == "int":
        return trial.suggest_int(name, int(spec["min"]), int(spec["max"]))
    if kind == "categorical":
        return trial.suggest_categorical(name, list(spec["categories"]))
    if kind == "bool":
        return trial.suggest_categorical(name, [False, True])
    raise ValueError(f"unsupported parameter type: {kind}")


def adversarial_score(result: Mapping[str, Any]) -> float | None:
    """Scalarize the documented lexicographic objective for Optuna TPE."""
    outcome = result.get("outcome")
    if outcome == "infrastructure_error":
        return None
    outcome_score = {
        "collision": 4000.0,
        "planner_stopped": 3000.0,
        "timeout": 2000.0,
        "goal_reached": 1000.0,
    }.get(str(outcome))
    if outcome_score is None:
        return None
    metrics = result.get("metrics", {})
    clearance = metrics.get("minimum_obstacle_clearance_m")
    if isinstance(clearance, (int, float)) and math.isfinite(float(clearance)):
        outcome_score += max(-100.0, min(100.0, -float(clearance)))
    efficiency = metrics.get("path_efficiency")
    if isinstance(efficiency, (int, float)) and math.isfinite(float(efficiency)):
        outcome_score += max(0.0, min(1.0, 1.0 - float(efficiency)))
    return outcome_score
