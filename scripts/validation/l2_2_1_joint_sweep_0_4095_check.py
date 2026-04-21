#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# 控制与映射：各关节电机位置在 0~4095（O10）全行程慢扫，连续读取位置/速度/电流，
# 检测异常跳变、越界、以及与指令方向相反的运动。

import argparse
import csv
import atexit
import math
import os
import time

from omnihand import HandType, OmniHand2025


def _connection_hint(args) -> tuple[str, str]:
    """返回 (链路中文说明, 参数摘要)。"""
    d = args.device
    if d == "zlgcan":
        return (
            "CANFD（ZLG USB CANFD）",
            f"hand_device_id={args.hand_device_id}, canfd_device_id={args.canfd_device_id}, "
            f"canfd_channel_id={args.canfd_channel_id}",
        )
    if d == "hcan":
        return (
            "CANFD（HCAN USB CANFD）",
            f"hand_device_id={args.hand_device_id}, canfd_device_id={args.canfd_device_id}, "
            f"canfd_channel_id={args.canfd_channel_id}",
        )
    if d == "rs485":
        return (
            "RS485",
            f"uart_port={args.uart_port}, baudrate={args.baudrate}, hand_device_id={args.hand_device_id}",
        )
    if d == "usb":
        return (
            "USB（CDC 串口直连 O10）",
            f"uart_port={args.uart_port}, baudrate={args.baudrate}, hand_device_id={args.hand_device_id}",
        )
    return (
        "SocketCAN（Linux CAN/CANFD）",
        f"can_interface={args.can_interface}, hand_device_id={args.hand_device_id}",
    )


def create_hand(args):
    ht = HandType.LEFT if args.hand.lower() == "left" else HandType.RIGHT
    if args.device == "zlgcan":
        return OmniHand2025.create_hand_by_zlgcan(
            ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
        )
    if args.device == "hcan":
        return OmniHand2025.create_hand_by_hcan(
            ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
        )
    if args.device == "rs485":
        return OmniHand2025.create_hand_by_rs485(
            ht, args.hand_device_id, args.uart_port, args.baudrate
        )
    if args.device == "usb":
        return OmniHand2025.create_hand_by_usb(
            ht, args.hand_device_id, args.uart_port, args.baudrate
        )
    return OmniHand2025.create_hand_socketcan(
        ht, args.hand_device_id, args.can_interface
    )


def connect_hand(args):
    """创建并 init，打印分链路成功/失败信息。"""
    label, detail = _connection_hint(args)
    print(f"[连接] 正在通过 {label} 连接 …  ({detail})")
    try:
        hand = create_hand(args)
    except Exception as e:
        print(f"[失败] {label}：创建手部对象时异常 — {e!r}")
        print("       请检查 SDK、驱动、udev、串口权限或 CAN 适配器是否被占用。")
        raise SystemExit(1) from e
    if not hand.init():
        print(f"[失败] {label}：init() 返回 False，通讯未建立。")
        print("       请检查：手部上电、线缆、hand_device_id、CAN 通道/波特率或串口设备名。")
        raise SystemExit(1)
    print(f"[成功] {label} 通讯正常，init 成功。")
    try:
        probe = hand.get_all_joint_positions()
        if probe and len(probe) == 10:
            print(f"[成功] 已读回 10 路电机位置，链路可收发数据。")
        else:
            print(f"[警告] init 成功但 get_all_joint_positions 返回异常（{probe!r}），请排查总线负载或超时。")
    except Exception as e:
        print(f"[警告] init 成功但首次读位置失败：{e!r}，后续步骤可能仍报错。")
    return hand


def _render_progress(progress: float) -> str:
    """渲染简单文本进度条（百分比）。"""
    progress = max(0.0, min(1.0, float(progress)))
    width = 30
    filled = int(round(width * progress))
    filled = max(0, min(width, filled))
    bar = "#" * filled + "-" * (width - filled)
    pct = progress * 100.0
    return f"[{bar}] {pct:6.2f}%"


