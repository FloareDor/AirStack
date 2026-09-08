"""Fast tests for scenario resolution and mission metric computation."""

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))
BRIDGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "robot"
    / "ros_ws"
    / "src"
    / "local"
    / "planners"
    / "mononav_bridge"
)
sys.path.insert(0, str(BRIDGE_DIR))

from automated_testbench.metrics import (  # noqa: E402
    obstacle_clearance,
    path_length,
    point_to_box_distance,
    summarize,
)
from automated_testbench.generators import GridGenerator  # noqa: E402
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
from automated_testbench.reporting import build_campaign_report  # noqa: E402
from automated_testbench.planner_adapters import (  # noqa: E402
    PlannerAdapterError,
    adapter_for,
)
from mononav_bridge.disturbances import (  # noqa: E402
    DelayedSampleBuffer,
    add_depth_noise,
    add_rgb_noise,
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
        "ISAAC_SIM_SCRIPT_NAME",
        "MONONAV_SCENE_SEED",
        "MONONAV_SCENE_LATERAL_JITTER_M",
        "MONONAV_SCENE_LONGITUDINAL_JITTER_M",
        "MONONAV_SCENE_SCALE_JITTER",
    )} == {
        "ISAAC_SIM_SCRIPT_NAME": "ws2_slalom_launch_script.py",
        "MONONAV_SCENE_SEED": "1",
        "MONONAV_SCENE_LATERAL_JITTER_M": "0.45",
        "MONONAV_SCENE_LONGITUDINAL_JITTER_M": "0.25",
        "MONONAV_SCENE_SCALE_JITTER": "0.1",
    }
    assert environment["MONONAV_SCENE_OBSTACLE_COUNT"] == "3"
    assert first["schema_version"] == 2
    assert first["sensor"] == {
        "fixed_delay_s": 0.0,
        "rgb_noise_stddev": 0.0,
        "depth_noise_stddev_m": 0.0,
    }
    assert first["recording"]["enabled"]
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


def test_stock_scenario_defaults_to_slalom_scene():
    stock = load_scenario(SCENARIOS / "stock.yaml")
    assert stock["scene"] == "slalom"
    assert stock["resolved"]["scene_environment"]["ISAAC_SIM_SCENE"] == ""


def test_office_scenario_resolves_with_no_obstacles():
    office = load_scenario(SCENARIOS / "office_stock.yaml")
    assert office["scene"] == "office"
    assert office["resolved"]["obstacles"] == []
    environment = office["resolved"]["scene_environment"]
    assert environment["ISAAC_SIM_SCENE"] == "Office"
    assert environment["MONONAV_SCENE_OBSTACLE_COUNT"] == "0"


def test_unknown_scene_is_rejected():
    stock = load_scenario(SCENARIOS / "stock.yaml")
    stock.pop("resolved")
    stock["scene"] = "hospital"
    with pytest.raises(ScenarioError, match="scenario.scene"):
        resolve_scenario(stock)


def test_office_scenario_rejects_obstacles_block():
    office = load_scenario(SCENARIOS / "office_stock.yaml")
    office.pop("resolved")
    office["obstacles"] = {"preset": "slalom_3box_v1"}
    with pytest.raises(ScenarioError, match="scenario.obstacles is not supported"):
        resolve_scenario(office)


def test_threat_model_rejects_out_of_model_values_and_builds_clean_twin():
    model = ThreatModel.load(
        TOOLS_DIR / "automated_testbench" / "threat_models" / "generic-ws2-v1.yaml"
    )
    with pytest.raises(ThreatModelError, match="undeclared"):
        model.validate({"shell": "docker down"})
    with pytest.raises(ThreatModelError, match="outside"):
        model.validate({"obstacle_lateral_jitter_m": 999.0})

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

    noisy = model.apply(
        medium,
        {
            "fixed_sensor_delay_s": 0.2,
            "rgb_noise_stddev": 12.0,
            "depth_noise_stddev_m": 0.1,
        },
    )
    assert noisy["sensor"] == {
        "fixed_delay_s": 0.2,
        "rgb_noise_stddev": 12.0,
        "depth_noise_stddev_m": 0.1,
    }
    assert noisy["resolved"]["bridge_launch_arguments"] == {
        "mononav_bridge_disturbance_seed": "1",
        "mononav_bridge_fixed_sensor_delay_s": "0.2",
        "mononav_bridge_rgb_noise_stddev": "12.0",
        "mononav_bridge_depth_noise_stddev_m": "0.1",
    }


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
        [{"obstacle_lateral_jitter_m": 0.2}, {"shell": "docker compose down"}],
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
        {
            "rgb_noise_stddev": 0.1,
            "fixed_delay_s": 0.02,
            "dropout_probability": 0.1,
        }
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
    assert metrics["mission_progress_percent"] == pytest.approx(100.0)
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


