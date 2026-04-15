from __future__ import annotations

from typing import Sequence

import rclpy
from omnihand_2025_node_msgs.srv import GetJointAngles, SetJointAngles
from rclpy.node import Node


class OmniHandClient:
    def __init__(self, node: Node, hand_side: str = "left") -> None:
        self._node = node
        prefix = f"/omnihand/omnihand_2025/{hand_side}"
        self._get_client = node.create_client(GetJointAngles, f"{prefix}/get_joint_angles")
        self._set_client = node.create_client(SetJointAngles, f"{prefix}/set_joint_angles")

    def wait_ready(self, timeout_sec: float = 5.0) -> bool:
        ok_get = self._get_client.wait_for_service(timeout_sec=timeout_sec)
        ok_set = self._set_client.wait_for_service(timeout_sec=timeout_sec)
        return bool(ok_get and ok_set)

    def get_joint_angles(self) -> list[float]:
        request = GetJointAngles.Request()
        future = self._get_client.call_async(request)
        rclpy.spin_until_future_complete(self._node, future)
        response = future.result()
        if response is None:
            raise RuntimeError("GetJointAngles returned no response")
        if not response.is_ready:
            raise RuntimeError(f"Hand is not ready: {response.error_message}")
        return list(response.angles)

    def set_joint_angles(self, target_angles: Sequence[float], timeout: float) -> list[float]:
        request = SetJointAngles.Request()
        request.target_angles = [float(v) for v in target_angles]
        request.timeout = float(timeout)
        future = self._set_client.call_async(request)
        rclpy.spin_until_future_complete(self._node, future)
        response = future.result()
        if response is None:
            raise RuntimeError("SetJointAngles returned no response")
        if not response.success:
            raise RuntimeError(f"SetJointAngles failed: {response.error_message}")
        return list(response.final_angles)
