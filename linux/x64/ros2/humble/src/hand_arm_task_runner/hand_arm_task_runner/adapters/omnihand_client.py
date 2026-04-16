from __future__ import annotations

from typing import Sequence

import rclpy
from omnihand_2025_node_msgs.srv import GetJointAngles, SetJointAngles
from rclpy.node import Node


class OmniHandClient:
    def __init__(
        self,
        node: Node,
        hand_side: str = "left",
        backend: str = "python_sdk",
        device: str = "zlgcan",
        rs485_port: str = "/dev/ttyUSB0",
        zlgcan_tcp_host: str = "127.0.0.1",
        zlgcan_tcp_port: int = 8000,
    ) -> None:
        self._node = node
        self._backend = str(backend).strip().lower()
        self._get_client = None
        self._set_client = None
        self._hand = None

        if self._backend == "ros_service":
            prefix = f"/omnihand/omnihand_2025/{hand_side}"
            self._get_client = node.create_client(GetJointAngles, f"{prefix}/get_joint_angles")
            self._set_client = node.create_client(SetJointAngles, f"{prefix}/set_joint_angles")
            return

        if self._backend != "python_sdk":
            raise ValueError(f"Unsupported hand backend: {backend}")

        # Lazy import to avoid hard dependency when using ROS service backend.
        from omnihand import HandType, OmniHand2025

        side = str(hand_side).strip().lower()
        hand_type = HandType.LEFT if side == "left" else HandType.RIGHT
        dev = str(device).strip().lower()
        if dev == "hcan":
            hand = OmniHand2025.create_hand_by_hcan(hand_type=hand_type)
        elif dev == "rs485":
            hand = OmniHand2025.create_hand_by_rs485(hand_type=hand_type, uart_port=str(rs485_port))
        elif dev == "zlgcan_tcp":
            hand = OmniHand2025.create_hand_by_zlgcan_tcp(
                hand_type=hand_type,
                host=str(zlgcan_tcp_host),
                port=int(zlgcan_tcp_port),
            )
        else:
            hand = OmniHand2025.create_hand_by_zlgcan(hand_type=hand_type)
        self._hand = hand

    def wait_ready(self, timeout_sec: float = 5.0) -> bool:
        if self._backend == "ros_service":
            ok_get = self._get_client.wait_for_service(timeout_sec=timeout_sec)
            ok_set = self._set_client.wait_for_service(timeout_sec=timeout_sec)
            return bool(ok_get and ok_set)
        return bool(self._hand.init())

    def get_joint_angles(self) -> list[float]:
        if self._backend == "python_sdk":
            return list(self._hand.get_all_active_joint_angles())
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
        if self._backend == "python_sdk":
            # Python SDK send API has no timeout argument; keep signature for compatibility.
            _ = timeout
            target = [float(v) for v in target_angles]
            self._hand.set_all_active_joint_angles(target)
            return list(self._hand.get_all_active_joint_angles())
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
