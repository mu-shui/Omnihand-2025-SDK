import time
from omnihand import OmniHand2025, HandType

hand = OmniHand2025.create_hand_by_zlgcan(
    hand_type=HandType.LEFT,
    hand_device_id=1,
    canfd_device_id=0,
    canfd_channel_id=0,
)

# if not hand.init():
#     raise SystemExit("init failed")

# # 读当前位置
# cur = hand.get_all_joint_positions()
# print("current positions:", cur)

# # 设目标位置（10个值，0~4095）
# 
# #aim_positions[9] = 4095  # 举例：第10个电机到最大
# actual = hand.set_all_joint_positions(aim_positions)  # SDK会返回实际位置（失败可能为空）
# print("set reply positions:", actual)

# time.sleep(0.5)

# # 再读一次
# cur2 = hand.get_all_joint_positions()
# print("after set positions:", cur2)

aim_positions = [4095] * 10
hand.set_all_joint_positions(aim_positions) 