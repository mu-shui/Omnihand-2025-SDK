#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# L2-5-0：经 CAN 周期运动关节并同步采集关节反馈，记录时间戳，用于离线计算刷新率与抖动。
'''
sdk未实现总线统计相关功能
'''

import argparse
import csv
import math
import statistics
import time

from omnihand import HandType, OmniHand2025, OmniHandPro2025


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
    p = argparse.ArgumentParser(description="L2-5-0 关节反馈时间间隔记录（CAN）")
    p.add_argument("--product", choices=["o10", "o12"], default="o10")
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--can-interface", default="can0")
    p.add_argument("--link", choices=["zlgcan", "socketcan"], default="zlgcan")
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--motion-hz", type=float, default=2.0, help="正弦运动频率（Hz）")
    p.add_argument("-o", "--output", default="joint_feedback_ts.csv")
    args = p.parse_args()

    hand = connect_hand(args)

    hand.set_request_interval(0)
    n_joint = 10 if args.product == "o10" else 12
    t0 = time.perf_counter()
    stamps = []

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "j0"] + [f"j{i}" for i in range(1, n_joint)])

        while time.perf_counter() - t0 < args.duration:
            now = time.perf_counter() - t0
            ang = hand.get_all_active_joint_angles()
            if ang and len(ang) >= n_joint:
                a = 0.12 * math.sin(2 * math.pi * args.motion_hz * now)
                ang[min(4, n_joint - 1)] = a
                ang[min(5, n_joint - 1)] = a
                try:
                    hand.set_all_active_joint_angles(ang)
                except Exception:
                    pass

            pos = hand.get_all_joint_positions()
            ts = time.perf_counter() - t0
            stamps.append(ts)
            if pos and len(pos) >= n_joint:
                w.writerow([f"{ts:.6f}"] + [str(int(x)) for x in pos[:n_joint]])
            #time.sleep(0.0000001)

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
