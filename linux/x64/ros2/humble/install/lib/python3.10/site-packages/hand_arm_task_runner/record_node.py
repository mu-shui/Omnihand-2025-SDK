from __future__ import annotations

from pathlib import Path

import rclpy
from rclpy.node import Node

from .adapters.omnihand_client import OmniHandClient
from .joint_state_reader import JointStateReader
from .models import Waypoint, write_yaml


class RecordNode(Node):
    def __init__(self) -> None:
        super().__init__("hand_arm_record_node")
        self.declare_parameter("waypoint_name", "waypoint_1")
        self.declare_parameter("output_dir", "waypoints")
        self.declare_parameter("hand_side", "left")
        self.declare_parameter("hand_timeout", 5.0)
        self.declare_parameter("goal_tolerance", 0.01)
        self.declare_parameter("arm_max_vel", [1.0] * 7)
        self.declare_parameter("joint_states_topic", "/joint_states")

    def run_once(self) -> None:
        waypoint_name = self.get_parameter("waypoint_name").value
        output_dir = Path(self.get_parameter("output_dir").value)
        hand_side = self.get_parameter("hand_side").value
        hand_timeout = float(self.get_parameter("hand_timeout").value)
        goal_tolerance = float(self.get_parameter("goal_tolerance").value)
        arm_max_vel = [float(v) for v in self.get_parameter("arm_max_vel").value]
        joint_states_topic = self.get_parameter("joint_states_topic").value

        hand_client = OmniHandClient(self, hand_side=hand_side)
        if not hand_client.wait_ready(timeout_sec=5.0):
            raise RuntimeError("OmniHand services not ready")

        arm_reader = JointStateReader(self, topic=joint_states_topic, arm_dof=7)
        self.get_logger().info("Reading current arm joints from joint_states...")
        arm_joints = arm_reader.get_arm_joints(timeout_sec=3.0)
        self.get_logger().info("Reading current hand joints from OmniHand service...")
        hand_joints = hand_client.get_joint_angles()

        waypoint = Waypoint(
            name=waypoint_name,
            arm_joints=arm_joints,
            hand_joints=hand_joints,
            arm_max_vel=arm_max_vel,
            goal_tolerance=goal_tolerance,
            hand_timeout=hand_timeout,
        )
        waypoint.validate()

        path = output_dir / f"{waypoint_name}.yaml"
        write_yaml(path, waypoint.to_dict())
        self.get_logger().info(f"Saved waypoint: {path}")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = RecordNode()
    try:
        node.run_once()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
