#!/usr/bin/env python3
"""Run one isolated AirStack WS2 planner scenario and record its verdict."""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from automated_testbench.metrics import obstacle_clearance, summarize
    from automated_testbench.processes import CommandError, ManagedProcess, run_logged
    from automated_testbench.planner_adapters import (
        PlannerAdapterError,
        adapter_for,
    )
    from automated_testbench.scenario import dump_scenario, load_scenario
    from automated_testbench.locking import try_lock, unlock
else:
    from .metrics import obstacle_clearance, summarize
    from .processes import CommandError, ManagedProcess, run_logged
    from .planner_adapters import PlannerAdapterError, adapter_for
    from .scenario import dump_scenario, load_scenario
    from .locking import try_lock, unlock


TERMINAL_RE = re.compile(
    r"Mission stopping \((?P<reason>.+)\) at goal distance (?P<distance>[0-9.]+) m"
)
GOAL_RE = re.compile(r"World-frame goal initialized at (?P<goal>\[[^]]+\])")
FRAME_RE = re.compile(
    r"frame=(?P<frame>\d+).*primitive=(?P<primitive>-?\d+).*blocked=(?P<blocked>True|False)"
)


class InfrastructureError(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


class EventRecorder:
    def __init__(self, path: Path) -> None:
        self._stream = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._started = time.monotonic()

    def emit(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp_utc": utc_now(),
            "elapsed_wall_s": round(time.monotonic() - self._started, 6),
            "event": event,
        }
        record.update(fields)
        with self._lock:
            self._stream.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._stream.flush()

    def close(self) -> None:
        with self._lock:
            self._stream.close()


class TrialState:
    def __init__(
        self,
        goal_position_m: list[float],
        goal_radius_m: float,
        obstacles: list[dict[str, Any]],
        robot_radius_m: float,
        events: EventRecorder,
        adapter_name: str = "mononav",
        collision_padding_m: float = 0.1,
        geometry_fallback: bool = True,
    ) -> None:
        self.goal_position_m = goal_position_m
        self.goal_radius_m = goal_radius_m
        self.obstacles = obstacles
        self.robot_radius_m = robot_radius_m
        self.collision_padding_m = collision_padding_m
        self.geometry_fallback = geometry_fallback
        self.events = events
        self.adapter_name = adapter_name
        self.lock = threading.Lock()
        self.active = False
        self.samples: list[dict[str, Any]] = []
        self.goal_reached_index: int | None = None
        self.collision = False
        self.collision_source: str | None = None
        self.physx_contact_available = False
        self.last_telemetry_wall: float | None = None
        self.activation_sim_time_s: float | None = None
        self.last_sim_time_s: float | None = None
        self.planner_ready = threading.Event()
        self.planner_terminal_reason: str | None = None
        self.planner_terminal_distance_m: float | None = None
        self.planner_hold_count = 0
        self.planner_recovery_count = 0
        self.worker_goal_position_m: list[float] | None = None
        self.planner_command_count = 0
        self._last_command_identity: tuple[Any, ...] | None = None

    def activate(self) -> None:
        with self.lock:
            self.samples.clear()
            self.goal_reached_index = None
            self.collision = False
            self.collision_source = None
            self.activation_sim_time_s = None
            self.last_sim_time_s = None
            self.active = True

    def telemetry_line(self, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return
        event = payload.get("event")
        if event == "bridge_status":
            status = payload.get("status")
            self.events.emit("bridge_status", status=status)
            if isinstance(status, dict) and isinstance(status.get("last_command"), dict):
                command = status["last_command"]
                identity = (
                    command.get("command_index"),
                    command.get("stamp"),
                    command.get("waypoint_count"),
                )
                if identity != self._last_command_identity:
                    self._last_command_identity = identity
                    self.planner_command_count += 1
                    self.events.emit(
                        "command_issued",
                        adapter=self.adapter_name,
                        command_index=command.get("command_index"),
                        waypoint_count=command.get("waypoint_count"),
                        source="bridge_status",
                    )
                    self.planner_ready.set()
            return
        if event == "physx_contact":
            with self.lock:
                self.physx_contact_available = True
                if self.active and bool(payload.get("contact", False)) and not self.collision:
                    self.collision = True
                    self.collision_source = "physx_contact"
                    self.events.emit("physx_contact", contact=True)
            return
        if event != "odometry":
            return
        with self.lock:
            self.last_telemetry_wall = time.monotonic()
            if not self.active:
                return
            sample = {
                "sim_time_s": float(payload["sim_time_s"]),
                "wall_time_s": float(payload["wall_time_s"]),
                "position_m": [float(value) for value in payload["position_m"]],
            }
            self.samples.append(sample)
            self.last_sim_time_s = sample["sim_time_s"]
            if self.activation_sim_time_s is None:
                self.activation_sim_time_s = sample["sim_time_s"]
            index = len(self.samples) - 1
            distance_to_goal = math.dist(sample["position_m"], self.goal_position_m)
            clearance = obstacle_clearance(
                sample["position_m"], self.obstacles, self.robot_radius_m
            )
            if (
                self.goal_reached_index is None
                and distance_to_goal <= self.goal_radius_m
            ):
                self.goal_reached_index = index
                self.events.emit(
                    "goal_radius_entered",
                    sim_time_s=sample["sim_time_s"],
                    distance_m=distance_to_goal,
                )
                self.events.emit(
                    "goal_reached",
                    source="odometry",
                    sim_time_s=sample["sim_time_s"],
                    distance_m=distance_to_goal,
                )
            if (
                self.geometry_fallback
                and not self.physx_contact_available
                and clearance is not None
                and clearance <= self.collision_padding_m
                and not self.collision
            ):
                self.collision = True
                self.collision_source = "geometry_fallback"
                self.events.emit(
                    "geometry_collision",
                    sim_time_s=sample["sim_time_s"],
                    clearance_m=clearance,
                    padding_m=self.collision_padding_m,
                )
            self.events.emit(
                "odometry",
                sim_time_s=sample["sim_time_s"],
                position_m=sample["position_m"],
                distance_to_goal_m=distance_to_goal,
                obstacle_clearance_m=clearance,
            )

    def planner_line(self, line: str) -> None:
        if not line:
            return
        goal_match = GOAL_RE.search(line)
        if goal_match:
            try:
                self.worker_goal_position_m = [
                    float(value) for value in ast.literal_eval(goal_match.group("goal"))
                ]
            except (ValueError, SyntaxError, TypeError):
                self.worker_goal_position_m = None
            self.events.emit(
                "planner_ready", worker_goal_position_m=self.worker_goal_position_m
            )
            self.events.emit("ready", adapter=self.adapter_name)
            self.planner_ready.set()
        if line.startswith("UNSAFE HOLD:"):
            self.planner_hold_count += 1
            self.events.emit("planner_hold", detail=line)
            self.events.emit("hold", adapter=self.adapter_name, detail=line)
        if line.startswith("RECOVERY "):
            self.planner_recovery_count += 1
            self.events.emit("planner_recovery", detail=line)
            self.events.emit("recovery", adapter=self.adapter_name, detail=line)
        frame_match = FRAME_RE.search(line)
        if frame_match:
            self.events.emit(
                "planner_frame",
                frame=int(frame_match.group("frame")),
                primitive=int(frame_match.group("primitive")),
                blocked=frame_match.group("blocked") == "True",
            )
            if int(frame_match.group("primitive")) >= 0:
                self.events.emit(
                    "command_issued",
                    adapter=self.adapter_name,
                    primitive=int(frame_match.group("primitive")),
                    frame=int(frame_match.group("frame")),
                )
        terminal_match = TERMINAL_RE.search(line)
        if terminal_match:
            self.planner_terminal_reason = terminal_match.group("reason")
            self.planner_terminal_distance_m = float(terminal_match.group("distance"))
            self.events.emit(
                "planner_terminal",
                reason=self.planner_terminal_reason,
                distance_to_goal_m=self.planner_terminal_distance_m,
            )
            self.events.emit(
                "planner_stopped",
                adapter=self.adapter_name,
                reason=self.planner_terminal_reason,
            )


def planner_reason_code(reason: str) -> str:
    """Map MonoNav terminal text to a small, stable result vocabulary."""
    if reason == "altitude deviation":
        return "altitude_deviation"
    if reason.startswith("no central safe primitive"):
        return "recovery_exhausted"
    if reason == "goal threshold reached":
        return "goal_threshold_reached"
    return "planner_terminal"


def flight_deadline_status(
    sim_elapsed_s: float | None,
    timeout_s: float,
    wall_elapsed_s: float,
    wall_backstop_s: float,
) -> str | None:
    """Decide whether the flight loop should end on the mission timeout.

    Uses simulation time (drift-free against real-time factor) for the normal
    `timeout` verdict, with a wall-clock backstop that catches a stalled or
    pathologically slow simulation the sim clock itself can't detect. Returns
    None to keep running, "timeout" for a normal autonomy timeout, or
    "wall_backstop" for an infrastructure-side stall.
    """
    if sim_elapsed_s is not None and sim_elapsed_s >= timeout_s:
        return "timeout"
    if wall_elapsed_s >= wall_backstop_s:
        return "wall_backstop"
    return None


def build_termination(
    outcome: str,
    state: TrialState | None,
    failure: dict[str, str] | None,
) -> dict[str, Any]:
    """Build the concise machine-readable explanation saved with every verdict."""
    if outcome == "infrastructure_error":
        stage = failure.get("stage", "unknown") if failure else "unknown"
        detail = failure.get("message", "infrastructure failure") if failure else None
        return {
            "source": "infrastructure",
            "reason": stage,
            "detail": detail,
        }
    if outcome == "collision":
        collision_source = state.collision_source if state is not None else None
        return {
            "source": collision_source or "geometry_fallback",
            "reason": (
                "physx_contact"
                if collision_source == "physx_contact"
                else "geometry_collision_fallback"
            ),
            "detail": (
                "PhysX reported obstacle contact"
                if collision_source == "physx_contact"
                else "estimated obstacle clearance crossed the configured padding"
            ),
        }
    if outcome == "timeout":
        return {
            "source": "runner",
            "reason": "trial_timeout",
            "detail": "configured flight timeout elapsed",
        }

    planner_reason = state.planner_terminal_reason if state is not None else None
    planner_distance = state.planner_terminal_distance_m if state is not None else None
    if outcome == "goal_reached":
        if planner_reason is not None:
            return {
                "source": "planner",
                "reason": planner_reason_code(planner_reason),
                "detail": planner_reason,
                "planner_distance_to_goal_m": planner_distance,
            }
        return {
            "source": "odometry_monitor",
            "reason": "goal_radius_reached",
            "detail": "odometry entered the configured goal radius",
        }
    if outcome == "planner_stopped":
        if planner_reason is not None:
            termination = {
                "source": "planner",
                "reason": planner_reason_code(planner_reason),
                "detail": planner_reason,
                "planner_distance_to_goal_m": planner_distance,
            }
            if termination["reason"] == "recovery_exhausted" and state is not None:
                termination["recovery_count"] = state.planner_recovery_count
            return termination
        return {
            "source": "planner",
            "reason": "planner_exited_cleanly",
            "detail": "planner process exited without a terminal message",
        }
    raise ValueError(f"unsupported trial outcome: {outcome}")


class AirStackRuntime:
    def __init__(
        self, scenario: dict[str, Any], result_dir: Path, events: EventRecorder
    ):
        self.scenario = scenario
        self.result_dir = result_dir
        self.events = events
        self.airstack = scenario["airstack"]
        try:
            self.adapter = adapter_for(str(scenario["planner"]["method"]))
        except PlannerAdapterError as exc:
            raise InfrastructureError("planner_configuration", str(exc)) from exc
        self.planner = scenario[self.adapter.config_key]
        self.repo = Path(self.airstack["repo"])
        self.robot_container = self.airstack.get(
            "robot_container", "airstack-robot-desktop-1"
        )
        self.sim_container = self.airstack.get("sim_container", "isaac-sim")
        self.domain_id = int(self.airstack.get("ros_domain_id", 1))
        self.ros_setup = self.airstack.get(
            "robot_setup", "/root/AirStack/robot/ros_ws/install/setup.bash"
        )
        self.probe_container_path = "/tmp/airstack_automated_testbench_ros_probe.py"
        self.bridge_process: ManagedProcess | None = None
        self.worker_process: ManagedProcess | None = None
        self.stack_started = False
        self.provenance = self._capture_provenance()

    @staticmethod
    def _git_commit(path: Path) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _capture_provenance(self) -> dict[str, Any]:
        image = self.planner.get("image")
        image_id = None
        try:
            if not image:
                raise ValueError("planner image is not managed by this adapter")
            inspected = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
            if inspected.returncode == 0:
                image_id = inspected.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return {
            "airstack_commit": self._git_commit(self.repo),
            "planner": {
                "method": self.adapter.method,
                "commit": self._git_commit(Path(self.planner["repo"])),
                "image": {"reference": image, "id": image_id},
            },
        }

    def _log(self, name: str) -> Path:
        return self.result_dir / name

    def _run(
        self,
        command: list[str],
        log_name: str,
        *,
        cwd: Path | str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: float = 60.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.events.emit("command_started", name=log_name, command=command)
        try:
            result = run_logged(
                command,
                self._log(log_name),
                cwd=cwd,
                env=env,
                timeout_s=timeout_s,
                check=check,
            )
        except CommandError as exc:
            self.events.emit("command_failed", name=log_name, error=str(exc))
            raise
        self.events.emit(
            "command_finished", name=log_name, returncode=result.returncode
        )
        return result

    def _ros_shell(self, command: list[str]) -> str:
        prefix = (
            f"source /opt/ros/jazzy/setup.bash && source {shlex.quote(self.ros_setup)} "
            f"&& export ROS_DOMAIN_ID={self.domain_id} && exec "
        )
        return prefix + shlex.join(command)

    def ros_command(
        self,
        command: list[str],
        log_name: str,
        *,
        timeout_s: float = 30.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            [
                "docker",
                "exec",
                self.robot_container,
                "bash",
                "-lc",
                self._ros_shell(command),
            ],
            log_name,
            timeout_s=timeout_s,
            check=check,
        )

    def preflight(self) -> None:
        checks = [
            ("docker_cli", ["docker", "version", "--format", "{{.Server.Version}}"]),
            ("docker_daemon", ["docker", "info", "--format", "{{.ServerVersion}}"]),
        ]
        image = self.planner.get("image")
        if image:
            checks.append(
                (
                    f"{self.adapter.method}_image",
                    ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                )
            )
        cache_volume = self.planner.get("torch_cache_volume")
        if cache_volume:
            checks.append(
                (
                    f"{self.adapter.method}_cache",
                    [
                        "docker",
                        "volume",
                        "inspect",
                        cache_volume,
                        "--format",
                        "{{.Name}}",
                    ],
                )
            )
        for name, command in checks:
            try:
                self._run(command, "preflight.log", timeout_s=15)
            except (CommandError, OSError) as exc:
                raise InfrastructureError("preflight", f"{name} failed: {exc}") from exc
            self.events.emit("health_check", check=name, ok=True)
        required = [
            self.repo / self.airstack.get("cli", "airstack.sh"),
            *self.adapter.required_paths(self.planner),
        ]
        for path in required:
            if not path.exists():
                raise InfrastructureError(
                    "preflight", f"required path is missing: {path}"
                )
        self.events.emit("health_check", check="required_paths", ok=True)

    def reset_stack(self) -> None:
        worker_name = self.planner["container_name"]
        self._run(
            ["docker", "rm", "-f", worker_name],
            "airstack.log",
            timeout_s=20,
            check=False,
        )
        cli = str(self.repo / self.airstack.get("cli", "airstack.sh"))
        self._run(
            [cli, "down"], "airstack.log", cwd=self.repo, timeout_s=150, check=False
        )
        env = os.environ.copy()
        env.update(self.scenario["resolved"]["scene_environment"])
        start = self.scenario["flight"]["start_pose"]
        env.update(
            {
                "AUTOLAUNCH": "true",
                "COMPOSE_PROFILES": self.airstack.get(
                    "compose_profiles", "desktop,isaac-sim"
                ),
                "DISPLAY": str(self.airstack.get("display", ":99")),
                "PLAY_SIM_ON_START": "true",
                "ISAAC_SIM_HEADLESS": str(self.airstack.get("headless", False)).lower(),
                "DRONE_INIT_X": str(start[0]),
                "DRONE_INIT_Y": str(start[1]),
                "DRONE_INIT_Z": str(start[2]),
                "ENABLE_LIDAR": "false",
                "NUM_ROBOTS": "1",
            }
        )
        self.events.emit(
            "scene_applied", environment=self.scenario["resolved"]["scene_environment"]
        )
        try:
            self._run(
                [cli, "up", "isaac-sim", "robot-desktop"],
                "airstack.log",
                cwd=self.repo,
                env=env,
                timeout_s=180,
            )
        except (CommandError, OSError) as exc:
            raise InfrastructureError("stack_start", str(exc)) from exc
        self.stack_started = True

    def wait_for_stack(self, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        containers_ready = False
        isaac_ready = False
        while time.monotonic() < deadline:
            states = {}
            for container in (self.sim_container, self.robot_container):
                result = self._run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", container],
                    "health.log",
                    timeout_s=10,
                    check=False,
                )
                states[container] = (
                    result.returncode == 0 and result.stdout.strip() == "true"
                )
            containers_ready = all(states.values())
            if containers_ready:
                process_result = self._run(
                    ["docker", "top", self.sim_container, "-eo", "pid,args"],
                    "health.log",
                    timeout_s=10,
                    check=False,
                )
                process_text = process_result.stdout
                isaac_ready = (
                    "example_one_px4_pegasus_launch_script.py" in process_text
                    and "PX4-Autopilot" in process_text
                )
            if containers_ready and isaac_ready:
                break
            time.sleep(2)
        if not containers_ready:
            raise InfrastructureError(
                "container_health", "AirStack containers did not become ready"
            )
        if not isaac_ready:
            raise InfrastructureError(
                "isaac_px4_health", "Isaac Sim or PX4 process is missing"
            )
        self.events.emit("health_check", check="containers", ok=True)
        self.events.emit("health_check", check="isaac_sim", ok=True)
        self.events.emit("health_check", check="px4_process", ok=True)

        probe_source = self.repo / "tools" / "automated_testbench" / "ros_probe.py"
        try:
            self._run(
                [
                    "docker",
                    "cp",
                    str(probe_source),
                    f"{self.robot_container}:{self.probe_container_path}",
                ],
                "health.log",
                timeout_s=15,
            )
        except CommandError as exc:
            raise InfrastructureError("ros_probe_install", str(exc)) from exc
        self.events.emit("health_check", check="ros_probe_installed", ok=True)

        px4_deadline = time.monotonic() + timeout_s
        px4_ready = False
        while time.monotonic() < px4_deadline:
            connected = self.ros_command(
                [
                    "timeout",
                    "5",
                    "ros2",
                    "topic",
                    "echo",
                    "--once",
                    "--csv",
                    "--field",
                    "connected",
                    "/robot_1/interface/mavros/state",
                ],
                "health.log",
                timeout_s=12,
                check=False,
            )
            if not any(
                line.strip() == "True" for line in connected.stdout.splitlines()
            ):
                time.sleep(2)
                continue
            local_odom = self.ros_command(
                [
                    "timeout",
                    "5",
                    "ros2",
                    "topic",
                    "echo",
                    "--once",
                    "/robot_1/interface/mavros/local_position/odom",
                ],
                "health.log",
                timeout_s=12,
                check=False,
            )
            if local_odom.returncode == 0 and "pose:" in local_odom.stdout:
                px4_ready = True
                break
            time.sleep(2)
        if not px4_ready:
            raise InfrastructureError(
                "px4_health", "PX4 did not reach connected local-odometry readiness"
            )
        self.events.emit("health_check", check="px4_mavros", ok=True)

        health = self.run_probe("wait", timeout_s=30, minimum_samples=5)
        if not health.get("ok"):
            raise InfrastructureError(
                "odometry_health", "fresh converted odometry was not received"
            )
        self.events.emit(
            "health_check", check="ros2_odometry", ok=True, samples=health["samples"]
        )

        action = self.ros_command(
            ["ros2", "action", "info", "/robot_1/tasks/takeoff"],
            "health.log",
            timeout_s=20,
            check=False,
        )
        match = re.search(r"Action servers:\s*(\d+)", action.stdout)
        if action.returncode != 0 or match is None or int(match.group(1)) != 1:
            raise InfrastructureError(
                "takeoff_health", "expected exactly one /robot_1/tasks/takeoff server"
            )
        self.events.emit("health_check", check="takeoff_server", ok=True, count=1)
        return health

    def run_probe(
        self, mode: str, *, timeout_s: float, minimum_samples: int = 5, **extra: Any
    ) -> dict[str, Any]:
        command = [
            "python3",
            "-u",
            self.probe_container_path,
            mode,
            "--odometry-topic",
            "/robot_1/odometry_conversion/odometry",
            "--status-topic",
            self.adapter.status_topic,
            "--contact-topic",
            self.scenario["oracle"]["collision"]["contact_topic"],
            "--timeout",
            str(timeout_s),
            "--minimum-samples",
            str(minimum_samples),
        ]
        for key, value in extra.items():
            command.extend(["--" + key.replace("_", "-"), str(value)])
        result = self.ros_command(
            command,
            "telemetry.log" if mode != "takeoff" else "takeoff.log",
            timeout_s=timeout_s + 15,
            check=False,
        )
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") in {"health", "takeoff"}:
                return payload
        return {"ok": False, "message": "probe produced no machine-readable result"}

    def start_bridge(self) -> None:
        bridge = self.planner["bridge"]
        if not bridge.get("manage", True):
            self.events.emit("bridge_launch_skipped")
            return
        command = self.adapter.bridge_command(
            self.scenario["resolved"]["bridge_launch_arguments"]
        )
        docker_command = [
            "docker",
            "exec",
            self.robot_container,
            "bash",
            "-lc",
            self._ros_shell(command),
        ]
        self.bridge_process = ManagedProcess(docker_command, self._log("bridge.log"))
        self.events.emit("bridge_started", adapter=self.adapter.method)

    def start_recording(self) -> ManagedProcess | None:
        recording = self.scenario["recording"]
        if not recording["enabled"]:
            self.events.emit("recording_skipped")
            return None
        bag_name = self.result_dir.name
        command = [
            "ros2",
            "bag",
            "record",
            "--storage",
            recording["storage_id"],
            "--output",
            f"/bags/{bag_name}",
            *recording["topics"],
        ]
        process = ManagedProcess(
            [
                "docker",
                "exec",
                self.robot_container,
                "bash",
                "-lc",
                self._ros_shell(command),
            ],
            self._log("recording.log"),
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise InfrastructureError(
                    "recording_start",
                    f"ros2 bag record exited early (exit {process.poll()})",
                )
            time.sleep(0.1)
        self.events.emit(
            "recording_started",
            storage_id=recording["storage_id"],
            topic_count=len(recording["topics"]),
        )
        return process

    def _fix_recording_ownership(self) -> None:
        """`ros2 bag record` runs as root inside the container, so both the bind
        mount point and the bag files it creates land root-owned on the host.
        Reclaim both, while the container is still up, so the unprivileged host
        runner can later remove the trial directory from its parent during move."""
        if not self.scenario["recording"]["enabled"]:
            return
        owner = f"{os.getuid()}:{os.getgid()}"
        self._run(
            ["docker", "exec", self.robot_container, "chown", owner, "/bags"],
            "cleanup.log",
            timeout_s=10,
            check=False,
        )
        self._run(
            [
                "docker",
                "exec",
                self.robot_container,
                "chown",
                "-R",
                owner,
                f"/bags/{self.result_dir.name}",
            ],
            "cleanup.log",
            timeout_s=15,
            check=False,
        )

    def collect_recording(self) -> str | None:
        if not self.scenario["recording"]["enabled"]:
            return None
        source = self.repo / "robot" / "bags" / self.result_dir.name
        destination = self.result_dir / "recording"
        if not source.is_dir():
            self.events.emit(
                "artifact_collection_error",
                artifact="recording",
                message=f"recording directory is missing: {source}",
            )
            return None
        shutil.move(str(source), str(destination))
        self.events.emit("recording_collected", path="recording")
        return "recording"

    def bridge_health(self) -> dict[str, Any] | None:
        url = self.planner["bridge"]["health_url"].rstrip("/") + "/health"
        code = (
            "import json,sys,urllib.request; "
            "print(urllib.request.urlopen(sys.argv[1],timeout=2).read().decode())"
        )
        result = self._run(
            ["docker", "exec", self.robot_container, "python3", "-c", code, url],
            "health.log",
            timeout_s=8,
            check=False,
        )
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            return None

    def wait_for_bridge(self, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        previous_sequence = None
        while time.monotonic() < deadline:
            health = self.bridge_health()
            if health and health.get("ready") and health.get("execute_commands"):
                sequence = health.get("sequence")
                if previous_sequence is not None and sequence != previous_sequence:
                    self.events.emit(
                        "health_check", check="vision_planner_bridge", ok=True,
                        adapter=self.adapter.method,
                    )
                    return health
                previous_sequence = sequence
            if (
                self.bridge_process is not None
                and self.bridge_process.poll() is not None
            ):
                break
            time.sleep(1)
        raise InfrastructureError(
            "bridge_health", "vision planner bridge did not produce fresh synchronized frames"
        )

    def takeoff(self, timeout_s: float = 60.0) -> dict[str, Any]:
        flight = self.scenario["flight"]
        result = self.run_probe(
            "takeoff",
            timeout_s=timeout_s,
            takeoff_action="/robot_1/tasks/takeoff",
            takeoff_height=flight["takeoff_height_m"],
            takeoff_velocity=flight["takeoff_velocity_m_s"],
        )
        if not result.get("ok"):
            raise InfrastructureError(
                "takeoff", f"takeoff failed: {result.get('message', 'unknown error')}"
            )
        self.events.emit("takeoff_complete", message=result.get("message"))
        return result

    def start_telemetry(self, state: TrialState) -> ManagedProcess:
        command = [
            "python3",
            "-u",
            self.probe_container_path,
            "stream",
            "--odometry-topic",
            "/robot_1/odometry_conversion/odometry",
            "--status-topic",
            self.adapter.status_topic,
            "--contact-topic",
            self.scenario["oracle"]["collision"]["contact_topic"],
            "--sample-rate",
            str(self.scenario["trial"].get("odometry_sample_rate_hz", 10.0)),
        ]
        process = ManagedProcess(
            [
                "docker",
                "exec",
                self.robot_container,
                "bash",
                "-lc",
                self._ros_shell(command),
            ],
            self._log("telemetry.log"),
            on_line=state.telemetry_line,
        )
        self.events.emit("telemetry_started")
        return process

    def start_worker(self, state: TrialState) -> ManagedProcess:
        goal_distance = self.scenario["flight"]["goal"]["offset_m"][0]
        try:
            command, environment = self.adapter.worker_command(
                self.planner,
                airstack=self.airstack,
                depth_source=self.scenario["planner"]["depth_source"],
                goal_distance_m=goal_distance,
            )
        except PlannerAdapterError as exc:
            raise InfrastructureError("planner_start", str(exc)) from exc
        self.worker_process = ManagedProcess(
            command,
            self._log(self.adapter.worker_log),
            cwd=(None if self.adapter.method == "mononav" else self.planner["repo"]),
            env=environment,
            on_line=state.planner_line,
        )
        self.events.emit("planner_started", method=self.adapter.method, command=command)
        return self.worker_process

    def pause(self) -> None:
        url = self.planner["bridge"]["health_url"].rstrip("/") + "/pause"
        code = (
            "import sys,urllib.request; "
            "r=urllib.request.Request(sys.argv[1],data=b'{}',method='POST'); "
            "print(urllib.request.urlopen(r,timeout=2).read().decode())"
        )
        self._run(
            ["docker", "exec", self.robot_container, "python3", "-c", code, url],
            "cleanup.log",
            timeout_s=8,
            check=False,
        )

    def collect_container_logs(self, since: str) -> None:
        for container, filename in (
            (self.sim_container, "isaac-sim.log"),
            (self.robot_container, "robot.log"),
        ):
            result = subprocess.run(
                ["docker", "logs", "--since", since, container],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output = result.stdout
            panes = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "tmux",
                    "list-panes",
                    "-a",
                    "-F",
                    "#{session_name}:#{window_index}.#{pane_index}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for pane in panes.stdout.splitlines():
                capture = subprocess.run(
                    [
                        "docker",
                        "exec",
                        container,
                        "tmux",
                        "capture-pane",
                        "-p",
                        "-S",
                        "-2000",
                        "-t",
                        pane,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                output += f"\n===== tmux {pane} =====\n{capture.stdout}"
            self._log(filename).write_text(output, encoding="utf-8")

    def cleanup(
        self,
        telemetry: ManagedProcess | None,
        recording: ManagedProcess | None,
        *,
        teardown_stack: bool,
    ) -> None:
        self.events.emit("cleanup_started")
        if self.stack_started:
            self.pause()
        worker_name = self.planner["container_name"]
        self._run(
            ["docker", "rm", "-f", worker_name],
            "cleanup.log",
            timeout_s=20,
            check=False,
        )
        if self.worker_process is not None:
            self.worker_process.stop()
        if recording is not None:
            recording.stop(timeout_s=20.0)
            if self.stack_started:
                self._fix_recording_ownership()
        if telemetry is not None:
            telemetry.stop()
        if self.bridge_process is not None:
            self.bridge_process.stop()
        if teardown_stack and self.stack_started:
            cli = str(self.repo / self.airstack.get("cli", "airstack.sh"))
            self._run(
                [cli, "down"],
                "cleanup.log",
                cwd=self.repo,
                timeout_s=150,
                check=False,
            )
            self.stack_started = False
        self.events.emit("cleanup_complete")


class TrialRunner:
    def __init__(
        self,
        scenario: dict[str, Any],
        results_root: Path,
        *,
        teardown_stack: bool = True,
    ) -> None:
        self.scenario = scenario
        self.results_root = results_root
        self.teardown_stack = teardown_stack

    def run(self) -> tuple[Path, dict[str, Any]]:
        trial_id = (
            f"{self.scenario['scenario_id']}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        result_dir = self.results_root / trial_id
        result_dir.mkdir(parents=True, exist_ok=False)
        events = EventRecorder(result_dir / "events.jsonl")
        dump_scenario(self.scenario, result_dir / "scenario.yaml")
        started_at = utc_now()
        result: dict[str, Any] = {
            "schema_version": 3,
            "trial_id": trial_id,
            "scenario_id": self.scenario["scenario_id"],
            "configuration": {
                "hash": self.scenario["resolved"]["configuration_hash"],
                "seed": self.scenario.get("seed"),
                "repetition": self.scenario.get("repetition", 0),
                "threat_model_version": self.scenario.get("threat_model_version"),
                "planner_method": self.scenario["planner"]["method"],
                "planner_depth_source": self.scenario["planner"]["depth_source"],
            },
            "outcome": "infrastructure_error",
            "started_at_utc": started_at,
            "ended_at_utc": None,
            "metrics": {},
            "termination": None,
            "failure": None,
        }
        atomic_json(result_dir / "result.json", result)
        runtime = AirStackRuntime(self.scenario, result_dir, events)
        telemetry: ManagedProcess | None = None
        recording: ManagedProcess | None = None
        recording_artifact: str | None = None
        state: TrialState | None = None
        outcome = "infrastructure_error"
        failure = None
        planner_started_monotonic = None
        outcome_monotonic = None
        events.emit("trial_created", trial_id=trial_id)
        try:
            runtime.preflight()
            runtime.reset_stack()
            startup_timeout = self.scenario["trial"]["startup_timeout_s"]
            runtime.wait_for_stack(startup_timeout)
            runtime.start_bridge()
            runtime.wait_for_bridge(self.scenario["trial"]["bridge_start_timeout_s"])
            runtime.takeoff()
            post_takeoff = runtime.run_probe("wait", timeout_s=15, minimum_samples=5)
            if not post_takeoff.get("ok"):
                raise InfrastructureError(
                    "post_takeoff_odometry", "odometry stopped after takeoff"
                )
            start_position = [
                float(value) for value in post_takeoff["last_sample"]["position_m"]
            ]
            offset = self.scenario["flight"]["goal"]["offset_m"]
            goal_position = [a + b for a, b in zip(start_position, offset)]
            self.scenario["resolved"]["actual_takeoff_odometry_m"] = start_position
            self.scenario["resolved"]["goal_position_m"] = goal_position
            dump_scenario(self.scenario, result_dir / "scenario.yaml")
            events.emit(
                "mission_resolved",
                start_position_m=start_position,
                goal_position_m=goal_position,
            )
            state = TrialState(
                goal_position,
                self.scenario["flight"]["goal"]["radius_m"],
                self.scenario["resolved"]["obstacles"],
                self.scenario["trial"]["robot_radius_m"],
                events,
                adapter_name=runtime.adapter.method,
                collision_padding_m=self.scenario["oracle"]["collision"]["padding_m"],
                geometry_fallback=self.scenario["oracle"]["collision"]["geometry_fallback"],
            )
            recording = runtime.start_recording()
            telemetry = runtime.start_telemetry(state)
            deadline = time.monotonic() + 10
            while state.last_telemetry_wall is None and time.monotonic() < deadline:
                if telemetry.poll() is not None:
                    break
                time.sleep(0.1)
            if state.last_telemetry_wall is None:
                raise InfrastructureError(
                    "telemetry_start", "trial telemetry stream did not start"
                )
            worker = runtime.start_worker(state)
            planner_deadline = (
                time.monotonic() + self.scenario["trial"]["planner_start_timeout_s"]
            )
            while not state.planner_ready.wait(timeout=0.2):
                if worker.poll() is not None:
                    raise InfrastructureError(
                        "planner_start",
                        f"{runtime.adapter.method} exited before issuing a command "
                        f"(exit {worker.poll()})",
                    )
                if time.monotonic() >= planner_deadline:
                    health = runtime.bridge_health()
                    detail = (
                        "bridge unavailable"
                        if health is None
                        else "planner did not initialize"
                    )
                    raise InfrastructureError("planner_start", detail)
            state.activate()
            planner_started_monotonic = time.monotonic()
            timeout_s = self.scenario["trial"]["timeout_s"]
            wall_backstop_s = self.scenario["trial"]["timeout_wall_backstop_s"]
            events.emit(
                "trial_started",
                timeout_s=timeout_s,
                timeout_clock="sim",
                wall_backstop_s=wall_backstop_s,
            )
            last_health_check = 0.0
            bridge_failures = 0
            while True:
                now = time.monotonic()
                with state.lock:
                    collision = state.collision
                    goal_index = state.goal_reached_index
                    last_telemetry = state.last_telemetry_wall
                    sim_start = state.activation_sim_time_s
                    sim_now = state.last_sim_time_s
                if collision:
                    outcome = "collision"
                    break
                if (
                    goal_index is not None
                    or state.planner_terminal_reason == "goal threshold reached"
                ):
                    outcome = "goal_reached"
                    break
                if state.planner_terminal_reason is not None:
                    outcome = "planner_stopped"
                    break
                returncode = worker.poll()
                if returncode is not None:
                    if returncode == 0:
                        outcome = "planner_stopped"
                    else:
                        raise InfrastructureError(
                            "planner_runtime",
                            f"{runtime.adapter.method} exited unexpectedly "
                            f"(exit {returncode})",
                        )
                    break
                if recording is not None and recording.poll() is not None:
                    raise InfrastructureError(
                        "recording_runtime",
                        f"ros2 bag record exited unexpectedly (exit {recording.poll()})",
                    )
                if last_telemetry is None or now - last_telemetry > 5.0:
                    raise InfrastructureError(
                        "telemetry_runtime", "odometry became stale"
                    )
                sim_elapsed = (
                    None if sim_start is None or sim_now is None else sim_now - sim_start
                )
                deadline_status = flight_deadline_status(
                    sim_elapsed, timeout_s, now - planner_started_monotonic, wall_backstop_s
                )
                if deadline_status == "timeout":
                    outcome = "timeout"
                    break
                if deadline_status == "wall_backstop":
                    raise InfrastructureError(
                        "timeout_wall_backstop",
                        f"simulation time advanced {sim_elapsed or 0.0:.1f}s of "
                        f"{timeout_s:.1f}s in {wall_backstop_s:.0f}s wall clock",
                    )
                if now - last_health_check >= 2.0:
                    bridge_failures = (
                        0
                        if runtime.bridge_health() is not None
                        else bridge_failures + 1
                    )
                    if bridge_failures >= 3:
                        raise InfrastructureError(
                            "bridge_runtime", "bridge health was lost"
                        )
                    last_health_check = now
                time.sleep(0.1)
            outcome_monotonic = time.monotonic()
        except InfrastructureError as exc:
            outcome_monotonic = time.monotonic()
            outcome = "infrastructure_error"
            failure = {"stage": exc.stage, "message": str(exc)}
            events.emit("infrastructure_error", **failure)
        except (CommandError, OSError, KeyboardInterrupt) as exc:
            outcome_monotonic = time.monotonic()
            outcome = "infrastructure_error"
            failure = {"stage": "runner", "message": str(exc)}
            events.emit("infrastructure_error", **failure)
        finally:
            try:
                runtime.collect_container_logs(started_at)
            except Exception as exc:  # best effort; never replace the flight verdict
                events.emit("artifact_collection_error", message=str(exc))
            try:
                runtime.cleanup(
                    telemetry,
                    recording,
                    teardown_stack=self.teardown_stack,
                )
                recording_artifact = runtime.collect_recording()
            except Exception as exc:  # result must survive cleanup failures
                events.emit("cleanup_error", message=str(exc))
                if outcome != "infrastructure_error":
                    failure = {"stage": "cleanup", "message": str(exc)}
            metrics: dict[str, Any] = {}
            if state is not None:
                with state.lock:
                    samples = list(state.samples)
                    goal_index = state.goal_reached_index
                if outcome == "goal_reached" and goal_index is None and samples:
                    goal_index = len(samples) - 1
                metrics = summarize(
                    samples,
                    state.goal_position_m,
                    state.obstacles,
                    state.robot_radius_m,
                    goal_index,
                    state.planner_hold_count,
                    state.planner_recovery_count,
                )
                metrics["planner_reported_final_distance_m"] = (
                    state.planner_terminal_distance_m
                )
                metrics["planner_wall_duration_s"] = (
                    None
                    if planner_started_monotonic is None
                    else (outcome_monotonic or time.monotonic())
                    - planner_started_monotonic
                )
                metrics["planner_sim_duration_s"] = (
                    None
                    if state.activation_sim_time_s is None or state.last_sim_time_s is None
                    else state.last_sim_time_s - state.activation_sim_time_s
                )
                authoritative = self.scenario["oracle"]["collision"]["authoritative"]
                metrics["collision_oracle"] = {
                    "authoritative": authoritative,
                    "physx_contact_available": state.physx_contact_available,
                    "source": state.collision_source,
                }
                if not state.physx_contact_available:
                    events.emit(
                        "oracle_degraded",
                        authoritative=authoritative,
                        detail="PhysX contact topic never reported",
                    )
            termination = build_termination(outcome, state, failure)
            result.update(
                {
                    "outcome": outcome,
                    "ended_at_utc": utc_now(),
                    "metrics": metrics,
                    "termination": termination,
                    "failure": failure,
                    "provenance": runtime.provenance,
                    "artifacts": {
                        "scenario": "scenario.yaml",
                        "events": "events.jsonl",
                        "logs": sorted(path.name for path in result_dir.glob("*.log")),
                        "recording": recording_artifact,
                    },
                }
            )
            events.emit(
                "trial_finished",
                outcome=outcome,
                termination=termination,
                metrics=metrics,
            )
            atomic_json(result_dir / "result.json", result)
            events.close()
        return result_dir, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument(
        "--results-dir", type=Path, default=Path("/home/ubuntu/airlab-data/trials")
    )
    parser.add_argument(
        "--keep-stack", action="store_true", help="leave AirStack running after cleanup"
    )
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help="validate and print the fully resolved scenario",
    )
    args = parser.parse_args()
    scenario = load_scenario(args.scenario)
    if args.resolve_only:
        print(json.dumps(scenario, indent=2))
        return 0
    args.results_dir.mkdir(parents=True, exist_ok=True)
    lock_path = args.results_dir / ".trial.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        if not try_lock(lock):
            print("another AirStack trial is already running", file=sys.stderr)
            return 3
        try:
            runner = TrialRunner(
                scenario, args.results_dir, teardown_stack=not args.keep_stack
            )
            result_dir, result = runner.run()
        finally:
            unlock(lock)
    print(json.dumps({"result_dir": str(result_dir), **result}, indent=2))
    return 2 if result["outcome"] == "infrastructure_error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
