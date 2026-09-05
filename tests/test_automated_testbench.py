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
from automated_testbench.run_trial import (  # noqa: E402
    EventRecorder,
    TrialState,
    build_termination,
)
from automated_testbench.scenario import (  # noqa: E402
    STOCK_OBSTACLES,
    ScenarioError,
    load_scenario,
    resolve_scenario,
)
from automated_testbench.threat_model import ThreatModel, ThreatModelError  # noqa: E402
from automated_testbench.adversary import BoundedAdversary  # noqa: E402
from automated_testbench.paired import prepare_pair, reproducibility_label  # noqa: E402
from automated_testbench.perturbation_adapters import (  # noqa: E402
    AdapterError,
    Ros2SensorProxyAdapter,
    WS1VisualPatchAdapter,
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
    environment = first["resolved"]["scene_environment"]
    assert {key: environment[key] for key in (
        "MONONAV_DEMO_OBSTACLES",
        "MONONAV_SCENE_SEED",
        "MONONAV_SCENE_LATERAL_JITTER_M",
        "MONONAV_SCENE_LONGITUDINAL_JITTER_M",
        "MONONAV_SCENE_SCALE_JITTER",
    )} == {
        "MONONAV_DEMO_OBSTACLES": "true",
        "MONONAV_SCENE_SEED": "1",
        "MONONAV_SCENE_LATERAL_JITTER_M": "0.45",
        "MONONAV_SCENE_LONGITUDINAL_JITTER_M": "0.25",
        "MONONAV_SCENE_SCALE_JITTER": "0.1",
    }
    assert environment["MONONAV_SCENE_OBSTACLE_COUNT"] == "3"
    assert first["schema_version"] == 2
    assert first["resolved"]["configuration_hash"] == second["resolved"]["configuration_hash"]


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


def test_nonfinite_and_infeasible_scenes_are_rejected():
    stock = load_scenario(SCENARIOS / "stock.yaml")
    stock.pop("resolved")
    stock["flight"]["goal"]["radius_m"] = float("nan")
    stock["mission"]["goal"]["radius_m"] = float("nan")
    with pytest.raises(ScenarioError, match="finite"):
        resolve_scenario(stock)

    blocked = load_scenario(SCENARIOS / "stock.yaml")
    blocked.pop("resolved")
    blocked["flight"]["start_pose"] = [3.0, 0.0, 1.0, 0.0]
    blocked["mission"]["start_pose"] = [3.0, 0.0, 1.0, 0.0]
    with pytest.raises(ScenarioError, match="spawn region is blocked"):
        resolve_scenario(blocked)


def test_threat_model_rejects_out_of_model_values_and_builds_clean_twin():
    model = ThreatModel.load(
        TOOLS_DIR / "automated_testbench" / "threat_models" / "generic-ws2-v1.yaml"
    )
    with pytest.raises(ThreatModelError, match="undeclared"):
        model.validate({"shell": "docker down"})
    with pytest.raises(ThreatModelError, match="outside"):
        model.validate({"obstacle_count": 4})

    medium = load_scenario(SCENARIOS / "medium_seed1.yaml")
    proposal = model.extract(medium)
    attack = model.apply(medium, proposal, repetition=2)
    clean = model.clean_twin(attack, repetition=2)
    assert attack["repetition"] == clean["repetition"] == 2
    assert clean["obstacles"]["variation"] == {
        "lateral_m": 0.0,
        "longitudinal_m": 0.0,
        "scale_fraction": 0.0,
    }
    assert attack["resolved"]["configuration_hash"] != clean["resolved"]["configuration_hash"]


def test_bounded_llm_facade_audits_and_rejects_undeclared_tools(tmp_path):
    model = ThreatModel.load(
        TOOLS_DIR / "automated_testbench" / "threat_models" / "generic-ws2-v1.yaml"
    )
    adversary = BoundedAdversary(
        load_scenario(SCENARIOS / "medium_seed1.yaml"),
        model,
        tmp_path,
        tmp_path / "llm_audit.json",
    )
    decisions = adversary.propose_batch(
        [{"obstacle_count": 2}, {"shell": "docker compose down"}],
        rationale="test audit boundary",
        model_configuration={"model": "test"},
    )
    assert decisions[0]["validator"]["accepted"]
    assert not decisions[1]["validator"]["accepted"]
    audit = json.loads((tmp_path / "llm_audit.json").read_text())
    assert audit["model_configurations"] == [{"model": "test"}]


def test_clean_pair_preserves_seed_mission_and_replay_configuration_hash():
    model = ThreatModel.load(
        TOOLS_DIR / "automated_testbench" / "threat_models" / "generic-ws2-v1.yaml"
    )
    scenario = load_scenario(SCENARIOS / "medium_seed1.yaml")
    pair_id, clean, perturbed = prepare_pair(scenario, model, repetition=0)
    _, _, replay = prepare_pair(scenario, model, repetition=1)
    assert pair_id == clean["pair"]["pair_id"] == perturbed["pair"]["pair_id"]
    assert clean["seed"] == perturbed["seed"] == 1
    assert clean["mission"] == perturbed["mission"]
    assert (
        perturbed["resolved"]["configuration_hash"]
        == replay["resolved"]["configuration_hash"]
    )
    pairs = [
        {"verdict": "autonomy_failure", "perturbed": {"outcome": "collision"}}
        for _ in range(3)
    ]
    assert reproducibility_label(pairs) == "reproducible"


def test_future_sensor_and_ws1_adapters_remain_bounded():
    proxy = Ros2SensorProxyAdapter().resolve(
        {"noise_stddev": 0.1, "fixed_delay_s": 0.02, "dropout_probability": 0.1}
    )
    assert "WS2_SENSOR_PROXY_CONFIG_JSON" in proxy
    with pytest.raises(AdapterError, match="canonical CyLab"):
        WS1VisualPatchAdapter().resolve({"scene": "patch.usd", "asset": "a.png"})


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
        "ready",
        "hold",
        "recovery",
        "planner_stopped",
    }


