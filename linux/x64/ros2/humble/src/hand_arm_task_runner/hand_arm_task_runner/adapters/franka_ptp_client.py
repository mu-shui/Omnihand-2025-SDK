from __future__ import annotations

import time
from typing import Sequence

import rclpy
from franka_msgs.action import PTPMotion
from rclpy.action import ActionClient
from rclpy.node import Node


class FrankaPTPClient:
    def __init__(self, node: Node, action_name: str = "action_server/ptp_motion") -> None:
        self._node = node
        self._action_client = ActionClient(node, PTPMotion, action_name)

    def wait_ready(self, timeout_sec: float = 5.0) -> bool:
        return bool(self._action_client.wait_for_server(timeout_sec=timeout_sec))

    def send_goal_and_wait(
        self,
        arm_joints: Sequence[float],
        max_joint_velocities: Sequence[float],
        goal_tolerance: float,
        goal_accept_timeout_sec: float = 5.0,
        result_timeout_sec: float = 30.0,
    ) -> None:
        def _send_once() -> None:
            if not self.wait_ready(timeout_sec=1.0):
                raise RuntimeError("PTPMotion action server is not ready")

            goal = PTPMotion.Goal()
            goal.goal_joint_configuration = [float(v) for v in arm_joints]
            goal.maximum_joint_velocities = [float(v) for v in max_joint_velocities]
            goal.goal_tolerance = float(goal_tolerance)

            goal_future = self._action_client.send_goal_async(goal)
            rclpy.spin_until_future_complete(self._node, goal_future, timeout_sec=goal_accept_timeout_sec)
            if not goal_future.done():
                raise TimeoutError(
                    f"PTPMotion goal acceptance timeout after {goal_accept_timeout_sec:.1f}s"
                )
            goal_handle = goal_future.result()
            if goal_handle is None:
                raise RuntimeError("PTPMotion goal call failed")
            if not goal_handle.accepted:
                raise RuntimeError("PTPMotion goal rejected")

            result_future = goal_handle.get_result_async()
            rclpy.spin_until_future_complete(self._node, result_future, timeout_sec=result_timeout_sec)
            if not result_future.done():
                raise TimeoutError(
                    f"PTPMotion result timeout after {result_timeout_sec:.1f}s"
                )
            wrapped = result_future.result()
            if wrapped is None:
                raise RuntimeError("PTPMotion result call failed")

            status_code = int(wrapped.status)
            if status_code != 4:  # action_msgs/msg/GoalStatus.STATUS_SUCCEEDED
                err_msg = ""
                if wrapped.result is not None and hasattr(wrapped.result, "error_message"):
                    err_msg = wrapped.result.error_message
                raise RuntimeError(f"PTPMotion failed (status={status_code}): {err_msg}")

        try:
            _send_once()
        except RuntimeError as exc:
            text = str(exc).lower()
            retryable = "status=6" in text and (
                "unexpected motion started" in text or "attempted to start multiple motions" in text
            )
            if not retryable:
                raise
            # In field runs this is often a transient controller-state race.
            self._node.get_logger().warn("PTPMotion transient status=6 detected, retrying once after 1.0s.")
            time.sleep(1.0)
            _send_once()
