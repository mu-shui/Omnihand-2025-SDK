#!/usr/bin/env python3
# Copyright (c) 2025, Agibot Co., Ltd.
# 最小 CANFD（ZLG USB CANFD）连接检测：仅 create + init + 读厂商信息，不发送关节控制指令。
# 用于在跑压测前确认适配器与手部链路是否可用。

import argparse
import sys

from omnihand import HandType, OmniHand2025


def main() -> int:
    p = argparse.ArgumentParser(
        description="OmniHand 2025 (O10) CANFD 连接检测（ZLG USBCANFD）"
    )
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)
    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)
    args = p.parse_args()

    ht = HandType.LEFT if args.hand == "left" else HandType.RIGHT
    label = "CANFD（ZLG USB CANFD）"
    detail = (
        f"hand={args.hand}, hand_device_id={args.hand_device_id}, "
        f"canfd_device_id={args.canfd_device_id}, canfd_channel_id={args.canfd_channel_id}"
    )
    print(f"[连接] 正在通过 {label} 检测 …  ({detail})")

    try:
        hand = OmniHand2025.create_hand_by_zlgcan(
            hand_type=ht,
            hand_device_id=args.hand_device_id,
            canfd_device_id=args.canfd_device_id,
            canfd_channel_id=args.canfd_channel_id,
        )
    except Exception as e:
        print(f"[失败] {label}：创建手部对象异常 — {e!r}")
        print("       请检查 ZLG 驱动、USB、udev 权限及适配器是否被占用。")
        return 1

    if not hand.init():
        print(f"[失败] {label}：init() 返回 False。")
        print("       请检查手部上电、CAN 接线、终端电阻、hand_device_id 与通道号。")
        return 1

    try:
        v = hand.get_vendor_info()
    except Exception as e:
        print(f"[失败] {label}：init 成功但读厂商信息失败 — {e!r}")
        print("       若底层报 VCI_TransmitFD，多为总线未应答：核对左右手、设备 ID、CAN 通道。")
        return 1

    print(f"[成功] {label} 通讯正常。")
    print(
        f"       型号: {v.product_model}  序列号: {v.product_seq_num}  "
        f"HW: {v.hardware_version.major}.{v.hardware_version.minor}.{v.hardware_version.patch}  "
        f"SW: {v.software_version.major}.{v.software_version.minor}.{v.software_version.patch}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
