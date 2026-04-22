#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# L2-4-1：O10 全量触觉带宽与阻塞验证。
# 以目标频率连续请求 get_all_tactile_sensor_data_raw()，并行执行握拳/张开动作，
# 实时输出阻塞/丢数/频率跌落与 CPU 占用，CSV 仅写触觉相关数据（原始值+分区求和）。
"""
常用参数说明（可通过 --help 查看）：
- --hand {left,right}：左右手，默认 left
- --hand-device-id：默认 1
- --canfd-device-id：默认 0
- --canfd-channel-id：默认 0
- --duration：测试时长（秒），默认 10.0
- --tactile-hz：目标触觉频率 Hz，默认 50.0
- --request-interval-ms：SDK 最小请求间隔，默认 2
- --motion-hold-s：握拳/张开每个姿态保持时长，默认 0.7
- --log-interval：实时日志打印周期（秒），默认 1.0
- --drop-multiplier：频率跌落判定倍数，默认 2.0
- --block-threshold-s：长期阻塞阈值（秒），默认 0.5
- -o / --output：输出 CSV 文件名，默认 l2_4_1_tactile_o10.csv
"""

import argparse
import csv
import statistics
import threading
import time

from omnihand import Finger, HandType, OmniHand2025


SENSOR_LAYOUT = [
    ("thumb", Finger.THUMB, 16),
    ("index", Finger.INDEX, 18),
    ("middle", Finger.MIDDLE, 18),
    ("ring", Finger.RING, 18),
    ("little", Finger.LITTLE, 18),
    ("palm", Finger.PALM, 78),
    ("dorsum", Finger.DORSUM, 102),
]

# 参考 demo_set_get_fist_reliability_csv.py
OPEN_TARGET_POSITIONS = [4087, 18, 3963, 2026, 4094, 4094, 2072, 4094, 39, 4093]
FIST_TARGET_POSITIONS = [4087, 4085, 1634, 2040, 3, 3, 2035, 2, 9, 3]

PARAMETER_GUIDE = """参数速览：
  --hand {left,right}            左右手，默认 left
  --hand-device-id               默认 1
  --canfd-device-id              默认 0
  --canfd-channel-id             默认 0
  --duration                     测试时长（秒），默认 10.0
  --tactile-hz                   目标触觉频率 Hz，默认 50.0
  --request-interval-ms          SDK 最小请求间隔，默认 2
  --motion-hold-s                握拳/张开每个姿态保持时长，默认 0.7
  --log-interval                 实时日志打印周期（秒），默认 1.0
  --drop-multiplier              频率跌落判定倍数，默认 2.0
  --block-threshold-s            长期阻塞阈值（秒），默认 0.5
  -o / --output                  输出 CSV 文件名，默认 l2_4_1_tactile_o10.csv
"""


def _psutil_cpu_percent():
    try:
        import psutil

        return psutil.cpu_percent(interval=None)
    except Exception:
        return None


def _build_csv_header():
    header = ["elapsed_ms"]
    for sensor_name, _, length in SENSOR_LAYOUT:
        for idx in range(length):
            header.append(f"{sensor_name}_{idx}")
        header.append(f"{sensor_name}_sum")
    header.append("total_sum")
    return header


def _empty_tactile_row(elapsed_ms):
    row = {"elapsed_ms": f"{elapsed_ms:.3f}", "total_sum": ""}
    for sensor_name, _, length in SENSOR_LAYOUT:
        for idx in range(length):
            row[f"{sensor_name}_{idx}"] = ""
        row[f"{sensor_name}_sum"] = ""
    return row


def _fill_row_by_flat_data(elapsed_ms, values):
    row = {"elapsed_ms": f"{elapsed_ms:.3f}"}
    issues = 0
    cursor = 0
    total_sum = 0
    for sensor_name, _, length in SENSOR_LAYOUT:
        segment = values[cursor : cursor + length]
        cursor += length
        if len(segment) < length:
            issues += 1
            segment = list(segment) + ["" for _ in range(length - len(segment))]
        sensor_sum = 0
        valid_count = 0
        for idx, val in enumerate(segment):
            row[f"{sensor_name}_{idx}"] = val
            if isinstance(val, int):
                sensor_sum += val
                valid_count += 1
        row[f"{sensor_name}_sum"] = sensor_sum if valid_count == length else ""
        if valid_count == length:
            total_sum += sensor_sum
    row["total_sum"] = total_sum
    return row, issues


