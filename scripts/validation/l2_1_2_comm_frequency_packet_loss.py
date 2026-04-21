#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# 依据测试项 L2-1-2：在计划的高/低频场景下，通过不同链路周期下发关节指令并读取反馈，统计丢包率。
# 典型判据示例：500 Hz、持续 5 s、丢包率小于 1%（以实机与工装为准）。
#
# 仅 OmniHand 2025 (O10) 支持 USB / RS485；CANFD 走 ZLG 或 SocketCAN。O12 请仅用 canfd / socketcan 模式。

'''
每次循环做一件事：
调 set_all_joint_positions(positions)
然后用下面规则记“成功”：
返回值存在，并且 len(actual) == 10 → 记一次成功应答（ok += 1）
其他情况（异常、None、长度不对）→ 记一次失败
最后：
sent = 循环调用次数
ok = 成功次数
loss_rate = (sent - ok) / sent
所以这个“丢包率”其实是 API 请求失败率（近似）。
'''

import argparse
import time

from omnihand import HandType, OmniHand2025


def _connection_hint(args) -> tuple[str, str]:
    lk = args.link
    if lk == "usb":
        return (
            "USB（CDC 串口直连 O10）",
            f"uart_port={args.uart_port}, baudrate={args.baudrate}, hand_device_id={args.hand_device_id}",
        )
    if lk == "rs485":
        return (
            "RS485",
            f"uart_port={args.uart_port}, baudrate={args.baudrate}, hand_device_id={args.hand_device_id}",
        )
    if lk == "socketcan":
        return (
            "SocketCAN（Linux CAN/CANFD）",
            f"can_interface={args.can_interface}, hand_device_id={args.hand_device_id}",
        )
    return (
        "CANFD（ZLG USB CANFD）",
        f"hand_device_id={args.hand_device_id}, canfd_device_id={args.canfd_device_id}, "
        f"canfd_channel_id={args.canfd_channel_id}",
    )


def create_hand_o10(args) -> OmniHand2025:
    ht = HandType.LEFT if args.hand.lower() == "left" else HandType.RIGHT
    if args.link == "usb":
        return OmniHand2025.create_hand_by_usb(
            ht, args.hand_device_id, args.uart_port, args.baudrate
        )
    if args.link == "rs485":
        return OmniHand2025.create_hand_by_rs485(
            ht, args.hand_device_id, args.uart_port, args.baudrate
        )
    if args.link == "socketcan":
        return OmniHand2025.create_hand_socketcan(
            ht, args.hand_device_id, args.can_interface
        )
    # canfd (ZLG USB CANFD)
    return OmniHand2025.create_hand_by_zlgcan(
        ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
    )


def connect_hand_o10(args) -> OmniHand2025:
    label, detail = _connection_hint(args)
    print(f"[连接] 正在通过 {label} 连接 …  ({detail})")
    try:
        hand = create_hand_o10(args)
    except Exception as e:
        print(f"[失败] {label}：创建手部对象时异常 — {e!r}")
        print("       请检查 SDK、驱动、udev、串口权限或 CAN 适配器是否被占用。")
        raise SystemExit(1) from e
    if not hand.init():
        print(f"[失败] {label}：init() 返回 False，通讯未建立。")
        print("       请检查：手部上电、线缆、hand_device_id、CAN 通道或串口设备名。")
        raise SystemExit(1)
    print(f"[成功] {label} 通讯正常，init 成功。")
    return hand


def main():
    p = argparse.ArgumentParser(
        description="L2-1-2: 固定频率 set+get 电机位置，统计成功应答比例（丢包率近似）。"
    )
    p.add_argument(
        "--link",
        choices=["usb", "rs485", "canfd", "socketcan"],
        default="canfd",
        help="通信链路：usb/rs485 仅 O10；canfd=ZLG USBCANFD；socketcan=Linux can0 等",
    )
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--uart-port", default="/dev/ttyACM0", help="usb/rs485 串口设备")
    p.add_argument("--baudrate", type=int, default=460800)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    p.add_argument("--can-interface", default="can0", help="socketcan 接口名")
    p.add_argument("--duration", type=float, default=5.0, help="测试时长（秒）")
    p.add_argument("--hz", type=float, default=500.0, help="目标请求频率（Hz）")
    p.add_argument("--timeout-ms", type=int, default=30, help="frame 接收超时（ms）")
    args = p.parse_args()

    if args.hz <= 0 or args.duration <= 0:
        raise SystemExit("hz 与 duration 必须为正")

    hand = connect_hand_o10(args)

    hand.set_frame_recv_timeout(max(10, min(1000, args.timeout_ms)))
    interval_ms = max(0, int(round(1000.0 / args.hz)))
    hand.set_request_interval(interval_ms)

    # 初始位姿，避免未就绪
    try:
        positions = hand.get_all_joint_positions()
        if not positions or len(positions) != 10:
            positions = [2048] * 10
    except Exception:
        positions = [2048] * 10
    time.sleep(0.2)

    sent = 0
    ok = 0
    t0 = time.perf_counter()
    period = 1.0 / args.hz
    next_fire = t0

    while time.perf_counter() - t0 < args.duration:
        now = time.perf_counter()
        if now < next_fire:
            time.sleep(next_fire - now)
        next_fire += period

        sent += 1
        # 轻微扰动目标，便于区分帧
        positions[0] = (positions[0] + 3) % 4096
        try:
            actual = hand.set_all_joint_positions(positions)
            if actual and len(actual) == 10:
                ok += 1
                positions = list(actual)
        except Exception:
            pass

    elapsed = time.perf_counter() - t0
    loss_rate = 100.0 * (sent - ok) / sent if sent else 0.0
    print(f"链路: {args.link}")
    print(f"时长: {elapsed:.3f}s  目标: {args.hz}Hz  请求间隔: {interval_ms}ms")
    print(f"发送次数: {sent}  成功应答: {ok}  丢包率(近似): {loss_rate:.3f}%")
    if loss_rate >= 1.0:
        print("提示: 未满足小于 1% 时需检查 USB 线、CAN 负载、timeout、CPU 抢占与 Python 调度。")


if __name__ == "__main__":
    main()
