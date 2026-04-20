from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import math
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import Tk, StringVar, Text, BooleanVar, DoubleVar, IntVar, filedialog, messagebox
from tkinter import ttk

import rclpy
from rclpy.node import Node

try:
    from .adapters.franka_ptp_client import FrankaPTPClient
    from .adapters.omnihand_client import OmniHandClient
    from .joint_state_reader import JointStateReader
    from .models import Waypoint, read_yaml, write_yaml
except ImportError:
    # Support direct startup: `python gui_app.py`
    pkg_root = Path(__file__).resolve().parents[1]
    if str(pkg_root) not in sys.path:
        sys.path.insert(0, str(pkg_root))
    from hand_arm_task_runner.adapters.franka_ptp_client import FrankaPTPClient
    from hand_arm_task_runner.adapters.omnihand_client import OmniHandClient
    from hand_arm_task_runner.joint_state_reader import JointStateReader
    from hand_arm_task_runner.models import Waypoint, read_yaml, write_yaml

try:
    from omnihand_2025 import AgibotHandO10, EHandType
except ImportError:
    AgibotHandO10 = None
    EHandType = None

try:
    from omnihand.omnihand_2025 import OmniHand2025Solver
except ImportError:
    OmniHand2025Solver = None


@dataclass
class TaskStep:
    waypoint: str
    hold_sec: float = 3.0
    hand_reset_enabled: bool = True


class PauseTestCancelledError(RuntimeError):
    """Raised when pause-test flow requests cancellation."""


class RobotExecutor:
    def __init__(self, app: "MainApp") -> None:
        self.app = app
        self._node: Node | None = None
        self._arm: FrankaPTPClient | None = None
        self._hand: OmniHandClient | None = None
        self._arm_reader: JointStateReader | None = None
        self._arm_motion_guard = threading.Lock()

    def _ensure_node(self) -> Node:
        if not rclpy.ok():
            rclpy.init()
        if self._node is None:
            self._node = rclpy.create_node("hand_arm_gui_runtime")
        return self._node

    def _ensure_arm_client(self) -> None:
        node = self._ensure_node()
        if self._arm is None:
            self._arm = FrankaPTPClient(node, action_name=self.app.arm_action_name_var.get().strip())
            if not self._arm.wait_ready(timeout_sec=5.0):
                raise RuntimeError("Franka action server not ready")
        if self._arm_reader is None:
            self._arm_reader = JointStateReader(node, topic=self.app.joint_states_topic_var.get().strip(), arm_dof=7)

    def _ensure_arm_reader(self) -> None:
        node = self._ensure_node()
        if self._arm_reader is None:
            self._arm_reader = JointStateReader(node, topic=self.app.joint_states_topic_var.get().strip(), arm_dof=7)

    def _ensure_hand_client(self) -> None:
        node = self._ensure_node()
        if self._hand is None:
            try:
                self._hand = OmniHandClient(
                    node,
                    hand_side=self.app.hand_side_var.get().strip(),
                    backend=self.app.hand_backend_var.get().strip(),
                    device=self.app.hand_device_var.get().strip(),
                    rs485_port=self.app.hand_rs485_port_var.get().strip(),
                    zlgcan_tcp_host=self.app.hand_tcp_host_var.get().strip(),
                    zlgcan_tcp_port=int(self.app.hand_tcp_port_var.get().strip()),
                )
            except Exception as exc:  # noqa: BLE001
                self.app.log_hand(f"手连接创建失败: {exc}")
                raise RuntimeError(
                    "手连接创建失败。请检查: 1) 电源与CAN线 2) 设备类型(hand_device) "
                    "3) 手型(hand_side) 4) 是否被其它程序占用"
                ) from exc

            if not self._hand.wait_ready(timeout_sec=5.0):
                self.app.log_hand("手后端未就绪(wait_ready=False)")
                raise RuntimeError(
                    "手后端未就绪。请检查: 1) 设备是否上电 2) CAN/串口权限 "
                    "3) 是否有其它进程占用总线 4) 设备参数是否正确"
                )
            # 某些SDK场景下 wait_ready 可能返回成功，但实际总线仍不可用；这里强制回读一次。
            try:
                probe = self._hand.get_joint_angles()
            except Exception as exc:  # noqa: BLE001
                self.app.log_hand(f"手后端探测失败(get_joint_angles): {exc}")
                raise RuntimeError(f"手后端探测失败，无法读取关节角度: {exc}") from exc
            if not isinstance(probe, list) or len(probe) < 10:
                raise RuntimeError("手后端探测失败：读取到的关节角度数量异常（可能未上电）")

    def _ensure_clients(self) -> None:
        self._ensure_arm_client()
        self._ensure_hand_client()

    def reset_hand_client(self) -> None:
        # Raw hand close/open may reset CAN resources; force recreate on next use.
        self._hand = None

    def _arm_settle_sleep(self, context: str = "arm motion") -> None:
        try:
            settle_sec = max(0.0, float(self.app.arm_motion_settle_sec_var.get()))
        except Exception:
            settle_sec = 1.0
        if settle_sec > 0:
            self.app.log_control(f"{context}: 等待机械臂稳定 {settle_sec:.2f}s")
            time.sleep(settle_sec)

    def _send_arm_goal_guarded(
        self,
        *,
        context: str,
        arm_joints: list[float] | tuple[float, ...],
        max_joint_velocities: list[float] | tuple[float, ...],
        goal_tolerance: float,
    ) -> None:
        self.app.wait_for_pause_test_gate(context)
        assert self._arm is not None
        if not self._arm_motion_guard.acquire(blocking=False):
            raise RuntimeError(f"{context}: 检测到已有机械臂 motion 正在执行，已拒绝新的 motion 请求。")
        try:
            self.app.log_arm(f"{context}: 提交PTPMotion目标")
            self._arm.send_goal_and_wait(arm_joints, max_joint_velocities, goal_tolerance)
        finally:
            self._arm_motion_guard.release()

    def _set_hand_angles(self, target_angles: list[float], timeout: float, context: str = "hand") -> list[float]:
        # If manual raw-hand is active, drive hand through raw-hand path to avoid CAN conflicts.
        if bool(getattr(self.app, "raw_hand_connected", False)):
            hand = self.app._ensure_raw_hand()
            solver = self.app._get_raw_hand_solver()
            actuator_positions = solver.active_joint_pos_to_actuator_input([float(v) for v in target_angles])
            if len(actuator_positions) < 10:
                raise RuntimeError(f"{context}: 目标转换失败，位置数量异常 {len(actuator_positions)}")
            send_results: list[object] = []
            for i, pos in enumerate(actuator_positions[:10], start=1):
                send_results.append(hand.set_joint_position(i, int(pos)))
            if any(self.app._is_hand_send_failed(v) for v in send_results):
                raise RuntimeError(f"{context}: raw_hand 下发失败（可能CAN总线异常）")
            # Keep GUI sliders in sync with target when this path is used.
            self.app.root.after(0, lambda vals=list(actuator_positions[:10]): [self.app.hand_pos_vars[i].set(int(vals[i])) for i in range(10)])
            return [float(v) for v in target_angles]

        self._ensure_hand_client()
        assert self._hand is not None
        return self._hand.set_joint_angles(target_angles, timeout=timeout)

    def _read_hand_angles_for_capture(self) -> list[float]:
        # 手动手控模式下记录“目标值”而不是“反馈值”，避免被夹持/卡住时记录到错误姿态。
        if bool(getattr(self.app, "raw_hand_connected", False)):
            return self.app._get_raw_hand_target_angles_from_sliders()
        self._ensure_hand_client()
        assert self._hand is not None
        vals = self._hand.get_joint_angles()
        return self.app._validate_hand_feedback(vals, min_len=10)

    def record_waypoint(self, name: str, note: str) -> Path:
        self._ensure_arm_reader()
        assert self._arm_reader is not None
        arm_joints = self._arm_reader.get_arm_joints(timeout_sec=3.0)
        hand_joints = self._read_hand_angles_for_capture()
        wp = Waypoint(
            name=name,
            arm_joints=arm_joints,
            hand_joints=hand_joints,
            arm_max_vel=[1.0] * 7,
            goal_tolerance=0.01,
            hand_timeout=5.0,
        )
        payload = wp.to_dict()
        if note.strip():
            payload["note"] = note.strip()
        path = self.app.waypoints_dir() / f"{name}.yaml"
        write_yaml(path, payload)
        return path

    def set_home_from_current(self) -> Path:
        self._ensure_arm_reader()
        assert self._arm_reader is not None
        arm_joints = self._arm_reader.get_arm_joints(timeout_sec=3.0)
        hand_joints = self._read_hand_angles_for_capture()
        home = {
            "name": "home",
            "arm_joints": arm_joints,
            "hand_joints": hand_joints,
            "arm_max_vel": [1.0] * 7,
            "goal_tolerance": 0.01,
            "hand_timeout": 5.0,
        }
        path = self.app.config_dir() / "home.yaml"
        write_yaml(path, home)
        return path

    def _load_home(self) -> Waypoint:
        path = self.app.config_dir() / "home.yaml"
        if not path.exists():
            raise RuntimeError("home.yaml not found. Please set initial position first.")
        return Waypoint.from_dict(read_yaml(path))

    def _load_waypoint(self, name: str) -> Waypoint:
        path = self.app.waypoints_dir() / f"{name}.yaml"
        if not path.exists():
            raise RuntimeError(f"Waypoint not found: {name}")
        return Waypoint.from_dict(read_yaml(path))

    def _go_home(self, home: Waypoint) -> None:
        assert self._arm is not None
        self.app.log_hand("回初始位: hand -> home")
        self._set_hand_angles(home.hand_joints, timeout=home.hand_timeout, context="回初始位")
        try:
            settle_sec = max(0.0, float(self.app.home_hand_settle_sec_var.get()))
        except Exception:
            settle_sec = 1.0
        if settle_sec > 0:
            self.app.log_control(f"回初始位: 等待手稳定 {settle_sec:.2f}s")
            time.sleep(settle_sec)
        self.app.log_control(f"回初始位: arm -> {home.arm_joints}")
        arm_scale = max(0.01, min(1.0, float(self.app.arm_velocity_scale_var.get())))
        scaled_vel = [float(v) * arm_scale for v in home.arm_max_vel]
        self._send_arm_goal_guarded(
            context="回初始位",
            arm_joints=home.arm_joints,
            max_joint_velocities=scaled_vel,
            goal_tolerance=home.goal_tolerance,
        )
        self._arm_settle_sleep("回初始位")

    def execute_task(self, task_name: str, go_home_before: bool = True, go_home_after: bool = True) -> None:
        self._ensure_clients()
        assert self._arm is not None and self._hand is not None
        home = self._load_home()
        task_path = self.app.tasks_dir() / f"{task_name}.yaml"
        task_raw = read_yaml(task_path)
        steps = task_raw.get("steps", [])
        if not steps:
            raise RuntimeError(f"Task has no steps: {task_name}")

        if go_home_before:
            self.app.log_control(f"[任务 {task_name}] 开始前回初始位")
            self._go_home(home)
        for i, step in enumerate(steps, start=1):
            wp_name = str(step["waypoint"])
            hold_sec = float(step.get("hold_sec", 3.0))
            hand_reset_enabled = bool(step.get("hand_reset_enabled", True))
            wp = self._load_waypoint(wp_name)
            self.app.log_arm(f"[任务 {task_name}] 步骤 {i}/{len(steps)} arm -> {wp_name}")
            arm_scale = max(0.01, min(1.0, float(self.app.arm_velocity_scale_var.get())))
            scaled_vel = [float(v) * arm_scale for v in wp.arm_max_vel]
            self._send_arm_goal_guarded(
                context=f"[任务 {task_name}] 步骤 {i}/{len(steps)} arm",
                arm_joints=wp.arm_joints,
                max_joint_velocities=scaled_vel,
                goal_tolerance=wp.goal_tolerance,
            )
            self._arm_settle_sleep(f"[任务 {task_name}] 步骤 {i} arm")
            self.app.log_hand(f"[任务 {task_name}] 步骤 {i}/{len(steps)} hand -> {wp_name}")
            self._set_hand_angles(wp.hand_joints, timeout=wp.hand_timeout, context=f"[任务 {task_name}] 步骤 {i} hand")
            if hold_sec > 0:
                self.app.log_control(f"[任务 {task_name}] 停留 {hold_sec:.2f}s")
                time.sleep(hold_sec)
            if hand_reset_enabled:
                self.app.log_hand(f"[任务 {task_name}] 手回位")
                self._set_hand_angles(home.hand_joints, timeout=home.hand_timeout, context=f"[任务 {task_name}] 手回位")
        if go_home_after:
            # User requirement: executing a single task should also return to home at the end.
            self.app.log_control(f"[任务 {task_name}] 结束后自动回初始位")
            self._go_home(home)
        self.app.log_control(f"[任务 {task_name}] 执行完成")

    def execute_plan(self, plan_name: str) -> None:
        self._ensure_clients()
        home = self._load_home()
        plan_path = self.app.plans_dir() / f"{plan_name}.yaml"
        raw = read_yaml(plan_path)
        task_names = [str(v) for v in raw.get("tasks", [])]
        if not task_names:
            raise RuntimeError(f"Plan has no tasks: {plan_name}")
        task_reset_enabled = bool(raw.get("task_reset_enabled", True))
        end_reset_enabled = bool(raw.get("end_reset_enabled", True))

        if not task_reset_enabled:
            self.app.log_control(f"[计划 {plan_name}] 开始，先回初始位")
            self._go_home(home)
        for idx, task_name in enumerate(task_names, start=1):
            if task_reset_enabled:
                self.app.log_control(f"[计划 {plan_name}] 任务 {idx}/{len(task_names)} 前回初始位")
                self._go_home(home)
            task_path = self.app.tasks_dir() / f"{task_name}.yaml"
            task_raw = read_yaml(task_path)
            steps = task_raw.get("steps", [])
            if not steps:
                raise RuntimeError(f"Task has no steps: {task_name}")
            for step_idx, step in enumerate(steps, start=1):
                wp_name = str(step["waypoint"])
                hold_sec = float(step.get("hold_sec", 3.0))
                hand_reset_enabled = bool(step.get("hand_reset_enabled", True))
                wp = self._load_waypoint(wp_name)
                self.app.log_arm(
                    f"[计划 {plan_name}] 任务 {idx}/{len(task_names)} 步骤 {step_idx}/{len(steps)} arm -> {wp_name}"
                )
                arm_scale = max(0.01, min(1.0, float(self.app.arm_velocity_scale_var.get())))
                scaled_vel = [float(v) * arm_scale for v in wp.arm_max_vel]
                self._send_arm_goal_guarded(
                    context=f"[计划 {plan_name}] 任务 {idx}/{len(task_names)} 步骤 {step_idx}/{len(steps)} arm",
                    arm_joints=wp.arm_joints,
                    max_joint_velocities=scaled_vel,
                    goal_tolerance=wp.goal_tolerance,
                )
                self._arm_settle_sleep(f"[计划 {plan_name}] 任务 {idx} 步骤 {step_idx} arm")
                self.app.log_hand(
                    f"[计划 {plan_name}] 任务 {idx}/{len(task_names)} 步骤 {step_idx}/{len(steps)} hand -> {wp_name}"
                )
                self._set_hand_angles(
                    wp.hand_joints,
                    timeout=wp.hand_timeout,
                    context=f"[计划 {plan_name}] 任务 {idx} 步骤 {step_idx} hand",
                )
                if hold_sec > 0:
                    self.app.log_control(f"[计划 {plan_name}] 任务 {idx} 步骤 {step_idx} 停留 {hold_sec:.2f}s")
                    time.sleep(hold_sec)
                if hand_reset_enabled:
                    self.app.log_hand(f"[计划 {plan_name}] 任务 {idx} 步骤 {step_idx} 手回位")
                    self._set_hand_angles(
                        home.hand_joints,
                        timeout=home.hand_timeout,
                        context=f"[计划 {plan_name}] 任务 {idx} 步骤 {step_idx} 手回位",
                    )
        if end_reset_enabled:
            self.app.log_control(f"[计划 {plan_name}] 结束回初始位")
            self._go_home(home)
        self.app.log_control(f"[计划 {plan_name}] 执行完成")

    def read_hand_angles(self) -> list[float]:
        self._ensure_hand_client()
        assert self._hand is not None
        return self._hand.get_joint_angles()

    def set_hand_angles(self, angles: list[float]) -> list[float]:
        self._ensure_hand_client()
        assert self._hand is not None
        return self._hand.set_joint_angles(angles, timeout=2.0)

    def move_to_waypoint(self, waypoint_name: str) -> None:
        self._ensure_arm_client()
        if not bool(getattr(self.app, "raw_hand_connected", False)):
            self._ensure_hand_client()
        assert self._arm is not None
        wp = self._load_waypoint(waypoint_name)
        self.app.log_control(f"[点位] 移动到 {waypoint_name}: arm")
        arm_scale = max(0.01, min(1.0, float(self.app.arm_velocity_scale_var.get())))
        scaled_vel = [float(v) * arm_scale for v in wp.arm_max_vel]
        self._send_arm_goal_guarded(
            context=f"[点位] {waypoint_name} arm",
            arm_joints=wp.arm_joints,
            max_joint_velocities=scaled_vel,
            goal_tolerance=wp.goal_tolerance,
        )
        self._arm_settle_sleep(f"[点位] {waypoint_name} arm")
        self.app.log_control(f"[点位] 移动到 {waypoint_name}: hand")
        self._set_hand_angles(wp.hand_joints, timeout=wp.hand_timeout, context=f"[点位] {waypoint_name} hand")

    def go_home_now(self) -> None:
        self._ensure_arm_client()
        if not bool(getattr(self.app, "raw_hand_connected", False)):
            self._ensure_hand_client()
        home = self._load_home()
        self._go_home(home)


class MainApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Hand Arm Task GUI")
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.running = False
        self._run_state_lock = threading.Lock()
        self._active_run: dict[str, object] | None = None
        self._run_seq = 0
        self._active_run_status_file = (Path.cwd() / "runtime" / "active_motion.json").resolve()
        self.env_initialized = False
        self.executor = RobotExecutor(self)
        self._pause_state_lock = threading.Lock()
        self._pause_continue_event = threading.Event()
        self._pause_test_enabled = False
        self._pause_cancel_requested = False
        self._pause_waiting_context = ""
        self._pause_waiting_since = 0.0

        self.hand_backend_var = StringVar(value="python_sdk")
        self.hand_device_var = StringVar(value="zlgcan")
        self.hand_side_var = StringVar(value="left")
        self.hand_rs485_port_var = StringVar(value="/dev/ttyUSB0")
        self.hand_tcp_host_var = StringVar(value="127.0.0.1")
        self.hand_tcp_port_var = StringVar(value="8000")
        self.arm_action_name_var = StringVar(value="action_server/ptp_motion")
        self.joint_states_topic_var = StringVar(value="/joint_states")
        self.task_hold_sec_var = StringVar(value="3.0")
        self.task_note_var = StringVar(value="")
        self.task_step_hand_reset_var = BooleanVar(value=True)
        self.plan_task_reset_var = BooleanVar(value=True)
        self.plan_end_reset_var = BooleanVar(value=True)
        self.waypoint_name_var = StringVar(value="waypoint_1")
        self.current_task_file_var = StringVar(value="")
        self.current_plan_file_var = StringVar(value="")
        self.hand_monitoring_var = BooleanVar(value=False)
        self.pause_test_enabled_var = BooleanVar(value=False)
        self.pause_test_status_var = StringVar(value="暂停测试：关闭")
        self.env_ros_var = StringVar(value="/opt/ros/humble/setup.bash")
        self.env_sdk_var = StringVar(
            value=str((Path.cwd() / "linux/x64/ros2/humble/install/setup.bash").resolve())
        )
        self.env_franka_var = StringVar(value="/home/agiuser/franka_ros2_ws/install/setup.bash")
        self.franka_robot_type_var = StringVar(value="fr3")
        self.franka_robot_ip_var = StringVar(value="192.169.0.2")
        self.auto_start_franka_var = BooleanVar(value=True)
        self.arm_velocity_scale_var = DoubleVar(value=0.2)
        self.arm_motion_settle_sec_var = StringVar(value="1.0")
        self.home_hand_settle_sec_var = StringVar(value="1.0")
        self.hand_joint_vars = [DoubleVar(value=0.0) for _ in range(10)]
        self.hand_pos_vars = [IntVar(value=0) for _ in range(10)]
        self.hand_joint_notes = [
            "大拇指旋转",
            "大拇指侧摆",
            "大拇指弯曲",
            "食指侧摆",
            "食指弯曲",
            "中指弯曲",
            "无名指侧摆",
            "无名指弯曲",
            "小拇指侧摆",
            "小拇指弯曲",
        ]
        self._hand_updating_from_device = False
        self._hand_send_after_id = None
        self.raw_hand = None
        self.raw_hand_connected = False
        self._raw_hand_solver = None
        self._raw_hand_solver_is_left: bool | None = None
        self.raw_hand_cfg_path = "/home/agiuser/Omnihand-2025-SDK-0.8.0/python/example/conf/hardware_conf.yaml"
        self.franka_launch_proc: subprocess.Popen | None = None
        self._last_popup_time: dict[str, float] = {}
        self._conflict_action_buttons: list[ttk.Button] = []
        self._write_active_run_status({"running": False, "note": "GUI initialized"})

        self._build_ui()
        self._refresh_all_lists()
        self._poll_logs()
        self._poll_runtime_status_panel()

    def waypoints_dir(self) -> Path:
        p = Path.cwd() / "point"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def tasks_dir(self) -> Path:
        p = Path.cwd() / "task"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def plans_dir(self) -> Path:
        p = Path.cwd() / "multitask"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def config_dir(self) -> Path:
        p = Path.cwd() / "config"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _log(self, channel: str, message: str) -> None:
        self.log_queue.put((channel, f"[{time.strftime('%H:%M:%S')}] {message}"))

    def log(self, message: str) -> None:
        self.log_control(message)

    def log_control(self, message: str) -> None:
        self._log("control", message)

    def log_arm(self, message: str) -> None:
        self._log("arm", message)

    def log_hand(self, message: str) -> None:
        self._log("hand", message)

    def popup_error(self, title: str, message: str, key: str | None = None, min_interval_sec: float = 2.0) -> None:
        now = time.time()
        k = key or f"{title}:{message[:80]}"
        last = self._last_popup_time.get(k, 0.0)
        if now - last < min_interval_sec:
            return
        self._last_popup_time[k] = now
        self.root.after(0, lambda t=title, m=message: messagebox.showerror(t, m))

    def popup_info(self, title: str, message: str, key: str | None = None, min_interval_sec: float = 1.0) -> None:
        now = time.time()
        k = key or f"{title}:{message[:80]}"
        last = self._last_popup_time.get(k, 0.0)
        if now - last < min_interval_sec:
            return
        self._last_popup_time[k] = now
        self.root.after(0, lambda t=title, m=message: messagebox.showinfo(t, m))

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True)
        self.tab_init = ttk.Frame(notebook)
        self.tab_waypoint = ttk.Frame(notebook)
        self.tab_task = ttk.Frame(notebook)
        self.tab_plan = ttk.Frame(notebook)
        self.tab_hand = ttk.Frame(notebook)
        self.tab_log = ttk.Frame(notebook)
        notebook.add(self.tab_init, text="初始化与环境")
        notebook.add(self.tab_waypoint, text="点位管理")
        notebook.add(self.tab_task, text="任务编辑")
        notebook.add(self.tab_plan, text="多任务编排")
        notebook.add(self.tab_hand, text="手动手控")
        notebook.add(self.tab_log, text="日志")
        self._build_init_tab()
        self._build_waypoint_tab()
        self._build_task_tab()
        self._build_plan_tab()
        self._build_hand_tab()
        self._build_log_tab()
        self._refresh_conflict_action_buttons()

    def _register_conflict_action_button(self, btn: ttk.Button) -> None:
        self._conflict_action_buttons.append(btn)

    def _refresh_conflict_action_buttons(self) -> None:
        disabled = bool(self.raw_hand_connected)
        for btn in self._conflict_action_buttons:
            if disabled:
                btn.state(["disabled"])
            else:
                btn.state(["!disabled"])

    def _refresh_conflict_action_buttons_async(self) -> None:
        self.root.after(0, self._refresh_conflict_action_buttons)

    @staticmethod
    def _format_ts(epoch: float) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))

    def _write_active_run_status(self, payload: dict[str, object]) -> None:
        try:
            self._active_run_status_file.parent.mkdir(parents=True, exist_ok=True)
            content = dict(payload)
            with self._pause_state_lock:
                content["pause_test"] = {
                    "enabled": self._pause_test_enabled,
                    "cancel_requested": self._pause_cancel_requested,
                    "waiting_context": self._pause_waiting_context,
                    "waiting_since": self._format_ts(self._pause_waiting_since) if self._pause_waiting_since > 0 else "",
                }
            content["updated_at"] = self._format_ts(time.time())
            tmp_path = self._active_run_status_file.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2, sort_keys=True)
            tmp_path.replace(self._active_run_status_file)
        except Exception as exc:  # noqa: BLE001
            self.log_control(f"写入运行状态文件失败: {exc}")

    def _refresh_pause_test_buttons(self) -> None:
        enabled = bool(self.pause_test_enabled_var.get())
        can_continue = False
        can_cancel = False
        waiting_context = ""
        cancel_requested = False
        waiting_since = 0.0
        with self._pause_state_lock:
            waiting_context = self._pause_waiting_context
            cancel_requested = self._pause_cancel_requested
            waiting_since = self._pause_waiting_since
            can_continue = enabled and bool(waiting_context)
            can_cancel = enabled and bool(self.running)
        if enabled:
            if waiting_context:
                wait_sec = max(0.0, time.time() - waiting_since)
                self.pause_test_status_var.set(f"暂停测试：已暂停在 `{waiting_context}`（{wait_sec:.1f}s）")
            elif cancel_requested:
                self.pause_test_status_var.set("暂停测试：已请求取消，等待当前步骤退出")
            else:
                self.pause_test_status_var.set("暂停测试：开启（每个 arm motion 前将暂停）")
        else:
            self.pause_test_status_var.set("暂停测试：关闭")
        if can_continue:
            self.btn_pause_test_continue.state(["!disabled"])
        else:
            self.btn_pause_test_continue.state(["disabled"])
        if can_cancel:
            self.btn_pause_test_cancel.state(["!disabled"])
        else:
            self.btn_pause_test_cancel.state(["disabled"])

    def _refresh_pause_test_buttons_async(self) -> None:
        self.root.after(0, self._refresh_pause_test_buttons)

    def on_pause_test_toggle(self) -> None:
        enabled = bool(self.pause_test_enabled_var.get())
        with self._pause_state_lock:
            self._pause_test_enabled = enabled
            if not enabled:
                self._pause_cancel_requested = False
                self._pause_waiting_context = ""
                self._pause_waiting_since = 0.0
                self._pause_continue_event.set()
        if enabled:
            self.log_control("暂停测试已开启：每个 arm motion 下发前需手动点击“继续下一步”。")
        else:
            self.log_control("暂停测试已关闭。")
        self._refresh_pause_test_buttons_async()

    def continue_pause_test(self) -> None:
        with self._pause_state_lock:
            if not self._pause_test_enabled:
                return
            waiting_context = self._pause_waiting_context
            self._pause_continue_event.set()
        if waiting_context:
            self.log_control(f"[暂停测试] 收到继续指令，放行：{waiting_context}")
        self._refresh_pause_test_buttons_async()

    def cancel_pause_test(self) -> None:
        with self._pause_state_lock:
            if not self.running:
                return
            self._pause_cancel_requested = True
            waiting_context = self._pause_waiting_context
            self._pause_continue_event.set()
        if waiting_context:
            self.log_control(f"[暂停测试] 收到取消指令，正在取消：{waiting_context}")
        else:
            self.log_control("[暂停测试] 收到取消指令，当前步骤完成后将停止后续动作。")
        self._refresh_pause_test_buttons_async()

    def wait_for_pause_test_gate(self, context: str) -> None:
        with self._pause_state_lock:
            if self._pause_cancel_requested:
                raise PauseTestCancelledError(f"测试已取消：{context}")
            if not self._pause_test_enabled:
                return
            self._pause_waiting_context = context
            self._pause_waiting_since = time.time()
            self._pause_continue_event.clear()
        self.log_control(f"[暂停测试] 已暂停：{context}。请点击“继续下一步”或“取消测试”。")
        self._refresh_pause_test_buttons_async()

        while True:
            self._pause_continue_event.wait(timeout=0.2)
            with self._pause_state_lock:
                cancel_requested = self._pause_cancel_requested
                enabled = self._pause_test_enabled
                if cancel_requested:
                    self._pause_waiting_context = ""
                    self._pause_waiting_since = 0.0
                    self._pause_continue_event.clear()
                    self._refresh_pause_test_buttons_async()
                    raise PauseTestCancelledError(f"测试已取消：{context}")
                if not enabled:
                    self._pause_waiting_context = ""
                    self._pause_waiting_since = 0.0
                    self._pause_continue_event.clear()
                    break
                if self._pause_continue_event.is_set():
                    self._pause_waiting_context = ""
                    self._pause_waiting_since = 0.0
                    self._pause_continue_event.clear()
                    break
        self.log_control(f"[暂停测试] 继续执行：{context}")
        self._refresh_pause_test_buttons_async()

    def _build_runtime_status_text(self) -> str:
        lines: list[str] = []
        lines.append(f"刷新时间: {self._format_ts(time.time())}")
        lines.append(f"状态文件: {self._active_run_status_file}")
        payload: dict[str, object] = {}
        try:
            if self._active_run_status_file.exists():
                with self._active_run_status_file.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    payload = raw
            else:
                payload = {"running": False, "note": "状态文件尚未生成（等待首次执行动作）"}
        except Exception as exc:  # noqa: BLE001
            payload = {"running": False, "note": f"读取状态文件失败: {exc}"}

        running = bool(payload.get("running", False))
        lines.append(f"running: {'YES' if running else 'NO'}")
        if running:
            lines.append(f"run_id: {payload.get('run_id', 'N/A')}")
            lines.append(f"action_name: {payload.get('action_name', 'N/A')}")
            lines.append(f"started_at: {payload.get('started_at', 'N/A')}")
        last_run = payload.get("last_run", {})
        if isinstance(last_run, dict) and last_run:
            lines.append("")
            lines.append("last_run:")
            lines.append(f"  run_id: {last_run.get('run_id', 'N/A')}")
            lines.append(f"  action_name: {last_run.get('action_name', 'N/A')}")
            lines.append(f"  status: {last_run.get('status', 'N/A')}")
            lines.append(f"  elapsed_sec: {last_run.get('elapsed_sec', 'N/A')}")
            lines.append(f"  finished_at: {last_run.get('finished_at', 'N/A')}")
            err = str(last_run.get("error", "")).strip()
            if err:
                lines.append(f"  error: {err}")
        note = str(payload.get("note", "")).strip()
        if note:
            lines.append("")
            lines.append(f"note: {note}")
        lines.append("")
        lines.append(f"pause_test: {self.pause_test_status_var.get()}")
        return "\n".join(lines)

    def _poll_runtime_status_panel(self) -> None:
        if hasattr(self, "runtime_status_text"):
            text = self._build_runtime_status_text()
            self.runtime_status_text.configure(state="normal")
            self.runtime_status_text.delete("1.0", "end")
            self.runtime_status_text.insert("end", text)
            self.runtime_status_text.configure(state="disabled")
        self.root.after(500, self._poll_runtime_status_panel)

    def _build_init_tab(self) -> None:
        frm = self.tab_init
        ttk.Label(frm, text="ROS setup").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.env_ros_var, width=80).grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(frm, text="SDK setup").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.env_sdk_var, width=80).grid(row=1, column=1, padx=4, pady=2)
        ttk.Label(frm, text="Franka setup").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.env_franka_var, width=80).grid(row=2, column=1, padx=4, pady=2)
        ttk.Button(frm, text="一键初始化", command=self.init_environment).grid(row=3, column=0, pady=6)
        ttk.Button(frm, text="停止机械臂启动进程", command=self.stop_franka_bringup).grid(row=3, column=1, pady=6, sticky="w")
        ttk.Button(frm, text="检测FCI/关节锁状态", command=self.check_fci_and_guide).grid(row=3, column=2, pady=6, sticky="w")
        ttk.Button(frm, text="检测手状态", command=self.check_raw_hand_status).grid(row=3, column=3, pady=6, sticky="w")

        cfg = ttk.LabelFrame(frm, text="运行参数")
        cfg.grid(row=4, column=0, columnspan=2, sticky="ew", padx=4, pady=6)
        ttk.Label(cfg, text="hand_backend").grid(row=0, column=0, sticky="w")
        ttk.Combobox(cfg, values=["python_sdk", "ros_service"], textvariable=self.hand_backend_var, width=20).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(cfg, text="hand_device").grid(row=0, column=2, sticky="w")
        ttk.Combobox(cfg, values=["zlgcan", "hcan", "rs485", "zlgcan_tcp"], textvariable=self.hand_device_var, width=20).grid(
            row=0, column=3, sticky="w"
        )
        ttk.Label(cfg, text="hand_side").grid(row=1, column=0, sticky="w")
        ttk.Combobox(cfg, values=["left", "right"], textvariable=self.hand_side_var, width=20).grid(row=1, column=1, sticky="w")
        ttk.Label(cfg, text="arm_action").grid(row=1, column=2, sticky="w")
        ttk.Entry(cfg, textvariable=self.arm_action_name_var, width=30).grid(row=1, column=3, sticky="w")
        ttk.Label(cfg, text="franka_robot_type").grid(row=2, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.franka_robot_type_var, width=20).grid(row=2, column=1, sticky="w")
        ttk.Label(cfg, text="franka_robot_ip").grid(row=2, column=2, sticky="w")
        ttk.Entry(cfg, textvariable=self.franka_robot_ip_var, width=30).grid(row=2, column=3, sticky="w")
        ttk.Label(cfg, text="arm_velocity_scale").grid(row=3, column=0, sticky="w")
        arm_scale_slider = tk.Scale(
            cfg,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            orient="horizontal",
            length=220,
            variable=self.arm_velocity_scale_var,
        )
        arm_scale_slider.grid(row=3, column=1, sticky="w")
        ttk.Label(cfg, textvariable=self.arm_velocity_scale_var, width=6).grid(row=3, column=2, sticky="w")
        ttk.Label(cfg, text="arm_motion_settle_sec").grid(row=4, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.arm_motion_settle_sec_var, width=20).grid(row=4, column=1, sticky="w")
        ttk.Label(cfg, text="home_hand_settle_sec").grid(row=5, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.home_hand_settle_sec_var, width=20).grid(row=5, column=1, sticky="w")
        ttk.Checkbutton(cfg, text="初始化后自动启动franka_bringup", variable=self.auto_start_franka_var).grid(
            row=6, column=0, columnspan=3, sticky="w"
        )

        pause_box = ttk.LabelFrame(frm, text="暂停测试（用于排查多任务串行冲突）")
        pause_box.grid(row=5, column=0, columnspan=4, sticky="ew", padx=4, pady=6)
        ttk.Checkbutton(
            pause_box,
            text="开启暂停测试（每个 arm motion 前暂停）",
            variable=self.pause_test_enabled_var,
            command=self.on_pause_test_toggle,
        ).pack(side="left", padx=4, pady=4)
        self.btn_pause_test_continue = ttk.Button(pause_box, text="继续下一步", command=self.continue_pause_test)
        self.btn_pause_test_continue.pack(side="left", padx=4)
        self.btn_pause_test_cancel = ttk.Button(pause_box, text="取消测试", command=self.cancel_pause_test)
        self.btn_pause_test_cancel.pack(side="left", padx=4)
        ttk.Label(pause_box, textvariable=self.pause_test_status_var).pack(side="left", padx=8)
        self._refresh_pause_test_buttons()

    def _build_waypoint_tab(self) -> None:
        left = ttk.Frame(self.tab_waypoint)
        left.pack(side="left", fill="y", padx=4, pady=4)
        right = ttk.Frame(self.tab_waypoint)
        right.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.waypoint_list = tk_listbox(left, 35, 20)
        self.waypoint_list.pack(fill="y")
        ttk.Button(left, text="刷新", command=self.refresh_waypoints).pack(fill="x")
        ttk.Button(left, text="导入点位", command=self.import_waypoint).pack(fill="x")
        ttk.Button(left, text="打开文件所在位置", command=lambda: open_path(self.waypoints_dir())).pack(fill="x")

        top = ttk.Frame(right)
        top.pack(fill="x")
        ttk.Label(top, text="点位名").pack(side="left")
        ttk.Entry(top, textvariable=self.waypoint_name_var, width=24).pack(side="left")
        ttk.Button(top, text="记录当前点位", command=self.record_waypoint).pack(side="left", padx=2)
        ttk.Button(top, text="重命名", command=self.rename_waypoint).pack(side="left", padx=2)
        ttk.Button(top, text="另存为", command=self.saveas_waypoint).pack(side="left", padx=2)
        ttk.Button(top, text="设为初始位置", command=self.set_home_pose).pack(side="left", padx=2)
        self.btn_move_to_waypoint = ttk.Button(top, text="移动到当前点位", command=self.move_to_selected_waypoint)
        self.btn_move_to_waypoint.pack(side="left", padx=2)
        self.btn_go_home = ttk.Button(top, text="回到初始位置", command=self.go_home_now)
        self.btn_go_home.pack(side="left", padx=2)
        ttk.Label(right, text="备注").pack(anchor="w")
        ttk.Entry(right, textvariable=self.task_note_var, width=60).pack(fill="x")
        self.waypoint_detail = Text(right, height=16)
        self.waypoint_detail.pack(fill="both", expand=True)
        self.waypoint_list.bind("<<ListboxSelect>>", lambda _: self.show_waypoint_detail())

    def _build_task_tab(self) -> None:
        mid = ttk.Frame(self.tab_task)
        right = ttk.Frame(self.tab_task)
        mid.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        right.pack(side="left", fill="y", padx=4, pady=4)

        top = ttk.Frame(mid)
        top.pack(fill="x")
        ttk.Label(top, text="当前任务文件").pack(side="left")
        ttk.Entry(top, textvariable=self.current_task_file_var, width=56).pack(side="left", padx=4)
        ttk.Button(top, text="新建任务", command=self.create_task).pack(side="left")
        ttk.Button(top, text="导入任务", command=self.import_task).pack(side="left")
        ttk.Button(top, text="打开task目录", command=lambda: open_path(self.tasks_dir())).pack(side="left")

        ttk.Label(mid, text="任务点位序列").pack(anchor="w")
        self.task_step_list = tk_listbox(mid, 60, 20)
        self.task_step_list.pack(fill="both", expand=True)
        row = ttk.Frame(mid)
        row.pack(fill="x")
        ttk.Button(row, text="添加点位到任务", command=self.add_waypoint_to_task).pack(side="left")
        ttk.Button(row, text="移除点位", command=self.remove_task_step).pack(side="left")
        ttk.Button(row, text="上移", command=lambda: self.move_task_step(-1)).pack(side="left")
        ttk.Button(row, text="下移", command=lambda: self.move_task_step(1)).pack(side="left")
        ttk.Button(row, text="保存任务", command=self.save_task).pack(side="left")
        self.btn_run_task = ttk.Button(row, text="执行该任务", command=self.run_task)
        self.btn_run_task.pack(side="left")
        self._register_conflict_action_button(self.btn_run_task)

        ttk.Label(right, text="步骤参数").pack(anchor="w")
        ttk.Label(right, text="停留(s)").pack(anchor="w")
        ttk.Entry(right, textvariable=self.task_hold_sec_var, width=8).pack(anchor="w")
        ttk.Checkbutton(right, text="手回位开关", variable=self.task_step_hand_reset_var).pack(anchor="w")
        ttk.Button(right, text="应用到选中步骤", command=self.apply_step_params).pack(fill="x")

    def _build_plan_tab(self) -> None:
        mid = ttk.Frame(self.tab_plan)
        right = ttk.Frame(self.tab_plan)
        mid.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        right.pack(side="left", fill="y", padx=4, pady=4)

        top = ttk.Frame(mid)
        top.pack(fill="x")
        ttk.Label(top, text="当前计划文件").pack(side="left")
        ttk.Entry(top, textvariable=self.current_plan_file_var, width=56).pack(side="left", padx=4)
        ttk.Button(top, text="新建计划", command=self.create_plan).pack(side="left")
        ttk.Button(top, text="导入计划", command=self.import_plan).pack(side="left")
        ttk.Button(top, text="打开multitask目录", command=lambda: open_path(self.plans_dir())).pack(side="left")
        ttk.Label(mid, text="计划任务序列").pack(anchor="w")
        self.plan_task_list = tk_listbox(mid, 60, 20)
        self.plan_task_list.pack(fill="both", expand=True)

        btn = ttk.Frame(mid)
        btn.pack(fill="x")
        ttk.Button(btn, text="添加任务到计划", command=self.add_task_to_plan).pack(side="left")
        ttk.Button(btn, text="移除任务", command=self.remove_task_from_plan).pack(side="left")
        ttk.Button(btn, text="上移", command=lambda: self.move_plan_task(-1)).pack(side="left")
        ttk.Button(btn, text="下移", command=lambda: self.move_plan_task(1)).pack(side="left")
        ttk.Button(btn, text="保存计划", command=self.save_plan).pack(side="left")
        self.btn_run_plan = ttk.Button(btn, text="执行该计划", command=self.run_plan)
        self.btn_run_plan.pack(side="left")
        self._register_conflict_action_button(self.btn_run_plan)

        ttk.Label(right, text="计划名称").pack(anchor="w")
        self.plan_name_var = StringVar(value="plan_1")
        ttk.Entry(right, textvariable=self.plan_name_var, width=20).pack(anchor="w")
        ttk.Checkbutton(right, text="任务间回初始位", variable=self.plan_task_reset_var).pack(anchor="w")
        ttk.Checkbutton(right, text="计划结束回初始位", variable=self.plan_end_reset_var).pack(anchor="w")
        ttk.Button(right, text="从文件重载计划", command=self.load_plan).pack(fill="x")

    def _build_log_tab(self) -> None:
        log_tabs = ttk.Notebook(self.tab_log)
        log_tabs.pack(fill="both", expand=True, padx=4, pady=4)
        f1 = ttk.Frame(log_tabs)
        f2 = ttk.Frame(log_tabs)
        f3 = ttk.Frame(log_tabs)
        log_tabs.add(f1, text="控制日志")
        log_tabs.add(f2, text="机械臂日志")
        log_tabs.add(f3, text="手日志")
        self.log_text_control = Text(f1, height=28)
        self.log_text_arm = Text(f2, height=28)
        self.log_text_hand = Text(f3, height=28)
        self.log_text_control.pack(fill="both", expand=True)
        self.log_text_arm.pack(fill="both", expand=True)
        self.log_text_hand.pack(fill="both", expand=True)
        runtime_box = ttk.LabelFrame(self.tab_log, text="任务运行状态（内置 active motion 监控）")
        runtime_box.pack(fill="x", padx=4, pady=(0, 4))
        self.runtime_status_text = Text(runtime_box, height=10)
        self.runtime_status_text.pack(fill="x", expand=False)
        self.runtime_status_text.configure(state="disabled")

    def _build_hand_tab(self) -> None:
        frm = self.tab_hand
        top = ttk.Frame(frm)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="手控模式: 0-4096 位置值, 滑条即时发送").pack(side="left")
        ttk.Button(top, text="初始化手", command=self.init_raw_hand).pack(side="left", padx=8)
        ttk.Button(top, text="同步当前位置到滑条", command=self.sync_hand_positions).pack(side="left", padx=4)
        ttk.Button(top, text="关闭手控连接", command=self.close_raw_hand).pack(side="left", padx=4)
        ttk.Checkbutton(top, text="实时监控(0.5s)", variable=self.hand_monitoring_var, command=self.toggle_hand_monitor).pack(
            side="left", padx=8
        )

        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True, padx=8, pady=6)
        sliders = ttk.Frame(body)
        sliders.pack(side="left", fill="both", expand=True)
        for i in range(10):
            row = ttk.Frame(sliders)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"J{i+1}", width=5).pack(side="left")
            ttk.Label(row, text=self.hand_joint_notes[i], width=14).pack(side="left")
            scale = tk.Scale(
                row,
                from_=0,
                to=4096,
                resolution=1,
                orient="horizontal",
                length=420,
                variable=self.hand_pos_vars[i],
                command=lambda _v, idx=i: self.on_hand_pos_slider_change(idx),
            )
            scale.pack(side="left", padx=6)
            ttk.Label(row, textvariable=self.hand_pos_vars[i], width=8).pack(side="left")

        monitor_box = ttk.LabelFrame(body, text="手关节实时监控")
        monitor_box.pack(side="left", fill="both", expand=True, padx=8)
        self.hand_monitor_text = Text(monitor_box, height=24)
        self.hand_monitor_text.pack(fill="both", expand=True)
        self.hand_monitoring_var.set(False)

    def _refresh_all_lists(self) -> None:
        self.refresh_waypoints()
        self.refresh_tasks()
        self.refresh_plans_to_list()

    def _poll_logs(self) -> None:
        while True:
            try:
                channel, line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            target = self.log_text_control
            if channel == "arm":
                target = self.log_text_arm
            elif channel == "hand":
                target = self.log_text_hand
            target.insert("end", line + "\n")
            target.see("end")
        self.root.after(200, self._poll_logs)

    def init_environment(self) -> None:
        cmds = [
            self.env_ros_var.get().strip(),
            self.env_sdk_var.get().strip(),
            self.env_franka_var.get().strip(),
        ]
        script = " && ".join([f"source '{c}'" for c in cmds if c])
        script += " && env -0"
        proc = subprocess.run(["bash", "-lc", script], capture_output=True)
        if proc.returncode != 0:
            self.log(f"初始化失败:\n{proc.stderr.decode(errors='ignore')}")
            messagebox.showerror("初始化失败", proc.stderr.decode(errors="ignore"))
            self.env_initialized = False
            return
        for item in proc.stdout.split(b"\0"):
            if not item:
                continue
            k, _, v = item.partition(b"=")
            os.environ[k.decode(errors="ignore")] = v.decode(errors="ignore")
        self.log("初始化成功，环境变量已载入。")
        self.env_initialized = True
        self.popup_info("初始化成功", "环境变量已载入，可继续执行检测或任务。", key="env_init_ok")
        if self.auto_start_franka_var.get():
            self.start_franka_bringup()

    def _compose_source_prefix(self) -> str:
        cmds = [
            self.env_ros_var.get().strip(),
            self.env_sdk_var.get().strip(),
            self.env_franka_var.get().strip(),
        ]
        return " && ".join([f"source '{c}'" for c in cmds if c])

    def start_franka_bringup(self) -> None:
        robot_ip = self.franka_robot_ip_var.get().strip()
        robot_type = self.franka_robot_type_var.get().strip() or "fr3"
        if not robot_ip:
            self.log_arm("未自动启动franka_bringup：franka_robot_ip 为空。")
            return
        if self.franka_launch_proc is not None and self.franka_launch_proc.poll() is None:
            self.log_arm("franka_bringup 已在运行，跳过重复启动。")
            return

        script = (
            f"{self._compose_source_prefix()} && "
            f"ros2 launch franka_bringup franka.launch.py "
            f"robot_type:={robot_type} robot_ip:={robot_ip}"
        )
        self.log_arm(f"启动机械臂: robot_type={robot_type}, robot_ip={robot_ip}")
        self.franka_launch_proc = subprocess.Popen(
            ["bash", "-lc", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )

        def stream_logs() -> None:
            assert self.franka_launch_proc is not None and self.franka_launch_proc.stdout is not None
            for line in self.franka_launch_proc.stdout:
                msg = line.strip()
                if msg:
                    self.log_arm(msg)

        threading.Thread(target=stream_logs, daemon=True).start()

    def stop_franka_bringup(self) -> None:
        if self.franka_launch_proc is None or self.franka_launch_proc.poll() is not None:
            self.log_arm("franka_bringup 未在运行。")
            return
        self.franka_launch_proc.terminate()
        self.log_arm("已发送终止信号到 franka_bringup 进程。")
        self.popup_info("操作成功", "已发送停止信号到 franka_bringup 进程。", key="stop_franka_ok")

    def check_fci_and_guide(self) -> None:
        if not self.env_initialized:
            messagebox.showwarning("提示", "请先点击“一键初始化”，再执行 FCI/关节锁状态检测。")
            self.log_control("FCI检测已拦截：未先执行一键初始化。")
            return
        action = self.arm_action_name_var.get().strip()
        prefix = self._compose_source_prefix()
        script = (
            f"{prefix} && "
            "echo '--- action list ---' && ros2 action list || true; "
            "echo '--- topics list ---' && ros2 topic list || true"
        )
        proc = subprocess.run(["bash", "-lc", script], capture_output=True, text=True, env=os.environ.copy())
        out = proc.stdout or ""
        self.log_control("执行 FCI/关节锁状态检测")
        if out:
            self.log_control(out.strip())
        ready = action in out
        if ready:
            messagebox.showinfo("检测结果", f"检测到动作服务 `{action}` 在线。\n可尝试执行任务。")
        else:
            messagebox.showwarning(
                "检测结果",
                "未检测到机械臂动作服务在线。\n"
                "请在 Desk 上确认：\n"
                "1) 解除关节锁（Unlock Joints）\n"
                "2) 切到编程模式并 Activate FCI\n"
                "3) 确认机器人网络/控制权正常\n"
                "然后重新点击“一键初始化”或手动启动 bringup。",
            )

    def refresh_waypoints(self) -> None:
        refill_listbox(self.waypoint_list, [p.stem for p in sorted(self.waypoints_dir().glob("*.yaml"))])

    def show_waypoint_detail(self) -> None:
        name = selected_text(self.waypoint_list)
        if not name:
            return
        raw = read_yaml(self.waypoints_dir() / f"{name}.yaml")
        self.waypoint_detail.delete("1.0", "end")
        self.waypoint_detail.insert("end", yaml_pretty(raw))

    def record_waypoint(self) -> None:
        if not self.raw_hand_connected and not self.ensure_hand_ready_or_warn("记录当前点位"):
            return
        save_path = choose_save_file_native(
            self.waypoints_dir(),
            [("YAML", "*.yaml")],
            default_name=f"{self.waypoint_name_var.get().strip() or 'waypoint_1'}.yaml",
        )
        if not save_path:
            return
        name = Path(save_path).stem
        self._run_async(lambda: self._record_waypoint_worker(name), action_name=f"record_waypoint:{name}")

    def _record_waypoint_worker(self, name: str) -> None:
        note = self.task_note_var.get().strip()
        path = self.executor.record_waypoint(name, note)
        self.log(f"点位已保存: {path}")
        self.root.after(0, self.refresh_waypoints)
        self.popup_info("点位保存成功", f"点位已保存:\n{path}", key=f"waypoint_saved_{name}")

    def rename_waypoint(self) -> None:
        old = selected_text(self.waypoint_list)
        if not old:
            return
        target = choose_save_file_native(
            self.waypoints_dir(),
            [("YAML", "*.yaml")],
            default_name=f"{old}.yaml",
        )
        if not target:
            return
        new = Path(target).stem
        src = self.waypoints_dir() / f"{old}.yaml"
        dst = self.waypoints_dir() / f"{new}.yaml"
        src.rename(dst)
        self.log(f"点位重命名: {old} -> {new}")
        self.refresh_waypoints()
        self.popup_info("重命名成功", f"点位已重命名:\n{old} -> {new}", key=f"rename_wp_{old}_{new}")

    def saveas_waypoint(self) -> None:
        old = selected_text(self.waypoint_list)
        if not old:
            return
        target = choose_save_file_native(
            self.waypoints_dir(),
            [("YAML", "*.yaml")],
            default_name=f"{old}_copy.yaml",
        )
        if not target:
            return
        new = Path(target).stem
        shutil.copy2(self.waypoints_dir() / f"{old}.yaml", self.waypoints_dir() / f"{new}.yaml")
        self.log(f"点位另存为: {old} -> {new}")
        self.refresh_waypoints()
        self.popup_info("另存为成功", f"点位已另存为:\n{new}.yaml", key=f"saveas_wp_{old}_{new}")

    def import_waypoint(self) -> None:
        files = choose_files_native(self.waypoints_dir(), [("YAML", "*.yaml")])
        imported = 0
        skipped = 0
        for f in files:
            src = Path(f).resolve()
            dst = (self.waypoints_dir() / Path(f).name).resolve()
            if src == dst:
                skipped += 1
                continue
            shutil.copy2(src, dst)
            imported += 1
        if files:
            self.log(f"导入点位完成: 新增{imported}个, 跳过{skipped}个(同路径)")
            self.refresh_waypoints()
            self.popup_info("导入完成", f"点位导入完成：新增 {imported} 个，跳过 {skipped} 个。", key="import_waypoint_ok")

    def set_home_pose(self) -> None:
        if not self.raw_hand_connected and not self.ensure_hand_ready_or_warn("设为初始位置"):
            return
        self.log("开始设置初始位置...")
        self._run_async(self._set_home_worker, action_name="set_home_pose")

    def _set_home_worker(self) -> None:
        path = self.executor.set_home_from_current()
        self.log(f"初始位置已保存: {path}")
        self.root.after(0, lambda p=str(path): messagebox.showinfo("设置成功", f"初始位置保存成功:\n{p}"))

    def move_to_selected_waypoint(self) -> None:
        name = selected_text(self.waypoint_list)
        if not name:
            messagebox.showwarning("提示", "请先选择一个点位")
            return
        if not self.raw_hand_connected and not self.ensure_hand_ready_or_warn("移动到当前点位"):
            return
        self._run_async(
            lambda: self.executor.move_to_waypoint(name),
            success_title="执行完成",
            success_message=f"已移动到点位：{name}",
            success_key=f"move_wp_ok_{name}",
            action_name=f"move_to_waypoint:{name}",
        )

    def go_home_now(self) -> None:
        if not self.raw_hand_connected and not self.ensure_hand_ready_or_warn("回到初始位置"):
            return
        self._run_async(
            self.executor.go_home_now,
            success_title="执行完成",
            success_message="机械臂和手已回到初始位置。",
            success_key="go_home_ok",
            action_name="go_home_now",
        )

    def refresh_tasks(self) -> None:
        if self.current_task_file_var.get().strip():
            self.load_selected_task()

    def create_task(self) -> None:
        save_path = choose_save_file_native(
            self.tasks_dir(),
            [("YAML", "*.yaml")],
            default_name="task_1.yaml",
        )
        if not save_path:
            return
        name = Path(save_path).stem
        write_yaml(self.tasks_dir() / f"{name}.yaml", {"name": name, "steps": []})
        self.current_task_file_var.set(str((self.tasks_dir() / f"{name}.yaml").resolve()))
        self.log(f"任务已创建: {name}")
        self.load_selected_task()
        self.popup_info("创建成功", f"任务已创建：{name}", key=f"create_task_{name}")

    def import_task(self) -> None:
        files = choose_files_native(self.tasks_dir(), [("YAML", "*.yaml")])
        imported = 0
        skipped = 0
        first_loaded: Path | None = None
        for f in files:
            src = Path(f).resolve()
            dst = (self.tasks_dir() / Path(f).name).resolve()
            if src == dst:
                skipped += 1
            else:
                shutil.copy2(src, dst)
                imported += 1
            if first_loaded is None:
                first_loaded = dst
        if files:
            self.log(f"导入任务完成: 新增{imported}个, 跳过{skipped}个(同路径)")
            if first_loaded is not None:
                self.current_task_file_var.set(str(first_loaded))
            self.load_selected_task()
            self.popup_info("导入完成", f"任务导入完成：新增 {imported} 个，跳过 {skipped} 个。", key="import_task_ok")

    def load_selected_task(self) -> None:
        task_file = self.current_task_file_var.get().strip()
        if not task_file:
            return
        path = Path(task_file)
        if not path.exists():
            messagebox.showwarning("提示", f"任务文件不存在: {path}")
            return
        raw = read_yaml(path)
        labels = [f"{s['waypoint']} | hold={s.get('hold_sec', 3.0)} | reset={bool(s.get('hand_reset_enabled', True))}" for s in raw.get("steps", [])]
        refill_listbox(self.task_step_list, labels)

    def add_waypoint_to_task(self) -> None:
        task_file = self.current_task_file_var.get().strip()
        if not task_file:
            messagebox.showwarning("提示", "请先导入或新建任务文件")
            return
        picked_files = choose_files_native(self.waypoints_dir(), [("YAML", "*.yaml")])
        if not picked_files:
            return
        raw = read_yaml(Path(task_file))
        steps = raw.setdefault("steps", [])
        hold_sec = float(self.task_hold_sec_var.get())
        hand_reset_enabled = bool(self.task_step_hand_reset_var.get())
        for picked in picked_files:
            wp = Path(picked).stem
            steps.append(
                {"waypoint": wp, "hold_sec": hold_sec, "hand_reset_enabled": hand_reset_enabled}
            )
        write_yaml(Path(task_file), raw)
        self.load_selected_task()
        self.popup_info("添加成功", f"已添加 {len(picked_files)} 个点位到任务。", key="add_waypoints_to_task_ok")

    def remove_task_step(self) -> None:
        task_file = self.current_task_file_var.get().strip()
        idx = self.task_step_list.curselection()
        if not task_file or not idx:
            return
        raw = read_yaml(Path(task_file))
        raw["steps"].pop(idx[0])
        write_yaml(Path(task_file), raw)
        self.load_selected_task()

    def move_task_step(self, delta: int) -> None:
        task_file = self.current_task_file_var.get().strip()
        idxs = self.task_step_list.curselection()
        if not task_file or not idxs:
            return
        i = idxs[0]
        raw = read_yaml(Path(task_file))
        steps = raw.get("steps", [])
        j = i + delta
        if j < 0 or j >= len(steps):
            return
        steps[i], steps[j] = steps[j], steps[i]
        write_yaml(Path(task_file), raw)
        self.load_selected_task()
        self.task_step_list.selection_set(j)

    def apply_step_params(self) -> None:
        task_file = self.current_task_file_var.get().strip()
        idxs = self.task_step_list.curselection()
        if not task_file or not idxs:
            return
        raw = read_yaml(Path(task_file))
        i = idxs[0]
        raw["steps"][i]["hold_sec"] = float(self.task_hold_sec_var.get())
        raw["steps"][i]["hand_reset_enabled"] = bool(self.task_step_hand_reset_var.get())
        write_yaml(Path(task_file), raw)
        self.load_selected_task()

    def save_task(self) -> None:
        task_file = self.current_task_file_var.get().strip()
        if task_file:
            self.log(f"任务已保存: {task_file}")
            self.popup_info("保存成功", f"任务已保存：\n{task_file}", key=f"save_task_{task_file}")

    def run_task(self) -> None:
        task_file = self.current_task_file_var.get().strip()
        if not task_file:
            messagebox.showwarning("提示", "请先导入或新建任务文件")
            return
        if self.raw_hand_connected:
            messagebox.showwarning(
                "提示",
                "当前已启用手动手控(0-4096)连接。请先关闭手动手控连接后再执行任务，避免CAN总线冲突。",
            )
            return
        if not self.ensure_hand_ready_or_warn("执行任务"):
            return
        task_name = Path(task_file).stem
        self._run_async(
            lambda: self.executor.execute_task(task_name),
            success_title="任务执行完成",
            success_message=f"任务 `{task_name}` 已执行完成。",
            success_key=f"run_task_ok_{task_name}",
            action_name=f"run_task:{task_name}",
        )

    def create_plan(self) -> None:
        save_path = choose_save_file_native(
            self.plans_dir(),
            [("YAML", "*.yaml")],
            default_name=f"{self.plan_name_var.get().strip() or 'plan_1'}.yaml",
        )
        if not save_path:
            return
        name = Path(save_path).stem
        write_yaml(self.plans_dir() / f"{name}.yaml", {"name": name, "tasks": [], "task_reset_enabled": True, "end_reset_enabled": True})
        self.current_plan_file_var.set(str((self.plans_dir() / f"{name}.yaml").resolve()))
        self.log(f"计划已创建: {name}")
        self.load_plan()
        self.popup_info("创建成功", f"计划已创建：{name}", key=f"create_plan_{name}")

    def import_plan(self) -> None:
        files = choose_files_native(self.plans_dir(), [("YAML", "*.yaml")])
        imported = 0
        skipped = 0
        first_loaded: Path | None = None
        for f in files:
            src = Path(f).resolve()
            dst = (self.plans_dir() / Path(f).name).resolve()
            if src == dst:
                skipped += 1
            else:
                shutil.copy2(src, dst)
                imported += 1
            if first_loaded is None:
                first_loaded = dst
        if files:
            self.log(f"导入计划完成: 新增{imported}个, 跳过{skipped}个(同路径)")
            if first_loaded is not None:
                self.current_plan_file_var.set(str(first_loaded))
            self.load_plan()
            self.popup_info("导入完成", f"计划导入完成：新增 {imported} 个，跳过 {skipped} 个。", key="import_plan_ok")

    def refresh_plans_to_list(self) -> None:
        if self.current_plan_file_var.get().strip():
            self.load_plan()

    def load_plan(self) -> None:
        plan_file = self.current_plan_file_var.get().strip()
        if not plan_file:
            return
        path = Path(plan_file)
        if not path.exists():
            refill_listbox(self.plan_task_list, [])
            return
        raw = read_yaml(path)
        self.plan_name_var.set(str(raw.get("name", path.stem)))
        self.plan_task_reset_var.set(bool(raw.get("task_reset_enabled", True)))
        self.plan_end_reset_var.set(bool(raw.get("end_reset_enabled", True)))
        refill_listbox(self.plan_task_list, [str(v) for v in raw.get("tasks", [])])

    def add_task_to_plan(self) -> None:
        plan_file = self.current_plan_file_var.get().strip()
        if not plan_file:
            messagebox.showwarning("提示", "请先导入或新建计划文件")
            return
        picked_files = choose_files_native(self.tasks_dir(), [("YAML", "*.yaml")])
        if not picked_files:
            return
        raw = read_yaml(Path(plan_file))
        tasks = raw.setdefault("tasks", [])
        for picked in picked_files:
            tasks.append(Path(picked).stem)
        write_yaml(Path(plan_file), raw)
        self.load_plan()
        self.popup_info("添加成功", f"已添加 {len(picked_files)} 个任务到计划。", key="add_tasks_to_plan_ok")

    def remove_task_from_plan(self) -> None:
        plan_file = self.current_plan_file_var.get().strip()
        idxs = self.plan_task_list.curselection()
        if not plan_file or not idxs:
            return
        raw = read_yaml(Path(plan_file))
        raw["tasks"].pop(idxs[0])
        write_yaml(Path(plan_file), raw)
        self.load_plan()

    def move_plan_task(self, delta: int) -> None:
        plan_file = self.current_plan_file_var.get().strip()
        idxs = self.plan_task_list.curselection()
        if not plan_file or not idxs:
            return
        i = idxs[0]
        raw = read_yaml(Path(plan_file))
        tasks = raw.get("tasks", [])
        j = i + delta
        if j < 0 or j >= len(tasks):
            return
        tasks[i], tasks[j] = tasks[j], tasks[i]
        write_yaml(Path(plan_file), raw)
        self.load_plan()
        self.plan_task_list.selection_set(j)

    def save_plan(self, popup: bool = True) -> None:
        plan_file = self.current_plan_file_var.get().strip()
        if not plan_file:
            return
        path = Path(plan_file)
        if not path.exists():
            return
        raw = read_yaml(path)
        raw["name"] = self.plan_name_var.get().strip() or path.stem
        raw["task_reset_enabled"] = bool(self.plan_task_reset_var.get())
        raw["end_reset_enabled"] = bool(self.plan_end_reset_var.get())
        write_yaml(path, raw)
        self.log(f"计划已保存: {path}")
        if popup:
            self.popup_info("保存成功", f"计划已保存：\n{path}", key=f"save_plan_{path}")

    def run_plan(self) -> None:
        plan_file = self.current_plan_file_var.get().strip()
        if not plan_file:
            messagebox.showwarning("提示", "请先导入或新建计划文件")
            return
        if self.raw_hand_connected:
            messagebox.showwarning(
                "提示",
                "当前已启用手动手控(0-4096)连接。请先关闭手动手控连接后再执行计划，避免CAN总线冲突。",
            )
            return
        if not self.ensure_hand_ready_or_warn("执行计划"):
            return
        self.save_plan(popup=False)
        plan_name = Path(plan_file).stem
        self._run_async(
            lambda: self.executor.execute_plan(plan_name),
            success_title="计划执行完成",
            success_message=f"计划 `{plan_name}` 已执行完成。",
            success_key=f"run_plan_ok_{plan_name}",
            action_name=f"run_plan:{plan_name}",
        )

    def _run_async(
        self,
        fn,
        success_title: str | None = None,
        success_message: str | None = None,
        success_key: str | None = None,
        action_name: str | None = None,
    ) -> None:
        label = (action_name or getattr(fn, "__name__", "anonymous")).strip() or "anonymous"
        started_epoch = time.time()
        with self._run_state_lock:
            if self.running:
                current_run_id = "N/A"
                current_action = "unknown"
                if isinstance(self._active_run, dict):
                    current_run_id = str(self._active_run.get("run_id", "N/A"))
                    current_action = str(self._active_run.get("action_name", "unknown"))
                self.log_control(f"拒绝新任务 `{label}`：已有任务运行中 run_id={current_run_id}, action={current_action}")
                messagebox.showwarning("提示", "已有任务在运行，请稍后")
                return
            self._run_seq += 1
            run_id = f"run-{int(started_epoch * 1000)}-{self._run_seq}"
            self.running = True
            with self._pause_state_lock:
                self._pause_cancel_requested = False
                self._pause_waiting_context = ""
                self._pause_waiting_since = 0.0
                self._pause_continue_event.clear()
            self._active_run = {
                "run_id": run_id,
                "action_name": label,
                "started_at": self._format_ts(started_epoch),
                "started_epoch": started_epoch,
            }
            self._write_active_run_status(
                {
                    "running": True,
                    "run_id": run_id,
                    "action_name": label,
                    "started_at": self._format_ts(started_epoch),
                    "started_epoch": started_epoch,
                }
            )
        self._refresh_pause_test_buttons_async()
        self.log_control(f"[RUN START] run_id={run_id}, action={label}")

        def worker() -> None:
            status = "succeeded"
            error_msg = ""
            try:
                fn()
                if success_title and success_message:
                    self.popup_info(success_title, success_message, key=success_key)
            except PauseTestCancelledError as exc:
                status = "cancelled"
                msg = str(exc)
                error_msg = msg
                self.log_control(msg)
                self.popup_info("执行已取消", msg, key="exec_cancelled")
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                msg = str(exc)
                error_msg = msg
                self.log(f"ERROR: {msg}")
                self.popup_error("执行失败", msg, key="exec_failed")
            finally:
                finished_epoch = time.time()
                elapsed_sec = max(0.0, finished_epoch - started_epoch)
                with self._run_state_lock:
                    self.running = False
                    self._active_run = None
                    with self._pause_state_lock:
                        self._pause_cancel_requested = False
                        self._pause_waiting_context = ""
                        self._pause_waiting_since = 0.0
                        self._pause_continue_event.set()
                    self._write_active_run_status(
                        {
                            "running": False,
                            "last_run": {
                                "run_id": run_id,
                                "action_name": label,
                                "status": status,
                                "started_at": self._format_ts(started_epoch),
                                "finished_at": self._format_ts(finished_epoch),
                                "elapsed_sec": round(elapsed_sec, 3),
                                "error": error_msg,
                            },
                        }
                    )
                self._refresh_pause_test_buttons_async()
                self.log_control(
                    f"[RUN END] run_id={run_id}, action={label}, status={status}, elapsed={elapsed_sec:.2f}s"
                )

        threading.Thread(target=worker, daemon=True).start()

    def ensure_hand_ready_or_warn(self, action_name: str) -> bool:
        try:
            self.executor._ensure_hand_client()
            return True
        except Exception as exc:  # noqa: BLE001
            detail = (
                f"动作 `{action_name}` 前检测到手后端未就绪。\n\n"
                f"错误: {exc}\n\n"
                "请依次检查:\n"
                "1) 手是否上电，电源指示灯是否正常\n"
                "2) CAN/串口连接是否稳定（线缆、转接器）\n"
                "3) hand_device / hand_side 参数是否正确\n"
                "4) 是否有其它程序占用手总线（例如另一个GUI或节点）\n"
                "5) 若使用zlgcan，是否有设备权限与驱动初始化成功\n"
            )
            self.log_hand(detail.replace("\n", " | "))
            self.log_control(f"[手检查失败] {action_name}: {exc}")
            messagebox.showerror("手未就绪", detail)
            return False

    def init_raw_hand(self) -> None:
        self._run_async(self._init_raw_hand_worker, action_name="init_raw_hand")

    @staticmethod
    def _is_hand_send_failed(ret: object) -> bool:
        # 兼容不同SDK返回语义：
        # - 有些成功返回 True
        # - 有些成功返回 0 / None
        # 因此这里只拦截“明确失败”的值，避免误报。
        if ret is False:
            return True
        if isinstance(ret, (int, float)):
            return ret < 0
        if isinstance(ret, str):
            token = ret.strip().lower()
            if token in {"false", "fail", "failed", "error", "-1"}:
                return True
        return False

    @staticmethod
    def _validate_hand_feedback(vals: object, *, min_len: int = 10) -> list[float]:
        if not isinstance(vals, (list, tuple)):
            raise RuntimeError("手反馈类型异常：不是数组")
        if len(vals) < min_len:
            raise RuntimeError(f"手反馈长度异常：收到 {len(vals)}，期望至少 {min_len}")
        checked: list[float] = []
        for i, v in enumerate(vals[:min_len], start=1):
            if not isinstance(v, (int, float)):
                raise RuntimeError(f"手反馈值异常：J{i} 不是数值")
            fv = float(v)
            if not math.isfinite(fv):
                raise RuntimeError(f"手反馈值异常：J{i} 不是有限数值")
            checked.append(fv)
        return checked

    def check_raw_hand_status(self) -> None:
        self._run_async(
            self._check_raw_hand_status_worker,
            success_title="检测结果",
            success_message="手状态正常：通信可用，关节反馈有效。",
            success_key="check_raw_hand_ok",
            action_name="check_raw_hand_status",
        )

    def _check_raw_hand_status_worker(self) -> None:
        hand = self._ensure_raw_hand()
        # 避免调用 get_all_active_joint_angles()：手未上电时底层可能触发 C++ assert 导致进程退出。
        probe_pos = int(self.hand_pos_vars[0].get())
        ret = hand.set_joint_position(1, probe_pos)
        if self._is_hand_send_failed(ret):
            raise RuntimeError(
                "手状态异常：探测指令发送失败（可能未上电/CAN总线异常/设备被占用）"
            )
        self.log_hand(f"手状态检测成功: 探测发送返回={ret!r}")

    def _ensure_raw_hand(self):
        if self.raw_hand is not None:
            return self.raw_hand
        if AgibotHandO10 is None or EHandType is None:
            raise RuntimeError("omnihand_2025 模块不可用，无法使用原始0-4096手控")
        cfg = Path(self.raw_hand_cfg_path)
        if not cfg.exists():
            raise RuntimeError(
                f"手控配置文件不存在: {cfg}\n"
                "请确认 raw_hand_cfg_path 路径或安装包目录是否正确。"
            )
        hand_type = EHandType.LEFT if self.hand_side_var.get().strip().lower() == "left" else EHandType.RIGHT
        self.executor.reset_hand_client()
        self.raw_hand = AgibotHandO10.create_hand(cfg_path=self.raw_hand_cfg_path, hand_type=hand_type)
        self._refresh_conflict_action_buttons_async()
        return self.raw_hand

    def _get_raw_hand_solver(self):
        if OmniHand2025Solver is None:
            raise RuntimeError("OmniHand2025Solver 不可用，无法将0-4096目标值转换为关节弧度")
        is_left = self.hand_side_var.get().strip().lower() == "left"
        if self._raw_hand_solver is None or self._raw_hand_solver_is_left != is_left:
            self._raw_hand_solver = OmniHand2025Solver(hand_type=is_left)
            self._raw_hand_solver_is_left = is_left
        return self._raw_hand_solver

    def _get_raw_hand_target_angles_from_sliders(self) -> list[float]:
        target_positions = [int(v.get()) for v in self.hand_pos_vars[:10]]
        solver = self._get_raw_hand_solver()
        try:
            target_angles = solver.actuator_input_to_active_joint_pos(target_positions)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"手目标值转换失败: {exc}") from exc
        checked = self._validate_hand_feedback(target_angles, min_len=10)
        self.log_hand(f"点位记录使用手目标角度: actuator={target_positions} -> rad={checked[:3]} ...")
        return checked

    def _init_raw_hand_worker(self) -> None:
        try:
            hand = self._ensure_raw_hand()
            init_positions = [1990, 201, 3998, 409, 4096, 4096, 2048, 4096, 2038, 4096]
            send_results: list[object] = []
            for i, pos in enumerate(init_positions):
                send_results.append(hand.set_joint_position(i + 1, int(pos)))
            # 部分底层SDK在未上电时仅打印CAN错误而不抛异常，这里主动校验返回值和回读状态。
            if any(self._is_hand_send_failed(res) for res in send_results):
                raise RuntimeError("下发初始化位置失败：检测到关节命令发送返回失败（可能未上电或总线异常）")
            feedback = hand.get_all_active_joint_angles()
            self._validate_hand_feedback(feedback, min_len=10)
            self.root.after(0, lambda: [self.hand_pos_vars[i].set(init_positions[i]) for i in range(10)])
            self.raw_hand_connected = True
            self.log_hand("手初始化完成(0-4096模式)")
            self.popup_info("手初始化成功", "手初始化完成（0-4096模式）。", key="raw_hand_init_ok")
        except Exception as exc:  # noqa: BLE001
            msg = (
                f"手初始化失败: {exc}\n\n"
                "建议检查:\n"
                "1) 手已上电且线缆连接正常\n"
                "2) CAN设备驱动与权限正常\n"
                "3) 配置文件路径(raw_hand_cfg_path)正确\n"
                "4) 当前没有其它程序占用手设备\n"
            )
            self.log_hand(msg.replace("\n", " | "))
            self.popup_error("手初始化失败", msg, key="hand_init_failed")
            raise RuntimeError(msg) from exc

    def _release_raw_hand(self) -> None:
        if self.raw_hand is None:
            return
        try:
            if hasattr(self.raw_hand, "close"):
                self.raw_hand.close()
        except Exception as exc:  # noqa: BLE001
            self.log_hand(f"释放手控连接失败: {exc}")
        self.raw_hand = None
        self.raw_hand_connected = False
        self.executor.reset_hand_client()
        self._refresh_conflict_action_buttons_async()

    def close_raw_hand(self) -> None:
        self.hand_monitoring_var.set(False)
        self._release_raw_hand()
        self.log_hand("手控连接已关闭")
        self.popup_info("操作成功", "手控连接已关闭。", key="close_raw_hand_ok")

    def toggle_hand_monitor(self) -> None:
        if self.hand_monitoring_var.get():
            self.log_hand("手关节实时监控已开启")
            self._schedule_hand_monitor()
        else:
            self.log_hand("手关节实时监控已关闭")

    def _schedule_hand_monitor(self) -> None:
        if not self.hand_monitoring_var.get():
            return
        if self.running:
            self.root.after(500, self._schedule_hand_monitor)
            return
        def worker() -> None:
            try:
                hand = self._ensure_raw_hand()
                vals = hand.get_all_active_joint_angles()
                ts = time.strftime("%H:%M:%S")
                lines = [f"[{ts}] 原始弧度: {vals[:10]}"]
                for i, rad in enumerate(vals[:10], start=1):
                    deg = float(rad) * 180.0 / 3.1415926535
                    lines.append(f"J{i:02d} {self.hand_joint_notes[i-1]} | rad={rad:.6f} | deg={deg:.3f}")
                text = "\n".join(lines) + "\n\n"
                self.root.after(0, lambda: self._append_hand_monitor(text))
            except Exception as exc:  # noqa: BLE001
                msg = f"手监控读取失败: {exc}"
                self.log_hand(msg)
                self.popup_error("手监控失败", msg, key="hand_monitor_failed", min_interval_sec=5.0)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(500, self._schedule_hand_monitor)

    def _append_hand_monitor(self, text: str) -> None:
        if hasattr(self, "hand_monitor_text"):
            self.hand_monitor_text.insert("end", text)
            self.hand_monitor_text.see("end")

    def sync_hand_positions(self) -> None:
        if not self.raw_hand_connected:
            messagebox.showwarning("提示", "请先点击“初始化手”，建立手控连接后再同步。")
            return
        self._run_async(
            self._sync_hand_positions_worker,
            success_title="同步成功",
            success_message="已将滑条同步为当前手关节位置。",
            success_key="sync_hand_positions_ok",
            action_name="sync_hand_positions",
        )

    def _sync_hand_positions_worker(self) -> None:
        hand = self._ensure_raw_hand()
        positions = hand.get_all_joint_positions()
        if not isinstance(positions, (list, tuple)) or len(positions) < 10:
            raise RuntimeError(
                f"读取关节位置失败: 期望至少10个位置，实际 {len(positions) if isinstance(positions, (list, tuple)) else 'N/A'}"
            )
        vals = [max(0, min(4096, int(v))) for v in positions[:10]]

        def apply_vals() -> None:
            self._hand_updating_from_device = True
            try:
                for i, v in enumerate(vals):
                    self.hand_pos_vars[i].set(v)
            finally:
                self._hand_updating_from_device = False

        self.root.after(0, apply_vals)
        self.log_hand(f"已同步滑条到当前位置: {vals}")

    def on_hand_pos_slider_change(self, idx: int) -> None:
        if self._hand_updating_from_device:
            return
        if not self.raw_hand_connected or self.raw_hand is None:
            return
        try:
            hand = self.raw_hand
            pos = int(self.hand_pos_vars[idx].get())
            ret = hand.set_joint_position(idx + 1, pos)
            if self._is_hand_send_failed(ret):
                raise RuntimeError(f"底层返回失败值: {ret!r}")
        except Exception as exc:  # noqa: BLE001
            msg = f"关节J{idx+1}设置失败: {exc}"
            self.log_hand(msg)
            self.popup_error("手关节设置失败", msg, key=f"hand_set_j{idx+1}", min_interval_sec=1.0)


