#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# L2-5-1 扩展：以最大速率读取触觉数据，按“调用返回时刻”记录 elapsed_ms。

import argparse
import csv
import statistics
import time

from omnihand import Finger, HandType, OmniHand2025, OmniHandPro2025


SENSOR_LAYOUT = [
    ("thumb", Finger.THUMB, 16),
    ("index", Finger.INDEX, 18),
    ("middle", Finger.MIDDLE, 18),
    ("ring", Finger.RING, 18),
    ("little", Finger.LITTLE, 18),
    ("palm", Finger.PALM, 78),
    ("dorsum", Finger.DORSUM, 102),
]


def _connection_hint(args) -> tuple[str, str]:
    if args.link == "socketcan":
        return (
            "SocketCAN（Linux CAN/CANFD）",
            f"can_interface={args.can_interface}, hand_device_id={args.hand_device_id}",
        )
    return (
        "CANFD（ZLG USB CANFD）",
        f"canfd_device_id={args.canfd_device_id}, canfd_channel_id={args.canfd_channel_id}, "
        f"hand_device_id={args.hand_device_id}",
    )


def create_hand(args):
    ht = HandType.LEFT if args.hand == "left" else HandType.RIGHT
    if args.product == "o10":
        if args.link == "socketcan":
            return OmniHand2025.create_hand_socketcan(
                ht, args.hand_device_id, args.can_interface
            )
        return OmniHand2025.create_hand_by_zlgcan(
            ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
        )
    if args.link == "socketcan":
        return OmniHandPro2025.create_hand_socketcan(
            ht, args.hand_device_id, args.can_interface
        )
    return OmniHandPro2025.create_hand_by_zlgcan(
        ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
    )


def connect_hand(args):
    prod = "O10" if args.product == "o10" else "O12"
    label, detail = _connection_hint(args)
    print(f"[连接] 正在通过 {label} 连接 …  ({detail}, product={prod})")
    try:
        hand = create_hand(args)
    except Exception as e:
        print(f"[失败] {label}：创建手部对象时异常 — {e!r}")
        raise SystemExit(1) from e
    if not hand.init():
        print(f"[失败] {label}：init() 返回 False，通讯未建立。")
        raise SystemExit(1)
    print(f"[成功] {label} 通讯正常，init 成功。")
    return hand


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _build_o10_csv_header():
    header = ["elapsed_ms"]
    for sensor_name, _, length in SENSOR_LAYOUT:
        for idx in range(length):
            header.append(f"{sensor_name}_{idx}")
        header.append(f"{sensor_name}_sum")
    header.append("total_sum")
    return header


def _empty_o10_row(elapsed_ms):
    row = {"elapsed_ms": f"{elapsed_ms:.3f}", "total_sum": ""}
    for sensor_name, _, length in SENSOR_LAYOUT:
        for idx in range(length):
            row[f"{sensor_name}_{idx}"] = ""
        row[f"{sensor_name}_sum"] = ""
    return row


def _fill_o10_row_by_flat_data(elapsed_ms, values):
    row = {"elapsed_ms": f"{elapsed_ms:.3f}"}
    issues = 0
    cursor = 0
    total_sum = 0
    region_sums = {}
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
        region_sums[sensor_name] = sensor_sum if valid_count == length else None
        if valid_count == length:
            total_sum += sensor_sum
    row["total_sum"] = total_sum
    return row, issues, region_sums


def _parse_o10_row(elapsed_ms, all_sensor_data):
    if not all_sensor_data:
        return _empty_o10_row(elapsed_ms), len(SENSOR_LAYOUT), {}

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
        for name, sensor_id, length in SENSOR_LAYOUT:
            sensor_item = data_map.get(sensor_id)
            if sensor_item is None or not hasattr(sensor_item, "data"):
                issues += 1
                for idx in range(length):
                    row[f"{name}_{idx}"] = ""
                row[f"{name}_sum"] = ""
                region_sums[name] = None
                continue
            raw = list(sensor_item.data) if sensor_item.data else []
            if len(raw) < length:
                issues += 1
            values = [_safe_int(v) for v in raw[:length]]
            values = [v if v is not None else "" for v in values]
            if len(values) < length:
                values.extend([""] * (length - len(values)))

            sensor_sum = 0
            valid_count = 0
            for idx, val in enumerate(values):
                row[f"{name}_{idx}"] = val
                if isinstance(val, int):
                    sensor_sum += val
                    valid_count += 1
            row[f"{name}_sum"] = sensor_sum if valid_count == length else ""
            region_sums[name] = sensor_sum if valid_count == length else None
            if valid_count == length:
                total_sum += sensor_sum
        row["total_sum"] = total_sum
        return row, issues, region_sums

    flat_values = []
    for value in all_sensor_data:
        parsed = _safe_int(value)
        flat_values.append(parsed if parsed is not None else "")
    return _fill_o10_row_by_flat_data(elapsed_ms, flat_values)


