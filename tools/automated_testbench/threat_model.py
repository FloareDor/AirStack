#!/usr/bin/env python3
"""Versioned threat-model loading, proposal validation, and safe application."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from .scenario import ScenarioError, resolve_scenario


class ThreatModelError(ValueError):
    """Raised when a manifest or adversarial proposal violates the contract."""


_TARGET_TOKEN = re.compile(r"(?P<key>[^.\[\]]+)|\[(?P<index>\d+)\]")


@dataclass(frozen=True)
class ThreatModel:
    version: str
    parameters: Mapping[str, Mapping[str, Any]]
    budgets: Mapping[str, Any]
    source_path: Path

    @classmethod
    def load(cls, path: str | Path) -> "ThreatModel":
        source = Path(path).resolve()
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ThreatModelError(f"cannot load threat model {source}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ThreatModelError("threat model root must be a mapping")
        version = raw.get("version")
        parameters = raw.get("parameters")
        budgets = raw.get("budgets", {})
        if not isinstance(version, str) or not version:
            raise ThreatModelError("threat model version must be a non-empty string")
        if not isinstance(parameters, dict) or not parameters:
            raise ThreatModelError("threat model parameters must be a non-empty mapping")
        if not isinstance(budgets, dict):
            raise ThreatModelError("threat model budgets must be a mapping")
        checked: dict[str, Mapping[str, Any]] = {}
        for name, spec in parameters.items():
            if not isinstance(name, str) or not isinstance(spec, dict):
                raise ThreatModelError("each threat-model parameter must be a mapping")
            _validate_spec(name, spec)
            checked[name] = MappingProxyType(copy.deepcopy(spec))
        return cls(
            version=version,
            parameters=MappingProxyType(checked),
            budgets=MappingProxyType(copy.deepcopy(budgets)),
            source_path=source,
        )

    def inspect(self) -> dict[str, Any]:
        """Return a detached representation safe to expose to a generator/LLM."""
        return {
            "version": self.version,
            "parameters": {
                name: dict(spec) for name, spec in self.parameters.items()
            },
            "budgets": dict(self.budgets),
        }

    def validate(self, proposal: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(proposal, Mapping):
            raise ThreatModelError("proposal must be a mapping")
        unknown = sorted(set(proposal) - set(self.parameters))
        if unknown:
            raise ThreatModelError(
                "proposal contains undeclared parameters: " + ", ".join(unknown)
            )
        validated: dict[str, Any] = {}
        for name, value in proposal.items():
            validated[name] = _validate_value(name, value, self.parameters[name])
        return validated

    def extract(self, scenario: Mapping[str, Any]) -> dict[str, Any]:
        """Extract declared parameter values from an already resolved scenario."""
        return {
            name: _get_target(scenario, str(spec["target"]))
            for name, spec in self.parameters.items()
        }

    def role_of(self, name: str) -> str:
        return str(self.parameters[name].get("role", "attack"))

    def attack_parameters(self) -> dict[str, Mapping[str, Any]]:
        return {
            name: spec
            for name, spec in self.parameters.items()
            if self.role_of(name) == "attack"
        }

    def is_clean(self, scenario: Mapping[str, Any]) -> bool:
        values = self.extract(scenario)
        return all(
            "clean" not in spec or values[name] == spec["clean"]
            for name, spec in self.attack_parameters().items()
        )

    def apply(
        self,
        base_scenario: Mapping[str, Any],
        proposal: Mapping[str, Any],
        *,
        scenario_id: str | None = None,
        repetition: int = 0,
    ) -> dict[str, Any]:
        values = self.validate(proposal)
        raw = _editable_scenario(base_scenario)
        for name, value in values.items():
            _set_target(raw, str(self.parameters[name]["target"]), value)
        _synchronize_mission_alias(raw)
        raw["threat_model_version"] = self.version
        raw["repetition"] = repetition
        raw["adversary"] = {
            "proposal": copy.deepcopy(values),
            "threat_model_version": self.version,
        }
        if scenario_id is not None:
            raw["scenario_id"] = scenario_id
        try:
            return resolve_scenario(raw)
        except ScenarioError as exc:
            raise ThreatModelError(f"proposal resolves to an invalid scene: {exc}") from exc

    def clean_twin(
        self,
        scenario: Mapping[str, Any],
        *,
        repetition: int | None = None,
    ) -> dict[str, Any]:
        proposal = {
            name: spec["clean"]
            for name, spec in self.attack_parameters().items()
            if "clean" in spec
        }
        base_id = str(scenario.get("scenario_id", "scenario"))
        return self.apply(
            scenario,
            proposal,
            scenario_id=f"{base_id}__clean",
            repetition=(
                int(scenario.get("repetition", 0))
                if repetition is None
                else repetition
            ),
        )


def _validate_spec(name: str, spec: dict[str, Any]) -> None:
    kind = spec.get("type")
    if kind not in {"float", "int", "categorical", "bool"}:
        raise ThreatModelError(f"parameter {name}.type is unsupported")
    if not isinstance(spec.get("target"), str) or not spec["target"]:
        raise ThreatModelError(f"parameter {name}.target is required")
    role = spec.get("role", "attack")
    if role not in {"scene", "attack"}:
        raise ThreatModelError(f"parameter {name}.role must be 'scene' or 'attack'")
    if kind in {"float", "int"}:
        for bound in ("min", "max"):
            value = spec.get(bound)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ThreatModelError(f"parameter {name}.{bound} must be numeric")
            if not math.isfinite(float(value)):
                raise ThreatModelError(f"parameter {name}.{bound} must be finite")
        if spec["min"] > spec["max"]:
            raise ThreatModelError(f"parameter {name} has min greater than max")
    if kind == "categorical" and (
        not isinstance(spec.get("categories"), list) or not spec["categories"]
    ):
        raise ThreatModelError(f"parameter {name}.categories must be non-empty")
    if "clean" in spec:
        _validate_value(name, spec["clean"], spec)


def _validate_value(name: str, value: Any, spec: Mapping[str, Any]) -> Any:
    kind = spec["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise ThreatModelError(f"parameter {name} must be boolean")
        return value
    if kind == "categorical":
        if value not in spec["categories"]:
            raise ThreatModelError(
                f"parameter {name} must be one of {spec['categories']}"
            )
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ThreatModelError(f"parameter {name} must be {kind}")
    if kind == "int" and not isinstance(value, int):
        raise ThreatModelError(f"parameter {name} must be int")
    numeric = int(value) if kind == "int" else float(value)
    if not math.isfinite(float(numeric)):
        raise ThreatModelError(f"parameter {name} must be finite")
    if numeric < spec["min"] or numeric > spec["max"]:
        raise ThreatModelError(
            f"parameter {name}={numeric} is outside [{spec['min']}, {spec['max']}]"
        )
    return numeric


def _editable_scenario(scenario: Mapping[str, Any]) -> dict[str, Any]:
    raw = copy.deepcopy(dict(scenario))
    for generated in (
        "resolved",
        "schema_version",
        "clean_environment",
        "perturbations",
        "adversary",
    ):
        raw.pop(generated, None)
    return raw


def _set_target(document: dict[str, Any], target: str, value: Any) -> None:
    tokens = _target_tokens(target)
    if not tokens or "".join(str(token) for token in tokens) == "":
        raise ThreatModelError(f"invalid target path {target!r}")
    current: Any = document
    try:
        for token in tokens[:-1]:
            current = current[token]
        current[tokens[-1]] = copy.deepcopy(value)
    except (KeyError, IndexError, TypeError) as exc:
        raise ThreatModelError(f"target path does not exist: {target}") from exc


def _get_target(document: Mapping[str, Any], target: str) -> Any:
    current: Any = document
    try:
        for token in _target_tokens(target):
            current = current[token]
    except (KeyError, IndexError, TypeError) as exc:
        raise ThreatModelError(f"target path does not exist: {target}") from exc
    return copy.deepcopy(current)


def _target_tokens(target: str) -> list[str | int]:
    tokens: list[str | int] = []
    for match in _TARGET_TOKEN.finditer(target):
        tokens.append(
            int(match.group("index"))
            if match.group("index") is not None
            else str(match.group("key"))
        )
    return tokens


def _synchronize_mission_alias(document: dict[str, Any]) -> None:
    if "mission" in document:
        document["flight"] = copy.deepcopy(document["mission"])
    elif "flight" in document:
        document["mission"] = copy.deepcopy(document["flight"])
