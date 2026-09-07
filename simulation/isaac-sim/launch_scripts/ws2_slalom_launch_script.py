#!/usr/bin/env python
"""
WS2 test bench launcher: single-drone PX4 + the three-box slalom course.

Built on the shared ``PegasusApp`` base (see pegasus_app.py) rather than a
standalone script — this is a scenario declaration plus two hooks:

 - ``post_scene_prep``: spawns the slalom obstacles (with optional
   deterministic jitter for domain randomization).
 - ``run`` (overridden): the same follow-cam/step loop as the base class,
   with a PhysX contact reporter tick added so the automated test bench gets
   a ground-truth collision signal independent of the planner under test.

Dome light and base-environment selection are *not* reimplemented here —
they use PegasusApp's own ``ISAAC_SIM_DOME_LIGHT`` / ``ISAAC_SIM_SCENE``
mechanisms directly (see pegasus_app.py).

Env vars specific to this script:
 - ``MONONAV_SCENE_SEED`` / ``_LATERAL_JITTER_M`` / ``_LONGITUDINAL_JITTER_M`` /
   ``_SCALE_JITTER`` / ``_OBSTACLE_COUNT``: obstacle domain randomization.
 - ``MONONAV_PHYSX_CONTACT_TOPIC``: where the contact reporter publishes
   (default ``/robot_1/simulation/physx_contact``).
 - ``MONONAV_PRESENTATION_OVERVIEW``: opt-in wide/high camera for capture.
 - ``DRONE_INIT_X`` / ``_Y`` / ``_Z``: spawn pose (default 0, 0, 0.07).
 - ``ENABLE_LIDAR``: forwarded to PegasusApp's per-drone lidar toggle.

See pegasus_app.py for the env vars it already owns (``ISAAC_SIM_LIVESTREAM``,
``ISAAC_SIM_HEADLESS``, ``PLAY_SIM_ON_START``, ``ISAAC_SIM_SCENE``,
``ISAAC_SIM_STAGE_SCALE``, ``ISAAC_SIM_DOME_LIGHT``).
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pegasus_app import create_simulation_app

# Must be created before any omni/pegasus imports.
simulation_app = create_simulation_app()

import carb  # noqa: E402
from omni.isaac.core.world import World  # noqa: E402
from pegasus.simulator.params import SIMULATION_ENVIRONMENTS  # noqa: E402
from pegasus_app import PegasusApp, resolve_scene_from_env  # noqa: E402

PRESENTATION_OVERVIEW = os.environ.get("MONONAV_PRESENTATION_OVERVIEW", "false").lower() == "true"
_OVERVIEW_EYE = [4.5, -12.0, 10.0]
_OVERVIEW_LOOK = [4.5, 0.0, 0.8]


def add_slalom_obstacles(stage):
    """Add the stock slalom course, optionally with deterministic test jitter.

    Defaults are exactly the fixed three-box scene. Set a seed plus one or
    more nonzero jitter limits to create a replayable domain-randomized case.
    """
    import random

    from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics

    seed = os.environ.get("MONONAV_SCENE_SEED") or None
    lateral_jitter_m = float(os.environ.get("MONONAV_SCENE_LATERAL_JITTER_M", "0.0"))
    longitudinal_jitter_m = float(os.environ.get("MONONAV_SCENE_LONGITUDINAL_JITTER_M", "0.0"))
    scale_jitter = float(os.environ.get("MONONAV_SCENE_SCALE_JITTER", "0.0"))
    obstacle_count = int(os.environ.get("MONONAV_SCENE_OBSTACLE_COUNT", "3"))
    if lateral_jitter_m < 0.0 or longitudinal_jitter_m < 0.0 or not 0.0 <= scale_jitter < 1.0:
        raise ValueError("scene jitter limits must be nonnegative; scale jitter must be below 1")
    if not 1 <= obstacle_count <= 3:
        raise ValueError("MONONAV_SCENE_OBSTACLE_COUNT must be between 1 and 3")
    rng = random.Random(int(seed)) if seed is not None else None
    obstacles = (
        ("CenterGate", (3.0, 0.0, 1.0), (0.6, 0.8, 2.0), (0.95, 0.32, 0.12)),
        ("LeftOffset", (5.1, -1.7, 1.0), (0.7, 1.0, 2.0), (0.12, 0.48, 0.95)),
        ("RightOffset", (7.2, 1.6, 1.0), (0.7, 1.0, 2.0), (0.95, 0.78, 0.10)),
    )
    resolved = []
    for name, position, dimensions, color in obstacles[:obstacle_count]:
        if rng is None:
            resolved_position, resolved_dimensions = position, dimensions
        else:
            x, y, z = position
            x += rng.uniform(-longitudinal_jitter_m, longitudinal_jitter_m)
            y += rng.uniform(-lateral_jitter_m, lateral_jitter_m)
            scale = rng.uniform(1.0 - scale_jitter, 1.0 + scale_jitter)
            resolved_position = (x, y, z)
            resolved_dimensions = tuple(component * scale for component in dimensions)
        cube = UsdGeom.Cube.Define(stage, f"/World/VisionPlannerDemo/{name}")
        cube.GetSizeAttr().Set(1.0)
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        xform = UsdGeom.Xformable(cube.GetPrim())
        xform.AddTranslateOp().Set(Gf.Vec3d(*resolved_position))
        xform.AddScaleOp().Set(Gf.Vec3f(*resolved_dimensions))
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        PhysxSchema.PhysxContactReportAPI.Apply(cube.GetPrim())
        resolved.append((name, resolved_position, resolved_dimensions))
    carb.log_info(f"[ws2_slalom] Added {len(resolved)} slalom obstacles; seed={seed}; resolved={resolved}")


class Ws2SlalomApp(PegasusApp):
    def post_scene_prep(self, stage):
        add_slalom_obstacles(stage)
        import omni.kit.app

        for _ in range(5):
            omni.kit.app.get_app().update()
        if PRESENTATION_OVERVIEW:
            self.pg.set_viewport_camera(_OVERVIEW_EYE, _OVERVIEW_LOOK)

    # --- PhysX contact reporter: ground-truth collision signal, independent
    # of whichever planner is under test. PegasusApp.run() has no per-tick
    # hook, so this overrides it wholesale (same loop body) with the
    # reporter init/publish calls added. ---

    def _initialize_contact_reporter(self):
        if self._contact_reporter_ready or self._contact_reporter_disabled:
            return
        import omni.usd
        from pxr import PhysxSchema

        drone_prim = omni.usd.get_context().get_stage().GetPrimAtPath("/World/base_link")
        if not drone_prim.IsValid():
            return
        try:
            PhysxSchema.PhysxContactReportAPI.Apply(drone_prim)
            from isaacsim.sensors.physics import _sensor
            import rclpy
            from std_msgs.msg import Bool

            if not rclpy.ok():
                rclpy.init(args=None)
            self._contact_node = rclpy.create_node("ws2_physx_contact_reporter")
            self._contact_message_type = Bool
            self._contact_publisher = self._contact_node.create_publisher(
                Bool,
                os.environ.get("MONONAV_PHYSX_CONTACT_TOPIC", "/robot_1/simulation/physx_contact"),
                10,
            )
            self._contact_interface = _sensor.acquire_contact_sensor_interface()
            self._contact_body_path = "/World/base_link"
            self._contact_reporter_ready = True
            carb.log_info("WS2 PhysX contact reporter ready")
        except Exception as exc:
            self._contact_reporter_disabled = True
            carb.log_warn(f"WS2 PhysX contact reporter unavailable: {exc}")

    def _publish_contact_state(self):
        if not self._contact_reporter_ready:
            return
        try:
            in_contact = False
            for contact in self._contact_interface.get_rigid_body_raw_data(self._contact_body_path):
                values = [*contact]
                bodies = {
                    self._contact_interface.decode_body_name(values[2]),
                    self._contact_interface.decode_body_name(values[3]),
                }
                if any(body.startswith("/World/VisionPlannerDemo/") for body in bodies):
                    in_contact = True
                    break
            now = time.monotonic()
            if in_contact != self._contact_last_value or now - self._contact_last_publish_wall >= 1.0:
                message = self._contact_message_type()
                message.data = in_contact
                self._contact_publisher.publish(message)
                self._contact_last_value = in_contact
                self._contact_last_publish_wall = now
            import rclpy

            rclpy.spin_once(self._contact_node, timeout_sec=0.0)
        except Exception as exc:
            self._contact_reporter_disabled = True
            carb.log_warn(f"WS2 PhysX contact reporter stopped: {exc}")

    def run(self):
        self._contact_reporter_ready = False
        self._contact_reporter_disabled = False
        self._contact_last_value = None
        self._contact_last_publish_wall = 0.0

        if self.play_on_start:
            self.timeline.play()
        else:
            self.timeline.stop()

        import omni.kit.app

        app = omni.kit.app.get_app()
        # The Pegasus viewport is initialized during play; apply the optional
        # overview after that initialization rather than during stage setup.
        if PRESENTATION_OVERVIEW:
            for _ in range(10):
                app.update()
            self.pg.set_viewport_camera(_OVERVIEW_EYE, _OVERVIEW_LOOK)

        while simulation_app.is_running() and not self.stop_sim:
            self._update_follow_cam()
            world = World.instance()
            if world is not None and hasattr(world, "_scene"):
                world.step(render=True)
                self._initialize_contact_reporter()
                self._publish_contact_state()
                if world is not self.world:
                    self.world = world
                    self.pg._world = world
            else:
                app.update()

        carb.log_warn("Closing simulation.")
        self.timeline.stop()
        simulation_app.close()


def main():
    env_url, stage_scale = resolve_scene_from_env(SIMULATION_ENVIRONMENTS)
    print(f"[ws2_slalom] Scene: {env_url} (stage_scale={stage_scale})")
    Ws2SlalomApp(
        env_url=env_url,
        stage_scale=stage_scale,
        drone_configs=[
            {
                "domain_id": 1,  # MAVLink port = 14540 + vehicle_id (= domain_id)
                "x_m": float(os.environ.get("DRONE_INIT_X", "0.0")),
                "y_m": float(os.environ.get("DRONE_INIT_Y", "0.0")),
                "z_m": float(os.environ.get("DRONE_INIT_Z", "0.07")),
                "prim": "/World/base_link",
                "node_name": "PX4Multirotor",
            }
        ],
        enable_lidar=os.environ.get("ENABLE_LIDAR", "false").lower() == "true",
    ).run()


if __name__ == "__main__":
    main()
