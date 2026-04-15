from __future__ import annotations

import json
from pathlib import Path
import socket
import time

import rclpy
from rclpy.node import Node

from .adapters.franka_ptp_client import FrankaPTPClient
from .adapters.omnihand_client import OmniHandClient
from .models import SequencePlan, Waypoint, read_yaml

STEP_FINGER_MAP = {
    "1_1": ("index", "食指压力"),
    "1_2": ("middle", "中指压力"),
    "1_3": ("ring", "无名指压力"),
    "1_4": ("little", "小拇指压力"),
}


class SequenceNode(Node):
    def __init__(self) -> None:
        super().__init__("hand_arm_sequence_node")
        self.declare_parameter("sequence_file", "sequences/task_1.yaml")
        self.declare_parameter("waypoints_dir", "waypoints")
        self.declare_parameter("hand_side", "left")
        self.declare_parameter("franka_action_name", "action_server/ptp_motion")
        self.declare_parameter("dry_run", False)
        self.declare_parameter("inter_step_delay_sec", 0.0)
        self.declare_parameter("arm_velocity_scale", 0.2)
        self.declare_parameter("hold_after_step_sec", 3.0)
        self.declare_parameter("hand_reset_enabled", True)
        self.declare_parameter("hand_reset_angles", [0.0] * 10)
        self.declare_parameter("post_reset_delay_sec", 1.0)
        self.declare_parameter("tcp_enabled", False)
        self.declare_parameter("tcp_host", "192.168.10.1")
        self.declare_parameter("tcp_port", 5001)
        self.declare_parameter("tcp_timeout_sec", 2.0)

    def _load_step_waypoint(self, waypoints_dir: Path, step_name: str) -> Waypoint:
        path = waypoints_dir / f"{step_name}.yaml"
        raw = read_yaml(path)
        if "name" not in raw:
            raw["name"] = step_name
        return Waypoint.from_dict(raw)

    def _send_tcp_event(
        self,
        enabled: bool,
        host: str,
        port: int,
        timeout_sec: float,
        message: dict[str, object],
    ) -> None:
        if not enabled:
            return
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with socket.create_connection((host, port), timeout=timeout_sec) as sock:
            sock.sendall(line.encode("utf-8"))
            sock.settimeout(timeout_sec)
            try:
                ack = sock.recv(1024)
                if ack:
                    self.get_logger().info(f"TCP ACK: {ack.decode('utf-8', 'ignore').strip()}")
                else:
                    self.get_logger().warn("TCP peer closed connection without ACK.")
            except TimeoutError:
                event_type = str(message.get("type", "UNKNOWN"))
                step = str(message.get("step", ""))
                self.get_logger().warn(
                    f"TCP ACK timeout for event={event_type} step={step}. Continue without ACK."
                )

    def run_once(self) -> None:
        sequence_file = Path(self.get_parameter("sequence_file").value)
        waypoints_dir = Path(self.get_parameter("waypoints_dir").value)
        self.get_logger().info(
            f"Loading sequence (cwd={Path.cwd()}): "
            f"sequence_file={sequence_file} -> {sequence_file.resolve()}, "
            f"waypoints_dir={waypoints_dir} -> {waypoints_dir.resolve()}"
        )
        hand_side = self.get_parameter("hand_side").value
        action_name = self.get_parameter("franka_action_name").value
        dry_run = bool(self.get_parameter("dry_run").value)
        inter_step_delay_sec = float(self.get_parameter("inter_step_delay_sec").value)
        arm_velocity_scale = float(self.get_parameter("arm_velocity_scale").value)
        hold_after_step_sec = float(self.get_parameter("hold_after_step_sec").value)
        hand_reset_enabled = bool(self.get_parameter("hand_reset_enabled").value)
        hand_reset_angles = [float(v) for v in self.get_parameter("hand_reset_angles").value]
        post_reset_delay_sec = float(self.get_parameter("post_reset_delay_sec").value)
        tcp_enabled = bool(self.get_parameter("tcp_enabled").value)
        tcp_host = str(self.get_parameter("tcp_host").value)
        tcp_port = int(self.get_parameter("tcp_port").value)
        tcp_timeout_sec = float(self.get_parameter("tcp_timeout_sec").value)
        if arm_velocity_scale <= 0.0 or arm_velocity_scale > 1.0:
            raise ValueError("arm_velocity_scale must be in (0.0, 1.0]")
        if hold_after_step_sec < 0.0 or post_reset_delay_sec < 0.0:
            raise ValueError("hold_after_step_sec and post_reset_delay_sec must be >= 0")

        sequence = SequencePlan.from_dict(read_yaml(sequence_file))
        self.get_logger().info(f"Loaded {len(sequence.steps)} steps from sequence.")

        waypoints = [self._load_step_waypoint(waypoints_dir, s) for s in sequence.steps]
        self.get_logger().info("All waypoint files validated.")
        if dry_run:
            self.get_logger().info("Dry-run enabled. No command sent.")
            return

        arm_client = FrankaPTPClient(self, action_name=action_name)
        if not arm_client.wait_ready(timeout_sec=5.0):
            raise RuntimeError("Franka PTP action server not ready")
        hand_client = OmniHandClient(self, hand_side=hand_side)
        if not hand_client.wait_ready(timeout_sec=5.0):
            raise RuntimeError("OmniHand services not ready")

        run_id = f"run-{int(time.time())}"
        self._send_tcp_event(
            tcp_enabled,
            tcp_host,
            tcp_port,
            tcp_timeout_sec,
            {"type": "TEST_START", "run_id": run_id, "t_ubuntu": time.time()},
        )
        for idx, (step_name, waypoint) in enumerate(zip(sequence.steps, waypoints), start=1):
            finger, label = STEP_FINGER_MAP.get(step_name, ("unknown", "未知压力"))
            self._send_tcp_event(
                tcp_enabled,
                tcp_host,
                tcp_port,
                tcp_timeout_sec,
                {
                    "type": "STEP_START",
                    "run_id": run_id,
                    "step": step_name,
                    "finger": finger,
                    "label": label,
                    "t_ubuntu": time.time(),
                },
            )
            self.get_logger().info(f"[Step {idx}/{len(waypoints)}] arm -> {waypoint.name}")
            scaled_vel = [v * arm_velocity_scale for v in waypoint.arm_max_vel]
            arm_client.send_goal_and_wait(
                arm_joints=waypoint.arm_joints,
                max_joint_velocities=scaled_vel,
                goal_tolerance=waypoint.goal_tolerance,
            )
            self.get_logger().info(f"[Step {idx}/{len(waypoints)}] hand -> {waypoint.name}")
            hand_client.set_joint_angles(waypoint.hand_joints, timeout=waypoint.hand_timeout)

            if hold_after_step_sec > 0.0:
                self.get_logger().info(
                    f"[Step {idx}/{len(waypoints)}] hold {hold_after_step_sec:.2f}s at target."
                )
                time.sleep(hold_after_step_sec)

            # Mark this test item as finished when reset starts.
            # This matches the lab workflow: end-of-test == begin return-to-reset.
            self._send_tcp_event(
                tcp_enabled,
                tcp_host,
                tcp_port,
                tcp_timeout_sec,
                {
                    "type": "STEP_END",
                    "run_id": run_id,
                    "step": step_name,
                    "finger": finger,
                    "label": label,
                    "t_ubuntu": time.time(),
                },
            )

            if hand_reset_enabled:
                if len(hand_reset_angles) != len(waypoint.hand_joints):
                    raise ValueError(
                        "hand_reset_angles length must equal hand joints length "
                        f"({len(waypoint.hand_joints)}), got {len(hand_reset_angles)}"
                    )
                self.get_logger().info(f"[Step {idx}/{len(waypoints)}] hand -> reset pose.")
                hand_client.set_joint_angles(hand_reset_angles, timeout=waypoint.hand_timeout)
                if post_reset_delay_sec > 0.0:
                    self.get_logger().info(
                        f"[Step {idx}/{len(waypoints)}] sleep {post_reset_delay_sec:.2f}s after reset."
                    )
                    time.sleep(post_reset_delay_sec)

            if idx < len(waypoints) and inter_step_delay_sec > 0.0:
                self.get_logger().info(
                    f"[Step {idx}/{len(waypoints)}] sleep {inter_step_delay_sec:.2f}s before next step."
                )
                time.sleep(inter_step_delay_sec)

        self._send_tcp_event(
            tcp_enabled,
            tcp_host,
            tcp_port,
            tcp_timeout_sec,
            {"type": "TEST_END", "run_id": run_id, "t_ubuntu": time.time()},
        )
        self.get_logger().info("Sequence completed.")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SequenceNode()
    try:
        node.run_once()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
