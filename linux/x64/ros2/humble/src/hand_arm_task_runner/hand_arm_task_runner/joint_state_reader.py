from __future__ import annotations

import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


class JointStateReader:
    def __init__(self, node: Node, topic: str = "/joint_states", arm_dof: int = 7) -> None:
        self._node = node
        self._arm_dof = arm_dof
        self._last_msg: JointState | None = None
        self._sub = node.create_subscription(JointState, topic, self._cb, 10)

    def _cb(self, msg: JointState) -> None:
        self._last_msg = msg

    def get_arm_joints(self, timeout_sec: float = 2.0) -> list[float]:
        # 强制等待“本次调用之后”的新消息，避免读取上一次缓存导致点位记录不一致。
        self._last_msg = None
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if self._last_msg is not None and len(self._last_msg.position) >= self._arm_dof:
                return [float(v) for v in self._last_msg.position[: self._arm_dof]]
            rclpy.spin_once(self._node, timeout_sec=0.05)
        raise RuntimeError("Failed to get arm joint state from topic")