def main():
    p = argparse.ArgumentParser(description="O10 关节 0~max_pos 慢扫 + 位置/速度/电流校验")
    p.add_argument(
        "--device",
        choices=["zlgcan", "hcan", "rs485", "usb", "socketcan"],
        default="zlgcan",
    )
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--uart-port", default="/dev/ttyACM0")
    p.add_argument("--baudrate", type=int, default=460800)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--can-interface", default="can0")
    p.add_argument("--max-pos", type=int, default=4095, help="O10 电机位置上限；O12 请改为 2000")
    p.add_argument("--step", type=int, default=32, help="每步位置增量（越小越慢）")
    p.add_argument(
        "--monitor-hz",
        type=float,
        default=10.0,
        help="实时刷新显示的频率（Hz；过高会刷屏）",
    )
    p.add_argument(
        "--csv-output",
        type=str,
        default="joint_sweep_log.csv",
        help="每一步写一行 CSV（写入到脚本同目录）",
    )
    p.add_argument(
        "--mode",
        choices=["all", "single"],
        default="all",
        help="all: 十路同步同值扫掠；single: 仅 --joint-index 指定的一路",
    )
    p.add_argument("--joint-index", type=int, default=1, help="single 模式下电机索引 1..10")
    args = p.parse_args()

    max_pos = max(1, min(4095, args.max_pos))
    step = max(1, args.step)

    hand = connect_hand(args)

    hand.set_request_interval(2)
    time.sleep(0.3)

    # 编码器语义：4095=张开(OPEN)，0=闭合(CLOSE)
    open_positions = [max_pos] * 10
    close_positions = [0] * 10

    def _reset_to_open():
        try:
            hand.set_all_joint_positions(open_positions)
            # 给设备一些时间稳定到 OPEN（4095）
            time.sleep(0.2)
        except Exception:
            pass

    # 保底：异常/中断退出时也尽量回到 0
    atexit.register(_reset_to_open)

    # 扫描开始前先回到 OPEN=4095，避免 CSV 起始 actual 不符合预期
    try:
        hand.set_all_joint_positions(open_positions)
        time.sleep(0.5)
    except Exception:
        pass

    # 估算总步数：0->max 与 max->0 各约 ceil(max_pos/step) 步（进度条用于“近似”）。
    steps_up = int(math.ceil(max_pos / float(step)))
    total_steps = max(1, steps_up * 2)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, args.csv_output)

    monitor_hz = max(0.1, float(args.monitor_hz))
    monitor_interval = 1.0 / monitor_hz
    start_t = time.perf_counter()
    last_monitor_t = start_t - monitor_interval
    step_count = 0

    # CSV：每一步一行
    target_cols = [f"target_pos_{i}" for i in range(10)]
    actual_cols = [f"actual_pos_{i}" for i in range(10)]
    prev_cols = [f"prev_actual_pos_{i}" for i in range(10)]
    vel_cols = [f"vel_{i}" for i in range(10)]
    cur_cols = [f"current_{i}" for i in range(10)]
    header = ["t_sec", "phase", "step_count", "step_value", *target_cols, *actual_cols, *prev_cols, *vel_cols, *cur_cols]

    csv_f = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(csv_f)
    writer.writerow(header)

    def read_vel_cur():
        # O10：速度与电流可能会因设备状态/超时而失败，失败则填空值，便于后续分析。
        vel = [""] * 10
        cur = [""] * 10
        try:
            v = hand.get_all_joint_velocities()
            if v and len(v) == 10:
                vel = list(v)
        except Exception:
            pass
        try:
            c = hand.get_all_current_reports()
            if c and len(c) == 10:
                cur = list(c)
        except Exception:
            pass
        return vel, cur

    pos_prev = hand.get_all_joint_positions()
    if not pos_prev or len(pos_prev) != 10:
        pos_prev = list(open_positions)

    p_cmd = list(open_positions)
    violations = []

    if args.mode == "single":
        j = args.joint_index
        if j < 1 or j > 10:
            raise SystemExit("joint-index 须为 1..10")
        idx = j - 1
        # 单关节模式：其它 9 个关节始终保持在 OPEN=4095，目标关节执行 4095 -> 0 -> 4095
        p_cmd = list(open_positions)
        p_cmd[idx] = max_pos  # OPEN

        # CLOSE：4095 -> 0
        phase = "close"
        while True:
            hand.set_all_joint_positions(p_cmd)
            time.sleep(0.02)

            prev_actual = list(pos_prev)
            pos_now = hand.get_all_joint_positions()
            if not pos_now or len(pos_now) != 10:
                violations.append(("no_position", None))
                continue

            if pos_now[idx] < 0 or pos_now[idx] > max_pos:
                violations.append(("out_of_range", (idx, pos_now[idx])))

            if abs(pos_now[idx] - pos_prev[idx]) > 512:
                violations.append(("jump", (idx, pos_prev[idx], pos_now[idx])))

            vel, cur = read_vel_cur()

            t_sec = time.perf_counter() - start_t
            writer.writerow(
                [
                    f"{t_sec:.6f}",
                    phase,
                    step_count,
                    step,
                    *list(p_cmd),
                    *list(pos_now),
                    *prev_actual,
                    *list(vel),
                    *list(cur),
                ]
            )
            step_count += 1

            progress = step_count / float(total_steps)
            print(f"\r{_render_progress(progress)}", end="", flush=True)

            now_t = time.perf_counter()
            if now_t - last_monitor_t >= monitor_interval:
                print()
                print(
                    f"[实时] t={t_sec:.3f}s phase={phase} step_count={step_count}/{total_steps} step_value={step}"
                )
                print(f" target={list(p_cmd)}")
                print(f" actual={list(pos_now)}")
                print(f" prev_actual={list(prev_actual)}")
                print(f" vel={vel}")
                print(f" current={cur}")
                last_monitor_t = now_t

            pos_prev = list(pos_now)

            if p_cmd[idx] <= close_positions[idx]:
                break

            nxt = p_cmd[idx] - step
            if nxt < close_positions[idx]:
                nxt = close_positions[idx]
            p_cmd[idx] = nxt

        # OPEN：0 -> 4095
        phase = "open"
        p_cmd[idx] = close_positions[idx]  # 0
        while True:
            hand.set_all_joint_positions(p_cmd)
            time.sleep(0.02)

            prev_actual = list(pos_prev)
            pos_now = hand.get_all_joint_positions()
            if not pos_now or len(pos_now) != 10:
                violations.append(("no_position", None))
                continue

            if pos_now[idx] < 0 or pos_now[idx] > max_pos:
                violations.append(("out_of_range", (idx, pos_now[idx])))

            if abs(pos_now[idx] - pos_prev[idx]) > 512:
                violations.append(("jump", (idx, pos_prev[idx], pos_now[idx])))

            vel, cur = read_vel_cur()

            t_sec = time.perf_counter() - start_t
            writer.writerow(
                [
                    f"{t_sec:.6f}",
                    phase,
                    step_count,
                    step,
                    *list(p_cmd),
                    *list(pos_now),
                    *prev_actual,
                    *list(vel),
                    *list(cur),
                ]
            )
            step_count += 1

            progress = step_count / float(total_steps)
            print(f"\r{_render_progress(progress)}", end="", flush=True)

            now_t = time.perf_counter()
            if now_t - last_monitor_t >= monitor_interval:
                print()
                print(
                    f"[实时] t={t_sec:.3f}s phase={phase} step_count={step_count}/{total_steps} step_value={step}"
                )
                print(f" target={list(p_cmd)}")
                print(f" actual={list(pos_now)}")
                print(f" prev_actual={list(prev_actual)}")
                print(f" vel={vel}")
                print(f" current={cur}")
                last_monitor_t = now_t

            pos_prev = list(pos_now)

            if p_cmd[idx] >= open_positions[idx]:
                break

            nxt = p_cmd[idx] + step
            if nxt > open_positions[idx]:
                nxt = open_positions[idx]
            p_cmd[idx] = nxt
    else:
        # all 模式：所有关节一起执行 4095 -> 0 -> 4095
        p_cmd = list(open_positions)

        # CLOSE：4095 -> 0
        phase = "close"
        while True:
            hand.set_all_joint_positions(p_cmd)
            time.sleep(0.02)

            prev_actual = list(pos_prev)
            pos_now = hand.get_all_joint_positions()
            if not pos_now or len(pos_now) != 10:
                violations.append(("no_position", None))
                continue

            for i in range(10):
                if pos_now[i] < 0 or pos_now[i] > max_pos:
                    violations.append(("out_of_range", (i, pos_now[i])))
                if abs(pos_now[i] - pos_prev[i]) > 512:
                    violations.append(("jump", (i, pos_prev[i], pos_now[i])))

            vel, cur = read_vel_cur()

            t_sec = time.perf_counter() - start_t
            writer.writerow(
                [
                    f"{t_sec:.6f}",
                    phase,
                    step_count,
                    step,
                    *list(p_cmd),
                    *list(pos_now),
                    *prev_actual,
                    *list(vel),
                    *list(cur),
                ]
            )
            step_count += 1

            progress = step_count / float(total_steps)
            print(f"\r{_render_progress(progress)}", end="", flush=True)

            now_t = time.perf_counter()
            if now_t - last_monitor_t >= monitor_interval:
                print()
                print(
                    f"[实时] t={t_sec:.3f}s phase={phase} step_count={step_count}/{total_steps} step_value={step}"
                )
                print(f" target={list(p_cmd)}")
                print(f" actual={list(pos_now)}")
                print(f" prev_actual={list(prev_actual)}")
                print(f" vel={vel}")
                print(f" current={cur}")
                last_monitor_t = now_t

            pos_prev = list(pos_now)

            if min(p_cmd) <= close_positions[0]:
                break
            p_cmd = [max(0, min(max_pos, x - step)) for x in p_cmd]

        # OPEN：0 -> 4095
        phase = "open"
        p_cmd = list(close_positions)
        while True:
            hand.set_all_joint_positions(p_cmd)
            time.sleep(0.02)

            prev_actual = list(pos_prev)
            pos_now = hand.get_all_joint_positions()
            if not pos_now or len(pos_now) != 10:
                violations.append(("no_position", None))
                continue

            for i in range(10):
                if pos_now[i] < 0 or pos_now[i] > max_pos:
                    violations.append(("out_of_range", (i, pos_now[i])))
                if abs(pos_now[i] - pos_prev[i]) > 512:
                    violations.append(("jump", (i, pos_prev[i], pos_now[i])))

            vel, cur = read_vel_cur()

            t_sec = time.perf_counter() - start_t
            writer.writerow(
                [
                    f"{t_sec:.6f}",
                    phase,
                    step_count,
                    step,
                    *list(p_cmd),
                    *list(pos_now),
                    *prev_actual,
                    *list(vel),
                    *list(cur),
                ]
            )
            step_count += 1

            progress = step_count / float(total_steps)
            print(f"\r{_render_progress(progress)}", end="", flush=True)

            now_t = time.perf_counter()
            if now_t - last_monitor_t >= monitor_interval:
                print()
                print(
                    f"[实时] t={t_sec:.3f}s phase={phase} step_count={step_count}/{total_steps} step_value={step}"
                )
                print(f" target={list(p_cmd)}")
                print(f" actual={list(pos_now)}")
                print(f" prev_actual={list(prev_actual)}")
                print(f" vel={vel}")
                print(f" current={cur}")
                last_monitor_t = now_t

            pos_prev = list(pos_now)

            if max(p_cmd) >= open_positions[0]:
                break
            p_cmd = [max(0, min(max_pos, x + step)) for x in p_cmd]

    # 扫描结束后回到 OPEN=4095（满足“结后自动回到初始状态”）
    try:
        hand.set_all_joint_positions(open_positions)
        time.sleep(0.5)
    except Exception:
        pass

    csv_f.close()
    print(f"扫掠结束。CSV 已写入：{csv_path}  异常记录条数: {len(violations)}")
    for item in violations[:50]:
        print(item)
    if len(violations) > 50:
        print(f"... 其余 {len(violations) - 50} 条省略")

    # 绘图：速度/电流随时间曲线
    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("[跳过] 未安装 matplotlib，无法生成速度/电流图。")
        return

    def _safe_float(x):
        try:
            if x is None:
                return float("nan")
            s = str(x).strip()
            if s == "":
                return float("nan")
            return float(s)
        except Exception:
            return float("nan")

    plot_base = os.path.splitext(os.path.basename(csv_path))[0]
    single_joint_idx = args.joint_index - 1 if args.mode == "single" else None

    ts = []
    vel_series = [[] for _ in range(10)]
    cur_series = [[] for _ in range(10)]
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts.append(_safe_float(row.get("t_sec")))
            for i in range(10):
                vel_series[i].append(_safe_float(row.get(f"vel_{i}")))
                cur_series[i].append(_safe_float(row.get(f"current_{i}")))

    def _plot_metric(series, out_png: str, metric_name: str, joints):
        n = len(list(joints))
        joints = list(joints)
        fig, axes = plt.subplots(n, 1, sharex=True, figsize=(12, max(3.0, 2.0 * n)))
        if n == 1:
            axes = [axes]

        for ax, j in zip(axes, joints):
            ax.plot(ts, series[j], linewidth=1)
            ax.set_ylabel(f"J{j}")
            ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("t_sec")
        fig.suptitle(f"{metric_name} ({'all 10 joints' if args.mode == 'all' else f'single J{single_joint_idx}'})")
        fig.tight_layout()
        fig.savefig(out_png, dpi=200)
        plt.close(fig)

    if args.mode == "all":
        vel_png = os.path.join(script_dir, f"{plot_base}_velocity.png")
        cur_png = os.path.join(script_dir, f"{plot_base}_current.png")
        _plot_metric(vel_series, vel_png, "Velocity", range(10))
        _plot_metric(cur_series, cur_png, "Current", range(10))
        print(f"[绘图] 已生成：{os.path.basename(vel_png)} 与 {os.path.basename(cur_png)}")
    else:
        vel_png = os.path.join(script_dir, f"{plot_base}_velocity_single_J{single_joint_idx}.png")
        cur_png = os.path.join(script_dir, f"{plot_base}_current_single_J{single_joint_idx}.png")
        _plot_metric(vel_series, vel_png, "Velocity", [single_joint_idx])
        _plot_metric(cur_series, cur_png, "Current", [single_joint_idx])
        print(f"[绘图] 已生成：{os.path.basename(vel_png)} 与 {os.path.basename(cur_png)}")


if __name__ == "__main__":
    main()
