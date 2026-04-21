from omnihand import OmniHand2025, HandType

# 创建灵巧手实例（ZLG USBCANFD）
hand = OmniHand2025.create_hand_by_zlgcan(
    hand_type=HandType.LEFT,    # 或 HandType.RIGHT
    hand_device_id=1,            # 灵巧手 ID（出厂默认为 1）
    canfd_device_id=0,           # CANFD 适配器索引（默认从 0 起）
    canfd_channel_id=0           # USBCANFD 200U 有两个通道 (can0/can1)，100U 或 MINI 的通道 id 恒为 0
)

# 初始化
if not hand.init():
    print("初始化失败")
    exit(1)

print("灵巧手初始化成功！")

# 获取设备信息
info = hand.get_device_info()
print(f"设备 ID: {info.hand_device_id}")

# 读取当前关节角度（弧度）
angles = hand.get_all_active_joint_angles()
print(f"当前角度: {angles}")

# 移动到目标位置（10 个关节，单位弧度）
target_angles = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
hand.set_all_active_joint_angles(target_angles)
print("已移动到目标位置")