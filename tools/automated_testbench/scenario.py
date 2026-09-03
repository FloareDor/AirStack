#!/usr/bin/env python3
"""Scenario loading, validation, and deterministic obstacle resolution."""

from __future__ import annotations

import copy
import random
from pathlib import Path
from typing import Any

import yaml


STOCK_OBSTACLES = (
    {
        "id": "CenterGate",
        "position_m": [3.0, 0.0, 1.0],
        "size_m": [0.6, 0.8, 2.0],
    },
    {
        "id": "LeftOffset",
        "position_m": [5.1, -1.7, 1.0],
        "size_m": [0.7, 1.0, 2.0],
    },
    {
        "id": "RightOffset",
        "position_m": [7.2, 1.6, 1.0],
        "size_m": [0.7, 1.0, 2.0],
    },
)

ALLOWED_OUTCOMES = {
    "goal_reached",
    "collision",
    "timeout",
    "planner_stopped",
    "infrastructure_error",
}


class ScenarioError(ValueError):
    """Raised when a scenario cannot be safely or unambiguously resolved."""


def _required(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ScenarioError(f"{context}.{key} is required")
    return mapping[key]


def _number(value: Any, context: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioError(f"{context} must be a number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ScenarioError(f"{context} must be >= {minimum}")
    return result


def _vector(value: Any, context: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ScenarioError(f"{context} must be a {length}-element list")
    return [_number(item, f"{context}[{index}]") for index, item in enumerate(value)]


def load_scenario(path: str | Path) -> dict[str, Any]:
    scenario_path = Path(path).resolve()
    raw = _load_raw_scenario(scenario_path, [])
    return resolve_scenario(raw, source_path=scenario_path)


def _load_raw_scenario(path: Path, stack: list[Path]) -> dict[str, Any]:
    if path in stack:
        chain = " -> ".join(str(item) for item in [*stack, path])
        raise ScenarioError(f"scenario extends cycle: {chain}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioError(f"cannot load {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ScenarioError("scenario root must be a mapping")
    parent = raw.pop("extends", None)
    if parent is None:
        return raw
    if not isinstance(parent, str) or not parent:
        raise ScenarioError("scenario.extends must be a non-empty relative path")
    parent_path = (path.parent / parent).resolve()
    base = _load_raw_scenario(parent_path, [*stack, path])
    return _deep_merge(base, raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def resolve_scenario(
    raw: dict[str, Any], source_path: Path | None = None
) -> dict[str, Any]:
    scenario = copy.deepcopy(raw)
    scenario_id = _required(scenario, "scenario_id", "scenario")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioError("scenario.scenario_id must be a non-empty string")

    seed = scenario.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ScenarioError("scenario.seed must be an integer or null")

    planner = _required(scenario, "planner", "scenario")
    if not isinstance(planner, dict):
        raise ScenarioError("scenario.planner must be a mapping")
    if planner.get("method") != "mononav":
        raise ScenarioError("only planner.method=mononav is supported in milestone 1")
    if planner.get("depth_source") not in {"zoe", "ground-truth"}:
        raise ScenarioError("planner.depth_source must be zoe or ground-truth")

    flight = _required(scenario, "flight", "scenario")
    if not isinstance(flight, dict):
        raise ScenarioError("scenario.flight must be a mapping")
    flight["start_pose"] = _vector(
        _required(flight, "start_pose", "scenario.flight"),
        "scenario.flight.start_pose",
        4,
    )
    if abs(flight["start_pose"][3]) > 1e-9:
        raise ScenarioError("milestone 1 supports only a zero-yaw start pose")
    flight["takeoff_height_m"] = _number(
        _required(flight, "takeoff_height_m", "scenario.flight"),
        "scenario.flight.takeoff_height_m",
        minimum=0.1,
    )
    flight["takeoff_velocity_m_s"] = _number(
        flight.get("takeoff_velocity_m_s", 0.3),
        "scenario.flight.takeoff_velocity_m_s",
        minimum=0.01,
    )
    goal = _required(flight, "goal", "scenario.flight")
    if not isinstance(goal, dict):
        raise ScenarioError("scenario.flight.goal must be a mapping")
    if goal.get("frame") != "takeoff_odometry":
        raise ScenarioError("only flight.goal.frame=takeoff_odometry is supported")
    goal["offset_m"] = _vector(
        _required(goal, "offset_m", "scenario.flight.goal"),
        "scenario.flight.goal.offset_m",
        3,
    )
    if abs(goal["offset_m"][1]) > 1e-9 or abs(goal["offset_m"][2]) > 1e-9:
        raise ScenarioError("MonoNav milestone 1 supports only a forward goal offset")
    if goal["offset_m"][0] <= 0:
        raise ScenarioError("flight.goal.offset_m[0] must be positive")
    goal["radius_m"] = _number(
        _required(goal, "radius_m", "scenario.flight.goal"),
        "scenario.flight.goal.radius_m",
        minimum=0.01,
    )
    if abs(goal["radius_m"] - 1.0) > 1e-9:
        raise ScenarioError("milestone 1 uses the existing 1.0 m MonoNav goal radius")

    obstacles = _required(scenario, "obstacles", "scenario")
    if not isinstance(obstacles, dict) or obstacles.get("preset") != "slalom_3box_v1":
        raise ScenarioError("only obstacles.preset=slalom_3box_v1 is supported")
    variation = obstacles.setdefault("variation", {})
    if not isinstance(variation, dict):
        raise ScenarioError("scenario.obstacles.variation must be a mapping")
    lateral = _number(
        variation.get("lateral_m", 0.0),
        "scenario.obstacles.variation.lateral_m",
        minimum=0.0,
    )
    longitudinal = _number(
        variation.get("longitudinal_m", 0.0),
        "scenario.obstacles.variation.longitudinal_m",
        minimum=0.0,
    )
    scale = _number(
        variation.get("scale_fraction", 0.0),
        "scenario.obstacles.variation.scale_fraction",
        minimum=0.0,
    )
    if scale >= 1.0:
        raise ScenarioError("scenario.obstacles.variation.scale_fraction must be < 1")
    variation.update(
        {
            "lateral_m": lateral,
            "longitudinal_m": longitudinal,
            "scale_fraction": scale,
        }
    )
    if seed is None and any(value > 0 for value in (lateral, longitudinal, scale)):
        raise ScenarioError("a seed is required when obstacle variation is non-zero")

    trial = _required(scenario, "trial", "scenario")
    if not isinstance(trial, dict):
        raise ScenarioError("scenario.trial must be a mapping")
    trial["timeout_s"] = _number(
        _required(trial, "timeout_s", "scenario.trial"),
        "scenario.trial.timeout_s",
        minimum=0.01,
    )
    trial["startup_timeout_s"] = _number(
        trial.get("startup_timeout_s", 240.0),
        "scenario.trial.startup_timeout_s",
        minimum=1.0,
    )
    trial["planner_start_timeout_s"] = _number(
        trial.get("planner_start_timeout_s", 90.0),
        "scenario.trial.planner_start_timeout_s",
        minimum=1.0,
    )
    trial["bridge_start_timeout_s"] = _number(
        trial.get("bridge_start_timeout_s", 60.0),
        "scenario.trial.bridge_start_timeout_s",
        minimum=1.0,
    )
    trial["robot_radius_m"] = _number(
        trial.get("robot_radius_m", 0.25),
        "scenario.trial.robot_radius_m",
        minimum=0.0,
    )

    airstack = _required(scenario, "airstack", "scenario")
    mononav = _required(scenario, "mononav", "scenario")
    if not isinstance(airstack, dict) or not isinstance(mononav, dict):
        raise ScenarioError("scenario.airstack and scenario.mononav must be mappings")
    for config, name in ((airstack, "airstack"), (mononav, "mononav")):
        repo = _required(config, "repo", f"scenario.{name}")
        if not isinstance(repo, str) or not repo.startswith("/"):
            raise ScenarioError(f"scenario.{name}.repo must be an absolute path")

    bridge = mononav.setdefault("bridge", {})
    bridge.setdefault("manage", True)
    bridge.setdefault("server_url", "http://airstack-robot-desktop-1:8765")
    bridge.setdefault("health_url", "http://127.0.0.1:8765")
    if not isinstance(bridge["manage"], bool):
        raise ScenarioError("scenario.monav.bridge.manage must be boolean")

    resolved_obstacles = resolve_obstacles(seed, lateral, longitudinal, scale)
    scenario["resolved"] = {
        "source_path": None if source_path is None else str(source_path),
        "obstacles": resolved_obstacles,
        "scene_environment": scene_environment(seed, lateral, longitudinal, scale),
    }
    scenario["schema_version"] = 1
    return scenario


def resolve_obstacles(
    seed: int | None,
    lateral_jitter_m: float,
    longitudinal_jitter_m: float,
    scale_jitter: float,
) -> list[dict[str, Any]]:
    """Mirror the Isaac launcher random.Random call order exactly."""
    rng = random.Random(seed) if seed is not None else None
    resolved: list[dict[str, Any]] = []
    for stock in STOCK_OBSTACLES:
        position = list(stock["position_m"])
        size = list(stock["size_m"])
        obstacle_scale = 1.0
        if rng is not None:
            position[0] += rng.uniform(-longitudinal_jitter_m, longitudinal_jitter_m)
            position[1] += rng.uniform(-lateral_jitter_m, lateral_jitter_m)
            obstacle_scale = rng.uniform(1.0 - scale_jitter, 1.0 + scale_jitter)
            size = [component * obstacle_scale for component in size]
        resolved.append(
            {
                "id": stock["id"],
                "position_m": position,
                "size_m": size,
                "uniform_scale": obstacle_scale,
            }
        )
    return resolved


def scene_environment(
    seed: int | None,
    lateral_jitter_m: float,
    longitudinal_jitter_m: float,
    scale_jitter: float,
) -> dict[str, str]:
    return {
        "MONONAV_DEMO_OBSTACLES": "true",
        "MONONAV_SCENE_SEED": "" if seed is None else str(seed),
        "MONONAV_SCENE_LATERAL_JITTER_M": str(lateral_jitter_m),
        "MONONAV_SCENE_LONGITUDINAL_JITTER_M": str(longitudinal_jitter_m),
        "MONONAV_SCENE_SCALE_JITTER": str(scale_jitter),
    }


def dump_scenario(scenario: dict[str, Any], path: Path) -> None:
    path.write_text(
        yaml.safe_dump(scenario, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