def test_physx_contact_overrides_geometry_fallback(tmp_path):
    events = EventRecorder(tmp_path / "events.jsonl")
    obstacle = {"position_m": [3.0, 0.0, 1.0], "size_m": [0.6, 0.8, 2.0]}
    state = TrialState([8.0, 0.0, 1.0], 1.0, [obstacle], 0.25, events)
    state.activate()
    state.telemetry_line('{"event":"physx_contact","contact":false}')
    state.telemetry_line(
        '{"event":"odometry","sim_time_s":1,"wall_time_s":1,"position_m":[3,0,1]}'
    )
    assert not state.collision
    state.telemetry_line('{"event":"physx_contact","contact":true}')
    assert state.collision_source == "physx_contact"
    events.close()
    assert build_termination("collision", state, None)["reason"] == "physx_contact"


@pytest.mark.parametrize(
    ("raw_reason", "reason_code", "recovery_count"),
    [
        ("altitude deviation", "altitude_deviation", None),
        (
            "no central safe primitive after 12 yaw scans",
            "recovery_exhausted",
            12,
        ),
    ],
)
def test_planner_stop_termination_has_stable_reason(
    tmp_path, raw_reason, reason_code, recovery_count
):
    events = EventRecorder(tmp_path / "events.jsonl")
    state = TrialState([8.0, 0.0, 1.0], 1.0, [], 0.25, events)
    state.planner_terminal_reason = raw_reason
    state.planner_terminal_distance_m = 1.54
    state.planner_recovery_count = recovery_count or 0
    events.close()

    termination = build_termination("planner_stopped", state, None)

    assert termination["source"] == "planner"
    assert termination["reason"] == reason_code
    assert termination["detail"] == raw_reason
    assert termination["planner_distance_to_goal_m"] == pytest.approx(1.54)
    if recovery_count is None:
        assert "recovery_count" not in termination
    else:
        assert termination["recovery_count"] == recovery_count


def test_infrastructure_termination_preserves_stage_and_message():
    termination = build_termination(
        "infrastructure_error",
        None,
        {"stage": "bridge_health", "message": "bridge unavailable"},
    )
    assert termination == {
        "source": "infrastructure",
        "reason": "bridge_health",
        "detail": "bridge unavailable",
    }
