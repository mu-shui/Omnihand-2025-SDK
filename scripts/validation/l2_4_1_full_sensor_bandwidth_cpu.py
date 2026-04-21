#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# L2-4-1：周期性获取全量触觉数据，同时做简单关节运动，记录 CPU/时间戳，用于带宽与阻塞粗测。
# O10：get_all_tactile_sensor_data_raw；O12：五指 get_tactile_sensor_3d_data 轮询。
'''
sdk未实现总线统计相关功能
'''


import argparse
import math
import threading
import time

from omnihand import Finger, HandType, OmniHand2025, OmniHandPro2025


def _psutil_cpu_percent():
    try:
        import psutil

        return psutil.cpu_percent(interval=None)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description="L2-4-1 全量触觉 + 关节运动 + CPU 采样")
    p.add_argument("--product", choices=["o10", "o12"], default="o10")
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--tactile-hz", type=float, default=50.0, help="触觉轮询目标频率（Hz）")
    args = p.parse_args()

    ht = HandType.LEFT if args.hand == "left" else HandType.RIGHT
    prod = "OmniHand 2025 (O10)" if args.product == "o10" else "OmniHand Pro 2025 (O12)"
    label = "CANFD（ZLG USB CANFD）"
    detail = (
        f"product={prod}, hand_device_id={args.hand_device_id}, "
        f"canfd_device_id={args.canfd_device_id}, canfd_channel_id={args.canfd_channel_id}"
    )
    print(f"[连接] 正在通过 {label} 连接 …  ({detail})")
    try:
        if args.product == "o10":
            hand = OmniHand2025.create_hand_by_zlgcan(
                ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
            )
        else:
            hand = OmniHandPro2025.create_hand_by_zlgcan(
                ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
            )
    except Exception as e:
        print(f"[失败] {label}：创建手部对象时异常 — {e!r}")
        raise SystemExit(1) from e
    if not hand.init():
        print(f"[失败] {label}：init() 返回 False，通讯未建立。")
        raise SystemExit(1)
    print(f"[成功] {label} 通讯正常，init 成功（{prod}）。")

    hand.set_request_interval(2)
    stop = threading.Event()

    def motion_loop():
        t0 = time.perf_counter()
        if args.product == "o10":
            mid = 2048
        else:
            mid = 1000
        while not stop.is_set():
            t = time.perf_counter() - t0
            a = 0.15 * math.sin(2 * math.pi * 0.3 * t)
            try:
                if args.product == "o10":
                    ang = hand.get_all_active_joint_angles()
                    if ang and len(ang) == 10:
                        ang[4] = a
                        ang[5] = a
                        hand.set_all_active_joint_angles(ang)
                else:
                    ang = hand.get_all_active_joint_angles()
                    if ang and len(ang) == 12:
                        ang[5] = a
                        ang[6] = a
                        hand.set_all_active_joint_angles(ang)
            except Exception:
                pass
            time.sleep(0.05)

    th = threading.Thread(target=motion_loop, daemon=True)
    th.start()

    period = 1.0 / max(1.0, args.tactile_hz)
    t0 = time.perf_counter()
    samples = 0
    errors = 0

    while time.perf_counter() - t0 < args.duration:
        loop_start = time.perf_counter()
        cpu = _psutil_cpu_percent()
        try:
            if args.product == "o10":
                hand.get_all_tactile_sensor_data_raw()
            else:
                for f in (
                    Finger.THUMB,
                    Finger.INDEX,
                    Finger.MIDDLE,
                    Finger.RING,
                    Finger.LITTLE,
                ):
                    hand.get_tactile_sensor_3d_data(f)
        except Exception:
            errors += 1
        samples += 1
        # 简单日志：每 100 次打印一行
        if samples % 100 == 0:
            print(
                f"t={time.perf_counter() - t0:.2f}s samples={samples} tactile_errors={errors} cpu%={cpu}"
            )
        spent = time.perf_counter() - loop_start
        time.sleep(max(0.0, period - spent))

    stop.set()
    th.join(timeout=1.0)
    print(
        f"完成: duration={args.duration}s  tactile_samples={samples}  errors={errors}  (安装 psutil 可显示 CPU%)"
    )


if __name__ == "__main__":
    main()
