import argparse
import time
from omnihand import OmniHand2025, HandType

def main():
    p = argparse.ArgumentParser(description="Read joint motor velocities (O10)")
    p.add_argument("--device", choices=["zlgcan", "hcan", "usb", "rs485", "socketcan"], default="zlgcan")
    p.add_argument("--hand", choices=["left", "right"], default="left")
    p.add_argument("--hand-device-id", type=int, default=1)

    p.add_argument("--canfd-device-id", type=int, default=0)
    p.add_argument("--canfd-channel-id", type=int, default=0)

    p.add_argument("--uart-port", default="/dev/ttyACM0")
    p.add_argument("--baudrate", type=int, default=460800)

    p.add_argument("--can-interface", default="can0")
    p.add_argument("--period", type=float, default=0.05, help="print period seconds")
    args = p.parse_args()

    ht = HandType.LEFT if args.hand == "left" else HandType.RIGHT

    if args.device == "hcan":
        hand = OmniHand2025.create_hand_by_hcan(
            hand_type=ht,
            hand_device_id=args.hand_device_id,
            canfd_device_id=args.canfd_device_id,
            canfd_channel_id=args.canfd_channel_id,
        )
    elif args.device == "rs485":
        # RS485 文档里速度接口不支持（get_joint_velocity / set_joint_velocity）
        hand = OmniHand2025.create_hand_by_rs485(
            hand_type=ht,
            hand_device_id=args.hand_device_id,
            uart_port=args.uart_port,
            baudrate=args.baudrate,
        )
    elif args.device == "usb":
        hand = OmniHand2025.create_hand_by_usb(
            ht, args.hand_device_id, args.uart_port, args.baudrate
        )
    elif args.device == "socketcan":
        hand = OmniHand2025.create_hand_socketcan(
            ht, args.hand_device_id, args.can_interface
        )
    else:  # zlgcan
        hand = OmniHand2025.create_hand_by_zlgcan(
            ht, args.hand_device_id, args.canfd_device_id, args.canfd_channel_id
        )

    if not hand.init():
        raise SystemExit("init failed")

    # 可选：请求间隔设为 0 以尽量快（如你担心总线负载可把它改成 2/5/10ms）
    try:
        hand.set_request_interval(0)
    except Exception:
        pass

    print("Reading velocities... Ctrl+C to stop")
    while True:
        v = hand.get_all_joint_velocities()  # 10 个关节
        print("velocities:", v)
        time.sleep(max(0.001, args.period))

if __name__ == "__main__":
    main()