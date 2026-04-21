#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# L2-5-1：经 CAN 周期读取触觉数据，记录时间戳，计算采样间隔中位数与等效刷新率。
'''
只要进入循环就会 append 时间戳并写 CSV；
即使读取异常（except），也会写一行 err:...，但时间戳仍计入 stamps
dt = stamps[i] - stamps[i-1]
med = median(dt) → 中位刷新间隔
hz = 1/med → 等效刷新频率
jitter = pstdev(dt) → 抖动（间隔标准差
'''

import argparse
import csv
import statistics
import time

from omnihand import Finger, HandType, OmniHand2025, OmniHandPro2025


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


def main():
    p = argparse.ArgumentParser(description="L2-5-1 触觉采样时间间隔（CAN）")
    p.add_argument("--product", choices=["o10", "o12"], default="o10")
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--can-interface", default="can0")
    p.add_argument("--link", choices=["zlgcan", "socketcan"], default="zlgcan")
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("-o", "--output", default="tactile_feedback_ts.csv")
    args = p.parse_args()

    hand = connect_hand(args)

    hand.set_request_interval(0)
    t0 = time.perf_counter()
    stamps = []

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if args.product == "o10":
            w.writerow(["t_s", "sum_raw"])
        else:
            w.writerow(["t_s", "thumb_nf", "index_nf"])

        while time.perf_counter() - t0 < args.duration:
            ts = time.perf_counter() - t0
            stamps.append(ts)
            try:
                if args.product == "o10":
                    raw = hand.get_all_tactile_sensor_data_raw()
                    s = sum(int(x) for x in raw) if raw else 0
                    w.writerow([f"{ts:.6f}", s])
                else:
                    t = hand.get_tactile_sensor_3d_data(Finger.THUMB)
                    i = hand.get_tactile_sensor_3d_data(Finger.INDEX)
                    w.writerow([f"{ts:.6f}", t.normal_force, i.normal_force])
            except Exception as e:
                w.writerow([f"{ts:.6f}", f"err:{e}"])
            #time.sleep(0.0005)

    if len(stamps) < 3:
        print("样本过少")
        return

    dt = [stamps[i] - stamps[i - 1] for i in range(1, len(stamps))]
    med = statistics.median(dt)
    hz = 1.0 / med if med > 0 else 0.0
    try:
        jitter = statistics.pstdev(dt)
    except statistics.StatisticsError:
        jitter = 0.0

    print(f"写入: {args.output}")
    print(f"样本数: {len(stamps)}  间隔中位数: {med*1000:.3f} ms  等效频率: {hz:.1f} Hz  间隔抖动(总体标准差): {jitter*1000:.3f} ms")


if __name__ == "__main__":
    main()