def _collect_o10(hand, elapsed_ms):
    raw = hand.get_all_tactile_sensor_data_raw()
    row, issues, region_sums = _parse_o10_row(elapsed_ms, raw)
    return row, issues, region_sums


def _collect_o12(hand, elapsed_ms):
    row = {"elapsed_ms": f"{elapsed_ms:.3f}"}
    for sensor_name, _, length in SENSOR_LAYOUT:
        for idx in range(length):
            row[f"{sensor_name}_{idx}"] = ""
        row[f"{sensor_name}_sum"] = ""
    row["total_sum"] = ""

    region_sums = {
        "thumb": None,
        "index": None,
        "middle": None,
        "ring": None,
        "little": None,
        "palm": None,
        "dorsum": None,
    }
    issues = 0

    try:
        thumb = hand.get_tactile_sensor_3d_data(Finger.THUMB)
        thumb_nf = _safe_int(getattr(thumb, "normal_force", None))
        if thumb_nf is not None:
            row["thumb_0"] = thumb_nf
            row["thumb_sum"] = thumb_nf
            region_sums["thumb"] = thumb_nf
    except Exception:
        issues += 1

    try:
        index = hand.get_tactile_sensor_3d_data(Finger.INDEX)
        index_nf = _safe_int(getattr(index, "normal_force", None))
        if index_nf is not None:
            row["index_0"] = index_nf
            row["index_sum"] = index_nf
            region_sums["index"] = index_nf
    except Exception:
        issues += 1

    total = 0
    valid_regions = 0
    for name in ["thumb", "index"]:
        val = region_sums[name]
        if isinstance(val, int):
            total += val
            valid_regions += 1
    if valid_regions > 0:
        row["total_sum"] = total
    if valid_regions < 2:
        issues += 1
    return row, issues, region_sums


def _median_ms(values):
    return statistics.median(values) * 1000.0 if values else 0.0


def _avg_ms(values):
    return (sum(values) / len(values)) * 1000.0 if values else 0.0


def _hz_by_median(values):
    if not values:
        return 0.0
    med = statistics.median(values)
    return (1.0 / med) if med > 0 else 0.0


def _is_number(value):
    return isinstance(value, (int, float))


