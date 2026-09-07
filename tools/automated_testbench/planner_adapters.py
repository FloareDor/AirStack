"""Narrow, deterministic adapters for the supported WS2 planners.

The scenario selects a method and supplies only that method's checked-in worker
configuration.  Search proposals never construct commands, start containers, or
select lifecycle hooks; those remain owned by :mod:`run_trial`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PlannerAdapterError(ValueError):
    """Raised when a scenario cannot be translated to a supported worker."""


@dataclass(frozen=True)
class PlannerAdapter:
    """Static method-specific details behind the common trial contract."""

    method: str
    config_key: str
    namespace: str
    worker_log: str
    launch_file: str

    @property
    def status_topic(self) -> str:
        return f"/robot_1/{self.namespace}/status"

    def bridge_command(self, bridge_arguments: dict[str, str]) -> list[str]:
        if self.method == "mononav":
            return [
                "ros2",
                "launch",
                "mononav_bridge",
                "mononav_bridge.launch.xml",
                "mononav_bridge_max_frame_rate:=3.0",
                "mononav_bridge_execute_commands:=true",
                *[f"{name}:={value}" for name, value in bridge_arguments.items()],
            ]
        translated = {
            name.replace("mononav_bridge_", "vision_planner_"): value
            for name, value in bridge_arguments.items()
        }
        return [
            "ros2",
            "launch",
            "mononav_bridge",
            "vision_planner_bridge.launch.xml",
            f"vision_planner_name:={self.method}",
            f"vision_planner_namespace:={self.namespace}",
            "vision_planner_max_frame_rate:=3.0",
            "vision_planner_execute_commands:=true",
            *[f"{name}:={value}" for name, value in translated.items()],
        ]

    def required_paths(self, config: dict[str, Any]) -> list[Path]:
        repo = Path(str(config["repo"]))
        if self.method == "mononav":
            return [repo / "mononav_airstack.py"]
        return [repo / str(config["worker_script"])]

    def worker_command(
        self,
        config: dict[str, Any],
        *,
        airstack: dict[str, Any],
        depth_source: str,
        goal_distance_m: float,
    ) -> tuple[list[str], dict[str, str] | None]:
        """Return the explicit host command and only required worker environment."""
        args = config.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise PlannerAdapterError(f"{self.config_key}.args must be a list of strings")
        if self.method == "mononav":
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                str(config["container_name"]),
                "--gpus",
                "all",
                "--network",
                str(airstack.get("docker_network", "airstack_airstack_network")),
            ]
            cache_volume = config.get("torch_cache_volume")
            if cache_volume:
                command.extend(["-v", f"{cache_volume}:/root/.cache/torch"])
            command.extend(
                [
                    "-v",
                    f"{config['repo']}:/workspace/MonoNav",
                    "-w",
                    "/workspace/MonoNav",
                    str(config["image"]),
                    "python",
                    "-u",
                    "mononav_airstack.py",
                    "--server",
                    str(config["bridge"]["server_url"]),
                    "--headless",
                    "--execute",
                    "--depth-source",
                    depth_source,
                    "--goal-distance",
                    str(goal_distance_m),
                    *args,
                ]
            )
            return command, None

        # The upstream adapter owns its GPU container invocation.  The bench only
        # gives it its documented execution flag and a fixed, validated argument
        # vector; a generator has no route to change Docker/ROS/PX4 lifecycle.
        command = [
            str(Path(str(config["repo"])) / str(config["worker_script"])),
            "--depth-source",
            depth_source,
            *args,
        ]
        environment = os.environ.copy()
        environment["COLLISION_AVOIDANCE_EXECUTE"] = "true"
        environment["COLLISION_AVOIDANCE_CONTAINER_NAME"] = str(
            config["container_name"]
        )
        # run_airstack_live.sh requires DISPLAY for its X11 passthrough volume
        # mount; unlike mononav_airstack.py (--headless), this worker's upstream
        # script hard-fails without it. reset_stack() only exports DISPLAY into
        # the airstack.sh subprocess env, not this process's own environment.
        environment["DISPLAY"] = str(airstack.get("display", ":99"))
        return command, environment


_ADAPTERS = {
    "mononav": PlannerAdapter(
        method="mononav",
        config_key="mononav",
        namespace="mononav",
        worker_log="mononav.log",
        launch_file="mononav_bridge.launch.xml",
    ),
    "collision_avoidance": PlannerAdapter(
        method="collision_avoidance",
        config_key="collision_avoidance",
        namespace="collision_avoidance",
        worker_log="collision_avoidance.log",
        launch_file="vision_planner_bridge.launch.xml",
    ),
}


def adapter_for(method: str) -> PlannerAdapter:
    try:
        return _ADAPTERS[method]
    except KeyError as exc:
        raise PlannerAdapterError(f"unsupported planner method: {method}") from exc
