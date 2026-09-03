"""Fast tests for scenario resolution and mission metric computation."""

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from automated_testbench.metrics import (  # noqa: E402
    obstacle_clearance,
    path_length,
    point_to_box_distance,
    summarize,
)
from automated_testbench.run_trial import EventRecorder, TrialState  # noqa: E402
from automated_testbench.scenario import (  # noqa: E402
    STOCK_OBSTACLES,
    ScenarioError,
    load_scenario,
    resolve_scenario,
)


SCENARIOS = TOOLS_DIR / "automated_testbench" / "scenarios"


def test_stock_scenario_preserves_legacy_geometry():
    scenario = load_scenario(SCENARIOS / "stock.yaml")
    resolved = scenario["resolved"]["obstacles"]
    assert [obstacle["position_m"] for obstacle in resolved] == [
        obstacle["position_m"] for obstacle in STOCK_OBSTACLES
    ]
    assert [obstacle["size_m"] for obstacle in resolved] == [
        obstacle["size_m"] for obstacle in STOCK_OBSTACLES
    ]
    assert scenario["resolved"]["scene_environment"]["MONONAV_SCENE_SEED"] == ""


def test_seed_one_resolves_identically_every_time():
    first = load_scenario(SCENARIOS / "medium_seed1.yaml")
    second = load_scenario(SCENARIOS / "medium_seed1.yaml")
    assert first["resolved"]["obstacles"] == second["resolved"]["obstacles"]
    assert first["resolved"]["scene_environment"] == {
        "MONONAV_DEMO_OBSTACLES": "true",
        "MONONAV_SCENE_SEED": "1",
        "MONONAV_SCENE_LATERAL_JITTER_M": "0.45",
        "MONONAV_SCENE_LONGITUDINAL_JITTER_M": "0.25",
        "MONONAV_SCENE_SCALE_JITTER": "0.1",
    }


def test_different_seeds_change_geometry():
    seed_one = load_scenario(SCENARIOS / "medium_seed1.yaml")
    seed_two = load_scenario(SCENARIOS / "medium_seed2.yaml")
    assert seed_one["resolved"]["obstacles"] != seed_two["resolved"]["obstacles"]


def test_variation_requires_seed():
    stock = load_scenario(SCENARIOS / "stock.yaml")
    stock.pop("resolved")
    stock["obstacles"]["variation"]["lateral_m"] = 0.1
    with pytest.raises(ScenarioError, match="seed is required"):
        resolve_scenario(stock)


def test_path_length_uses_three_dimensional_odometry():
    samples = [
        {"position_m": [0.0, 0.0, 0.0]},
        {"position_m": [3.0, 4.0, 0.0]},
        {"position_m": [3.0, 4.0, 12.0]},
    ]
    assert path_length(samples) == pytest.approx(17.0)


def test_axis_aligned_box_clearance_accounts_for_robot_radius():
    obstacle = {"position_m": [3.0, 0.0, 1.0], "size_m": [0.6, 0.8, 2.0]}
    assert point_to_box_distance(
        [2.0, 0.0, 1.0], obstacle["position_m"], obstacle["size_m"]
    ) == pytest.approx(0.7)
    assert obstacle_clearance([2.0, 0.0, 1.0], [obstacle], 0.25) == pytest.approx(0.45)
    assert obstacle_clearance([3.0, 0.0, 1.0], [obstacle], 0.25) == pytest.approx(-0.25)


def test_summary_matches_independent_time_and_length_calculation():
    samples = [
        {"sim_time_s": 10.0, "position_m": [0.0, 0.0, 1.0]},
        {"sim_time_s": 11.0, "position_m": [3.0, 4.0, 1.0]},
        {"sim_time_s": 12.5, "position_m": [6.0, 8.0, 1.0]},
    ]
    metrics = summarize(samples, [6.0, 8.0, 1.0], [], 0.25, 2, 3, 4)
    assert metrics["time_to_goal_s"] == pytest.approx(2.5)
    assert metrics["path_length_m"] == pytest.approx(10.0)
    assert metrics["final_distance_to_goal_m"] == pytest.approx(0.0)
    assert metrics["planner_hold_count"] == 3
    assert metrics["planner_recovery_count"] == 4


def test_planner_events_are_counted_without_scraping_frame_noise(tmp_path):
    events = EventRecorder(tmp_path / "events.jsonl")
    state = TrialState([8.0, 0.0, 1.0], 1.0, [], 0.25, events)
    state.planner_line("World-frame goal initialized at [8.2, -0.17, 0.96]")
    state.planner_line("UNSAFE HOLD: {'success': True}")
    state.planner_line("RECOVERY 1/12: blocked yaw scan, yaw_step=25.0 deg")
    state.planner_line(
        "Mission stopping (goal threshold reached) at goal distance 0.90 m"
    )
    events.close()
    assert state.planner_ready.is_set()
    assert state.planner_hold_count == 1
    assert state.planner_recovery_count == 1
    assert state.planner_terminal_reason == "goal threshold reached"
    records = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    assert {record["event"] for record in records} >= {
        "planner_ready",
        "planner_hold",
        "planner_recovery",
        "planner_terminal",
    }