def test_sensor_noise_and_delay_are_deterministic():
    image = __import__("numpy").full((4, 5, 3), 128, dtype="uint8")
    first = add_rgb_noise(image, 12.0, seed=7, sequence=3)
    second = add_rgb_noise(image, 12.0, seed=7, sequence=3)
    assert (first == second).all()
    assert not (first == image).all()

    depth = __import__("numpy").ones((4, 5), dtype="float32")
    depth[0, 0] = 0.0
    noisy_depth = add_depth_noise(depth, 0.1, seed=7, sequence=3)
    assert noisy_depth[0, 0] == 0.0
    assert (noisy_depth == add_depth_noise(depth, 0.1, 7, 3)).all()

    buffer = DelayedSampleBuffer(0.25)
    buffer.push("frame-1", 10.0)
    assert buffer.latest(10.24) is None
    assert buffer.latest(10.25) == "frame-1"


def test_campaign_report_compares_clean_and_perturbed_metrics():
    manifest = {
        "campaign_id": "example",
        "trials": [
            {
                "scenario_id": "case-1",
                "pairs": [
                    {
                        "pair_id": "pair-1",
                        "repetition": 0,
                        "verdict": "autonomy_failure",
                        "clean": {
                            "outcome": "goal_reached",
                            "result_dir": "/clean",
                            "metrics": {
                                "mission_progress_percent": 100.0,
                                "minimum_obstacle_clearance_m": 0.5,
                            },
                        },
                        "perturbed": {
                            "outcome": "collision",
                            "result_dir": "/perturbed",
                            "metrics": {
                                "mission_progress_percent": 40.0,
                                "minimum_obstacle_clearance_m": -0.1,
                            },
                        },
                    }
                ],
            }
        ],
    }
    report = build_campaign_report(manifest)
    assert report["summary"]["success_percent"] == pytest.approx(50.0)
    assert report["summary"]["collision_percent"] == pytest.approx(50.0)
    delta = report["comparisons"][0]["metric_delta_perturbed_minus_clean"]
    assert delta["mission_progress_percent"] == pytest.approx(-60.0)
    assert delta["minimum_obstacle_clearance_m"] == pytest.approx(-0.6)


def test_grid_generator_is_bounded_and_changes_one_factor_at_a_time():
    model = ThreatModel.load(
        TOOLS_DIR / "automated_testbench" / "threat_models" / "generic-ws2-v1.yaml"
    )
    generator = GridGenerator(model)
    first = generator.propose()
    validated = model.validate(first.parameters)
    changed = [
        name
        for name, value in validated.items()
        if value != model.parameters[name]["clean"]
    ]
    assert first.generator == "one_factor_grid"
    assert len(changed) == 1


def test_unsupported_planner_method_is_rejected():
    with pytest.raises(PlannerAdapterError, match="unsupported planner method"):
        adapter_for("nonexistent_planner")


def test_mononav_adapter_builds_bridge_and_docker_worker_commands():
    adapter = adapter_for("mononav")
    assert adapter.status_topic == "/robot_1/mononav/status"

    bridge_command = adapter.bridge_command({"mononav_bridge_disturbance_seed": "1"})
    assert bridge_command[:4] == [
        "ros2",
        "launch",
        "mononav_bridge",
        "mononav_bridge.launch.xml",
    ]
    assert "mononav_bridge_disturbance_seed:=1" in bridge_command

    config = {
        "repo": "/home/ubuntu/airlab/MonoNav",
        "image": "mononav-demo:1.0",
        "container_name": "mononav-airstack",
        "torch_cache_volume": "mononav-torch-cache",
        "args": ["--rate", "2.0"],
        "bridge": {"server_url": "http://airstack-robot-desktop-1:8765"},
    }
    command, environment = adapter.worker_command(
        config,
        airstack={"docker_network": "airstack_airstack_network"},
        depth_source="zoe",
        goal_distance_m=8.0,
    )
    assert command[:4] == ["docker", "run", "--rm", "--name"]
    assert "mononav-airstack" in command
    assert "-v" in command and "mononav-torch-cache:/root/.cache/torch" in command
    assert "--depth-source" in command and "zoe" in command
    assert "--goal-distance" in command and "8.0" in command
    assert environment is None
    assert adapter.required_paths(config) == [
        Path("/home/ubuntu/airlab/MonoNav") / "mononav_airstack.py"
    ]