def _parse_tactile_row(elapsed_ms, all_sensor_data):
    if not all_sensor_data:
        return _empty_tactile_row(elapsed_ms), len(SENSOR_LAYOUT), {}

    first = all_sensor_data[0]
    if hasattr(first, "sensor_id"):
        data_map = {}
        for item in all_sensor_data:
            if hasattr(item, "sensor_id"):
                data_map[item.sensor_id] = item

        row = {"elapsed_ms": f"{elapsed_ms:.3f}"}
        issues = 0
        total_sum = 0
        region_sums = {}
        for sensor_name, sensor_id, length in SENSOR_LAYOUT:
            if sensor_id not in data_map:
                issues += 1
                for idx in range(length):
                    row[f"{sensor_name}_{idx}"] = ""
                row[f"{sensor_name}_sum"] = ""
                region_sums[sensor_name] = None
                continue

            data_obj = data_map[sensor_id]
            raw = list(data_obj.data) if hasattr(data_obj, "data") and data_obj.data else []
            if len(raw) < length:
                issues += 1
            padded = [int(x) for x in raw[:length]]
            if len(padded) < length:
                padded.extend([""] * (length - len(padded)))

            sensor_sum = 0
            valid_count = 0
            for idx, val in enumerate(padded):
                row[f"{sensor_name}_{idx}"] = val
                if isinstance(val, int):
                    sensor_sum += val
                    valid_count += 1
            row[f"{sensor_name}_sum"] = sensor_sum if valid_count == length else ""
            region_sums[sensor_name] = sensor_sum if valid_count == length else None
            if valid_count == length:
                total_sum += sensor_sum

        row["total_sum"] = total_sum
        return row, issues, region_sums

    # 兼容绑定返回平铺列表的情况
    flat_values = []
    for value in all_sensor_data:
        try:
            flat_values.append(int(value))
        except Exception:
            flat_values.append("")
    row, issues = _fill_row_by_flat_data(elapsed_ms, flat_values)
    region_sums = {}
    for sensor_name, _, _ in SENSOR_LAYOUT:
        v = row.get(f"{sensor_name}_sum", "")
        region_sums[sensor_name] = v if isinstance(v, int) else None
    return row, issues, region_sums