def main():
    p = argparse.ArgumentParser(description="L2-5-1 触觉反馈最大速率采样（返回时刻打点）")
    p.add_argument("--product", choices=["o10", "o12"], default="o10")
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--can-interface", default="can0")
    p.add_argument("--link", choices=["zlgcan", "socketcan"], default="zlgcan")
    p.add_argument("--duration", type=float, default=10.0, help="采样持续时长（秒）")
    p.add_argument("--request-interval-ms", type=int, default=0, help="SDK 请求最小间隔（ms）")
    p.add_argument("--change-threshold", type=int, default=0, help="有效变化阈值（abs(delta)>=阈值）")
    p.add_argument("--log-interval", type=float, default=1.0, help="实时日志输出间隔（秒）")
    p.add_argument("-o", "--output", default="l2_5_1_sensor_feedback_maxrate.csv")
    args = p.parse_args()

    hand = connect_hand(args)
    hand.set_request_interval(max(0, args.request_interval_ms))

    t0 = time.perf_counter()
    last_log = t0

    sample_ts = []
    effective_ts = []
    exception_count = 0
    valid_samples = 0
    data_loss_events = 0

    prev_region_sums = None
    prev_total_sum = None

    base_csv_fields = _build_o10_csv_header()
    extra_csv_fields = [
        "is_effective_update",
        "effective_change_count",
        "changed_regions",
        "delta_total_sum",
        "status",
        "error",
    ]
    csv_fields = base_csv_fields + extra_csv_fields

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()

        while time.perf_counter() - t0 < args.duration:
            row = {k: "" for k in csv_fields}
            changed_regions = []
            err = ""
            status = "ok"
            region_sums = {}

            try:
                # 先执行 SDK 调用，再取时间戳，确保 elapsed_ms 对齐“调用返回时刻”。
                if args.product == "o10":
                    sample_row, issues, region_sums = _collect_o10(hand, 0.0)
                else:
                    sample_row, issues, region_sums = _collect_o12(hand, 0.0)
                sample_time = time.perf_counter()
                elapsed_ms = (sample_time - t0) * 1000.0
                sample_ts.append(sample_time)
                sample_row["elapsed_ms"] = f"{elapsed_ms:.3f}"
                row.update(sample_row)
                if issues > 0:
                    status = "invalid"
                    data_loss_events += 1
                else:
                    valid_samples += 1
            except Exception as e:
                sample_time = time.perf_counter()
                elapsed_ms = (sample_time - t0) * 1000.0
                sample_ts.append(sample_time)
                status = "error"
                err = repr(e)
                exception_count += 1
                data_loss_events += 1
                row.update(_empty_o10_row(elapsed_ms))

            row["status"] = status
            row["error"] = err

            is_effective = 0
            delta_total_sum = ""
            if status == "ok":
                current_region_sums = [region_sums.get(name) for name, _, _ in SENSOR_LAYOUT]
                if prev_region_sums is not None:
                    for idx, (region_name, _, _) in enumerate(SENSOR_LAYOUT):
                        prev_v = prev_region_sums[idx]
                        curr_v = current_region_sums[idx]
                        if prev_v is None or curr_v is None:
                            continue
                        delta = abs(curr_v - prev_v)
                        threshold = max(0, args.change_threshold)
                        if (threshold == 0 and delta > 0) or (
                            threshold > 0 and delta >= threshold
                        ):
                            changed_regions.append(region_name)
                    if changed_regions:
                        is_effective = 1
                        effective_ts.append(sample_time)
                prev_region_sums = current_region_sums

                total_sum = row.get("total_sum", "")
                if _is_number(prev_total_sum) and _is_number(total_sum):
                    delta_total_sum = total_sum - prev_total_sum
                prev_total_sum = total_sum

            row["is_effective_update"] = is_effective
            row["effective_change_count"] = len(changed_regions)
            row["changed_regions"] = "|".join(changed_regions)
            row["delta_total_sum"] = delta_total_sum
            writer.writerow(row)

            now = time.perf_counter()
            if now - last_log >= max(0.2, args.log_interval):
                elapsed_s = now - t0
                sample_count = len(sample_ts)
                avg_sample_hz = (sample_count / elapsed_s) if elapsed_s > 0 else 0.0
                print(
                    f"t={elapsed_s:.2f}s samples={sample_count} valid={valid_samples} "
                    f"data_loss={data_loss_events} effective={len(effective_ts)} avg_sample_hz={avg_sample_hz:.1f}"
                )
                last_log = now

    sample_dt = [sample_ts[i] - sample_ts[i - 1] for i in range(1, len(sample_ts))]
    effective_dt = [effective_ts[i] - effective_ts[i - 1] for i in range(1, len(effective_ts))]

    sample_median_ms = _median_ms(sample_dt)
    sample_avg_ms = _avg_ms(sample_dt)
    sample_median_hz = _hz_by_median(sample_dt)
    effective_median_ms = _median_ms(effective_dt)
    effective_avg_ms = _avg_ms(effective_dt)
    effective_median_hz = _hz_by_median(effective_dt)
    effective_min_ms = min(effective_dt) * 1000.0 if effective_dt else 0.0

    print(f"CSV 已写入: {args.output}")
    print(
        f"采样统计: samples={len(sample_ts)} valid={valid_samples} data_loss={data_loss_events} "
        f"exceptions={exception_count} sample_interval_median={sample_median_ms:.3f}ms "
        f"sample_interval_avg={sample_avg_ms:.3f}ms sample_median_hz={sample_median_hz:.2f}Hz"
    )
    print(
        f"有效更新统计: effective_updates={len(effective_ts)} "
        f"effective_interval_min={effective_min_ms:.3f}ms "
        f"effective_interval_median={effective_median_ms:.3f}ms "
        f"effective_interval_avg={effective_avg_ms:.3f}ms "
        f"effective_median_hz={effective_median_hz:.2f}Hz"
    )
    if len(effective_dt) < 1:
        print("有效更新间隔样本不足（需要至少 2 次有效更新事件才可计算间隔）。")


if __name__ == "__main__":
    main()