def test_collision_avoidance_adapter_translates_bridge_args_and_sets_worker_environment():
    adapter = adapter_for("collision_avoidance")
    assert adapter.status_topic == "/robot_1/collision_avoidance/status"

    bridge_command = adapter.bridge_command({"mononav_bridge_disturbance_seed": "1"})
    assert bridge_command[:4] == [
        "ros2",
        "launch",
        "mononav_bridge",
        "vision_planner_bridge.launch.xml",
    ]
    assert "vision_planner_name:=collision_avoidance" in bridge_command
    assert "vision_planner_namespace:=collision_avoidance" in bridge_command
    assert "vision_planner_disturbance_seed:=1" in bridge_command
    assert not any(item.startswith("mononav_bridge_") for item in bridge_command)

    config = {
        "repo": "/home/ubuntu/airlab/Collision-avoidance",
        "container_name": "collision-avoidance-airstack",
        "worker_script": "docker/run_airstack_live.sh",
        "args": ["--rate", "3.0"],
        "bridge": {"server_url": "http://airstack-robot-desktop-1:8765"},
    }
    command, environment = adapter.worker_command(
        config,
        airstack={"docker_network": "airstack_airstack_network"},
        depth_source="fcrn",
        goal_distance_m=8.0,
    )
    assert command == [
        str(Path("/home/ubuntu/airlab/Collision-avoidance") / "docker/run_airstack_live.sh"),
        "--depth-source",
        "fcrn",
        "--rate",
        "3.0",
    ]
    assert environment is not None
    assert environment["COLLISION_AVOIDANCE_EXECUTE"] == "true"
    assert environment["COLLISION_AVOIDANCE_CONTAINER_NAME"] == "collision-avoidance-airstack"
    assert environment["DISPLAY"] == ":99"
    assert adapter.required_paths(config) == [
        Path("/home/ubuntu/airlab/Collision-avoidance") / "docker/run_airstack_live.sh"
    ]

    _, environment_with_display = adapter.worker_command(
        config,
        airstack={"docker_network": "airstack_airstack_network", "display": ":42"},
        depth_source="fcrn",
        goal_distance_m=8.0,
    )
    assert environment_with_display["DISPLAY"] == ":42"


def test_worker_command_rejects_non_string_args():
    adapter = adapter_for("mononav")
    with pytest.raises(PlannerAdapterError, match="args must be a list of strings"):
        adapter.worker_command(
            {
                "repo": "/repo",
                "image": "img",
                "container_name": "name",
                "args": [1, 2],
                "bridge": {"server_url": "http://x"},
            },
            airstack={},
            depth_source="zoe",
            goal_distance_m=8.0,
        )


def test_collision_avoidance_scenario_resolves_with_its_own_status_topic_and_depth_sources():
    scenario = load_scenario(SCENARIOS / "collision_avoidance_stock.yaml")
    assert scenario["planner"]["method"] == "collision_avoidance"
    assert scenario["planner"]["depth_source"] == "fcrn"
    assert scenario["recording"]["topics"][-2] == "/robot_1/collision_avoidance/status"
    assert scenario["resolved"]["bridge_launch_arguments"] == {
        "mononav_bridge_disturbance_seed": "0",
        "mononav_bridge_fixed_sensor_delay_s": "0.0",
        "mononav_bridge_rgb_noise_stddev": "0.0",
        "mononav_bridge_depth_noise_stddev_m": "0.0",
    }


def test_collision_avoidance_rejects_mononav_only_depth_source():
    raw = yaml_round_trip(SCENARIOS / "collision_avoidance_stock.yaml")
    raw["planner"]["depth_source"] = "zoe"
    with pytest.raises(ScenarioError, match="depth_source for collision_avoidance"):
        resolve_scenario(raw)


def test_collision_avoidance_worker_script_rejects_path_escape():
    raw = yaml_round_trip(SCENARIOS / "collision_avoidance_stock.yaml")
    raw["collision_avoidance"]["worker_script"] = "../../etc/passwd"
    with pytest.raises(ScenarioError, match="worker_script must be a relative path"):
        resolve_scenario(raw)


def yaml_round_trip(path: Path) -> dict:
    """Load and fully merge a scenario file's `extends` chain without resolving it."""
    from automated_testbench.scenario import _load_raw_scenario

    return _load_raw_scenario(Path(path).resolve(), [])