def main():
    p = argparse.ArgumentParser(
        description="L2-4-1 O10 全量触觉 + 握拳/张开并发压力测试",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=PARAMETER_GUIDE,
    )
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--tactile-hz", type=float, default=50.0, help="触觉轮询目标频率（Hz）")
    p.add_argument("--request-interval-ms", type=int, default=2, help="SDK 请求最小间隔（ms）")
    p.add_argument("--motion-hold-s", type=float, default=0.7, help="握拳/张开每个姿态保持时长（秒）")
    p.add_argument("--log-interval", type=float, default=1.0, help="实时日志打印周期（秒）")
    p.add_argument("--drop-multiplier", type=float, default=2.0, help="dt 超过该倍数*目标周期记为频率跌落")
    p.add_argument("--block-threshold-s", type=float, default=0.5, help="dt 超过该阈值记为长期阻塞")
    p.add_argument("-o", "--output", default="l2_4_1_tactile_o10.csv", help="触觉 CSV 输出路径")
    args = p.parse_args()

    ht = HandType.LEFT if args.hand == "left" else HandType.RIGHT
    prod = "OmniHand 2025 (O10)"
    label = "CANFD（ZLG USB CANFD）"
    detail = (
        f"product={prod}, hand_device_id={args.hand_device_id}, "
        f"canfd_device_id={args.canfd_device_id}, canfd_channel_id={args.canfd_channel_id}"
    )
    print(f"[连接] 正在通过 {label} 连接 …  ({detail})")
    try:
        hand = OmniHand2025.create_hand_by_zlgcan(
            ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
        )
    except Exception as e:
        print(f"[失败] {label}：创建手部对象时异常 — {e!r}")
        raise SystemExit(1) from e
    if not hand.init():
        print(f"[失败] {label}：init() 返回 False，通讯未建立。")
        raise SystemExit(1)
    print(f"[成功] {label} 通讯正常，init 成功（{prod}）。")

    hand.set_request_interval(max(0, args.request_interval_ms))
    stop = threading.Event()
    motion_stats = {"ok": 0, "fail": 0}
    motion_lock = threading.Lock()

    def motion_loop():
        is_fist = True
        while not stop.is_set():
            target = FIST_TARGET_POSITIONS if is_fist else OPEN_TARGET_POSITIONS
            try:
                hand.set_all_joint_positions(target)
                with motion_lock:
                    motion_stats["ok"] += 1
            except Exception:
                with motion_lock:
                    motion_stats["fail"] += 1
            is_fist = not is_fist
            stop.wait(max(0.01, args.motion_hold_s))

    th = threading.Thread(target=motion_loop, daemon=True)
    th.start()

    period = 1.0 / max(1.0, args.tactile_hz)
    t0 = time.perf_counter()
    last_log = t0
    last_sample_ts = None

    samples = 0
    exception_errors = 0
    data_loss_events = 0
    freq_drop_events = 0
    long_block_events = 0
    dt_history = []

    with open(args.output, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=_build_csv_header())
        writer.writeheader()

        while time.perf_counter() - t0 < args.duration:
            loop_start = time.perf_counter()
            elapsed_s = loop_start - t0
            elapsed_ms = elapsed_s * 1000.0
            cpu = _psutil_cpu_percent()

            region_sums = {}
            try:
                all_sensor_data = hand.get_all_tactile_sensor_data_raw()
                row, issues, region_sums = _parse_tactile_row(elapsed_ms, all_sensor_data)
                if issues > 0:
                    data_loss_events += 1
            except Exception:
                exception_errors += 1
                data_loss_events += 1
                row = _empty_tactile_row(elapsed_ms)

            writer.writerow(row)
            samples += 1

            if last_sample_ts is not None:
                dt = loop_start - last_sample_ts
                dt_history.append(dt)
                if dt > period * max(1.0, args.drop_multiplier):
                    freq_drop_events += 1
                if dt > max(0.01, args.block_threshold_s):
                    long_block_events += 1
            last_sample_ts = loop_start

            now = time.perf_counter()
            if now - last_log >= max(0.2, args.log_interval):
                dt_last = dt_history[-1] if dt_history else 0.0
                inst_hz = (1.0 / dt_last) if dt_last > 0 else 0.0
                avg_hz = (samples / elapsed_s) if elapsed_s > 0 else 0.0
                sums_preview = ", ".join(
                    f"{name}:{region_sums.get(name)}"
                    for name in ["thumb", "index", "middle", "ring", "little", "palm", "dorsum"]
                )
                print(
                    f"t={elapsed_s:.2f}s samples={samples} data_loss={data_loss_events} "
                    f"freq_drop={freq_drop_events} block={long_block_events} "
                    f"inst_hz={inst_hz:.1f} avg_hz={avg_hz:.1f} cpu%={cpu} | {sums_preview}"
                )
                last_log = now

            spent = time.perf_counter() - loop_start
            time.sleep(max(0.0, period - spent))

    stop.set()
    th.join(timeout=1.0)

    avg_hz = (samples / args.duration) if args.duration > 0 else 0.0
    med_dt_ms = statistics.median(dt_history) * 1000.0 if dt_history else 0.0
    max_dt_ms = max(dt_history) * 1000.0 if dt_history else 0.0
    p95_dt_ms = 0.0
    if len(dt_history) >= 2:
        dt_sorted = sorted(dt_history)
        idx = min(len(dt_sorted) - 1, int(len(dt_sorted) * 0.95))
        p95_dt_ms = dt_sorted[idx] * 1000.0

    with motion_lock:
        motion_ok = motion_stats["ok"]
        motion_fail = motion_stats["fail"]

    print(f"CSV 已写入: {args.output}")
    print(
        f"完成: duration={args.duration:.1f}s samples={samples} avg_hz={avg_hz:.1f} "
        f"exceptions={exception_errors} data_loss={data_loss_events} "
        f"freq_drop={freq_drop_events} block={long_block_events}"
    )
    print(
        f"采样间隔统计: median={med_dt_ms:.3f}ms p95={p95_dt_ms:.3f}ms max={max_dt_ms:.3f}ms"
    )
    print(f"动作线程统计: motion_ok={motion_ok} motion_fail={motion_fail}")


if __name__ == "__main__":
    main()
