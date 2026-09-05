#!/usr/bin/env python3
"""Small in-container ROS 2 probe used by the host-side trial runner."""

from __future__ import annotations

import argparse
import json
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Bool, String
from task_msgs.action import TakeoffTask


class TelemetryProbe(Node):
    def __init__(
        self,
        odometry_topic: str,
        status_topic: str,
        contact_topic: str,
        sample_rate_hz: float,
    ):
        super().__init__("automated_testbench_probe")
        self.period_s = 1.0 / max(sample_rate_hz, 0.1)
        self.last_emit_wall = 0.0
        self.last_status = None
        self.samples = 0
        self.last_sample = None
        self.create_subscription(
            Odometry, odometry_topic, self.odometry_callback, qos_profile_sensor_data
        )
        self.create_subscription(String, status_topic, self.status_callback, 10)
        self.create_subscription(Bool, contact_topic, self.contact_callback, 10)

    @staticmethod
    def emit(payload):
        print(json.dumps(payload, separators=(",", ":")), flush=True)

    def odometry_callback(self, message):
        now = time.time()
        stamp = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        self.samples += 1
        self.last_sample = {
            "event": "odometry",
            "wall_time_s": now,
            "sim_time_s": stamp,
            "position_m": [
                message.pose.pose.position.x,
                message.pose.pose.position.y,
                message.pose.pose.position.z,
            ],
        }
        if now - self.last_emit_wall >= self.period_s:
            self.emit(self.last_sample)
            self.last_emit_wall = now

    def status_callback(self, message):
        if message.data == self.last_status:
            return
        self.last_status = message.data
        try:
            status = json.loads(message.data)
        except json.JSONDecodeError:
            status = {"raw": message.data}
        self.emit(
            {"event": "bridge_status", "wall_time_s": time.time(), "status": status}
        )

    def contact_callback(self, message):
        self.emit(
            {
                "event": "physx_contact",
                "wall_time_s": time.time(),
                "contact": bool(message.data),
            }
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("wait", "stream", "takeoff"))
    parser.add_argument("--odometry-topic", required=True)
    parser.add_argument("--status-topic", required=True)
    parser.add_argument("--contact-topic", required=True)
    parser.add_argument("--sample-rate", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--minimum-samples", type=int, default=5)
    parser.add_argument("--takeoff-action")
    parser.add_argument("--takeoff-height", type=float)
    parser.add_argument("--takeoff-velocity", type=float)
    args = parser.parse_args()

    rclpy.init()
    node = TelemetryProbe(
        args.odometry_topic,
        args.status_topic,
        args.contact_topic,
        args.sample_rate,
    )
    try:
        if args.mode == "takeoff":
            if not args.takeoff_action:
                parser.error("--takeoff-action is required in takeoff mode")
            client = ActionClient(node, TakeoffTask, args.takeoff_action)
            if not client.wait_for_server(timeout_sec=args.timeout):
                node.emit(
                    {
                        "event": "takeoff",
                        "ok": False,
                        "message": "action server unavailable",
                    }
                )
                raise SystemExit(2)
            goal = TakeoffTask.Goal()
            goal.target_altitude_m = float(args.takeoff_height)
            goal.velocity_m_s = float(args.takeoff_velocity)
            send_future = client.send_goal_async(goal)
            rclpy.spin_until_future_complete(
                node, send_future, timeout_sec=args.timeout
            )
            handle = send_future.result() if send_future.done() else None
            if handle is None or not handle.accepted:
                node.emit({"event": "takeoff", "ok": False, "message": "goal rejected"})
                raise SystemExit(2)
            result_future = handle.get_result_async()
            rclpy.spin_until_future_complete(
                node, result_future, timeout_sec=args.timeout
            )
            wrapped = result_future.result() if result_future.done() else None
            if wrapped is None:
                node.emit(
                    {"event": "takeoff", "ok": False, "message": "result timeout"}
                )
                raise SystemExit(2)
            result = wrapped.result
            node.emit(
                {
                    "event": "takeoff",
                    "ok": bool(result.success),
                    "message": result.message,
                    "status": int(wrapped.status),
                }
            )
            if not result.success:
                raise SystemExit(2)
            return
        if args.mode == "stream":
            rclpy.spin(node)
            return
        deadline = time.monotonic() + args.timeout
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            if node.samples >= args.minimum_samples and node.last_sample is not None:
                node.emit(
                    {
                        "event": "health",
                        "ok": True,
                        "samples": node.samples,
                        "last_sample": node.last_sample,
                    }
                )
                return
        node.emit({"event": "health", "ok": False, "samples": node.samples})
        raise SystemExit(2)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
