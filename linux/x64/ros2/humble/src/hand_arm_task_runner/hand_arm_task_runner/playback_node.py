from __future__ import annotations

from pathlib import Path

import rclpy
from rclpy.node import Node

from .adapters.franka_ptp_client import FrankaPTPClient
from .adapters.omnihand_client import OmniHandClient
from .models import Waypoint, read_yaml


class PlaybackNode(Node):
    def __init__(self) -> None:
        super().__init__("hand_arm_playback_node")
        self.declare_parameter("waypoint_file", "waypoints/waypoint_1.yaml")
        self.declare_parameter("hand_side", "left")
        self.declare_parameter("hand_backend", "python_sdk")
        self.declare_parameter("hand_device", "zlgcan")
        self.declare_parameter("hand_rs485_port", "/dev/ttyUSB0")
        self.declare_parameter("hand_zlgcan_tcp_host", "127.0.0.1")
        self.declare_parameter("hand_zlgcan_tcp_port", 8000)
        self.declare_parameter("franka_action_name", "action_server/ptp_motion")
        self.declare_parameter("dry_run", False)
        self.declare_parameter("arm_velocity_scale", 1.0)

    def run_once(self) -> None:
        waypoint_file = Path(self.get_parameter("waypoint_file").value)
        hand_side = self.get_parameter("hand_side").value
        hand_backend = str(self.get_parameter("hand_backend").value)
        hand_device = str(self.get_parameter("hand_device").value)
        hand_rs485_port = str(self.get_parameter("hand_rs485_port").value)
        hand_zlgcan_tcp_host = str(self.get_parameter("hand_zlgcan_tcp_host").value)
        hand_zlgcan_tcp_port = int(self.get_parameter("hand_zlgcan_tcp_port").value)
        action_name = self.get_parameter("franka_action_name").value
        dry_run = bool(self.get_parameter("dry_run").value)
        arm_velocity_scale = float(self.get_parameter("arm_velocity_scale").value)
        if arm_velocity_scale <= 0.0 or arm_velocity_scale > 1.0:
            raise ValueError("arm_velocity_scale must be in (0.0, 1.0]")

        waypoint = Waypoint.from_dict(read_yaml(waypoint_file))
        self.get_logger().info(f"Loaded waypoint: {waypoint.name}")

        if dry_run:
            self.get_logger().info("Dry-run enabled. Validation passed; no command sent.")
            return

        arm_client = FrankaPTPClient(self, action_name=action_name)
        if not arm_client.wait_ready(timeout_sec=5.0):
            raise RuntimeError("Franka PTP action server not ready")

        hand_client = OmniHandClient(
            self,
            hand_side=hand_side,
            backend=hand_backend,
            device=hand_device,
            rs485_port=hand_rs485_port,
            zlgcan_tcp_host=hand_zlgcan_tcp_host,
            zlgcan_tcp_port=hand_zlgcan_tcp_port,
        )
        if not hand_client.wait_ready(timeout_sec=5.0):
            raise RuntimeError("OmniHand backend is not ready")

        self.get_logger().info("Executing arm motion...")
        scaled_vel = [v * arm_velocity_scale for v in waypoint.arm_max_vel]
        arm_client.send_goal_and_wait(
            arm_joints=waypoint.arm_joints,
            max_joint_velocities=scaled_vel,
            goal_tolerance=waypoint.goal_tolerance,
        )
        self.get_logger().info("Arm reached target. Executing hand motion...")
        hand_client.set_joint_angles(waypoint.hand_joints, timeout=waypoint.hand_timeout)
        self.get_logger().info("Playback completed.")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = PlaybackNode()
    try:
        node.run_once()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