def refill_listbox(lb, values: list[str]) -> None:
    lb.delete(0, "end")
    for v in values:
        lb.insert("end", v)


def selected_text(lb) -> str:
    idx = lb.curselection()
    if not idx:
        return ""
    return str(lb.get(idx[0]))


def yaml_pretty(data: dict) -> str:
    lines: list[str] = []
    for k, v in data.items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def tk_listbox(parent, width: int, height: int):
    from tkinter import Listbox

    return Listbox(parent, width=width, height=height)


def open_path(path: Path) -> None:
    subprocess.Popen(["xdg-open", str(path)])


def _zenity_filter(filetypes: list[tuple[str, str]]) -> str:
    patterns: list[str] = []
    for _, pattern in filetypes:
        patterns.append(pattern)
    if not patterns:
        patterns = ["*"]
    return " ".join(patterns)


def choose_file_native(initialdir: Path, filetypes: list[tuple[str, str]]) -> str:
    if shutil.which("zenity"):
        cmd = [
            "zenity",
            "--file-selection",
            "--filename",
            str(initialdir) + "/",
            "--file-filter",
            _zenity_filter(filetypes),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.strip()
        return ""
    return filedialog.askopenfilename(initialdir=str(initialdir), filetypes=filetypes)


def choose_files_native(initialdir: Path, filetypes: list[tuple[str, str]]) -> list[str]:
    if shutil.which("zenity"):
        cmd = [
            "zenity",
            "--file-selection",
            "--multiple",
            "--separator=|",
            "--filename",
            str(initialdir) + "/",
            "--file-filter",
            _zenity_filter(filetypes),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return [v for v in res.stdout.strip().split("|") if v]
        return []
    return list(filedialog.askopenfilenames(initialdir=str(initialdir), filetypes=filetypes))


def choose_save_file_native(initialdir: Path, filetypes: list[tuple[str, str]], default_name: str) -> str:
    if shutil.which("zenity"):
        cmd = [
            "zenity",
            "--file-selection",
            "--save",
            "--confirm-overwrite",
            "--filename",
            str((initialdir / default_name).resolve()),
            "--file-filter",
            _zenity_filter(filetypes),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            path = res.stdout.strip()
            if not path.endswith(".yaml"):
                path += ".yaml"
            return path
        return ""
    path = filedialog.asksaveasfilename(
        initialdir=str(initialdir),
        initialfile=default_name,
        defaultextension=".yaml",
        filetypes=filetypes,
    )
    return str(path or "")


def main() -> None:
    root = Tk()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{int(sw*0.92)}x{int(sh*0.9)}+20+20")
    root.minsize(1200, 760)
    try:
        root.state("zoomed")
    except Exception:  # noqa: BLE001
        pass
    app = MainApp(root)
    app.log("GUI 已启动")
    root.mainloop()


if __name__ == "__main__":
    main()
