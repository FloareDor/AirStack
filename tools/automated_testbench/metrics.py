#!/usr/bin/env python3
"""Pure metric functions for the automated test bench."""

from __future__ import annotations

import math
from typing import Any, Iterable


def distance(a: Iterable[float], b: Iterable[float]) -> float:
    return math.dist(tuple(a), tuple(b))


def path_length(samples: list[dict[str, Any]]) -> float:
    return sum(
        distance(previous["position_m"], current["position_m"])
        for previous, current in zip(samples, samples[1:])
    )


def point_to_box_distance(
    point: Iterable[float], position: Iterable[float], size: Iterable[float]
) -> float:
    """Euclidean distance from a point to an axis-aligned box (zero inside)."""
    deltas = []
    for coordinate, center, extent in zip(point, position, size):
        deltas.append(max(abs(coordinate - center) - extent / 2.0, 0.0))
    return math.sqrt(sum(component * component for component in deltas))


def obstacle_clearance(
    point: Iterable[float], obstacles: list[dict[str, Any]], robot_radius_m: float
) -> float | None:
    if not obstacles:
        return None
    return min(
        point_to_box_distance(point, obstacle["position_m"], obstacle["size_m"])
        - robot_radius_m
        for obstacle in obstacles
    )


def summarize(
    samples: list[dict[str, Any]],
    goal_position_m: list[float] | None,
    obstacles: list[dict[str, Any]],
    robot_radius_m: float,
    goal_reached_index: int | None,
    planner_hold_count: int,
    planner_recovery_count: int,
) -> dict[str, Any]:
    final_distance = None
    if samples and goal_position_m is not None:
        final_distance = distance(samples[-1]["position_m"], goal_position_m)
    clearances = [
        value
        for sample in samples
        if (
            value := obstacle_clearance(sample["position_m"], obstacles, robot_radius_m)
        )
        is not None
    ]
    time_to_goal = None
    if goal_reached_index is not None and samples:
        time_to_goal = (
            samples[goal_reached_index]["sim_time_s"] - samples[0]["sim_time_s"]
        )
    return {
        "time_to_goal_s": time_to_goal,
        "path_length_m": path_length(samples),
        "final_distance_to_goal_m": final_distance,
        "planner_hold_count": planner_hold_count,
        "planner_recovery_count": planner_recovery_count,
        "minimum_obstacle_clearance_m": min(clearances) if clearances else None,
        "odometry_sample_count": len(samples),
        "odometry_start_sim_time_s": samples[0]["sim_time_s"] if samples else None,
        "odometry_end_sim_time_s": samples[-1]["sim_time_s"] if samples else None,
    }
