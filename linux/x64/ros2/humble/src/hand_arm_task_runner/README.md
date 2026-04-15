# hand_arm_task_runner

ROS 2 Humble package for teach-record, single-point playback, and multi-step sequence execution.

## Nodes

- `record_node`: capture current arm joints (`/joint_states`) + hand joints (`get_joint_angles`) to YAML.
- `playback_node`: execute one waypoint in strict serial order: arm first, then hand.
- `sequence_node`: execute multiple waypoint names from a sequence file.

## Directory convention

- Waypoints: `waypoints/<name>.yaml`
- Sequences: `sequences/<task>.yaml`

## Waypoint YAML example

```yaml
name: pick_pre
arm_joints: [0.0, -0.7, 0.0, -2.3, 0.0, 1.6, 0.8]
hand_joints: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
arm_max_vel: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
goal_tolerance: 0.01
hand_timeout: 5.0
```

## Sequence YAML example

```yaml
steps: ["pick_pre", "pick_close", "place_pre", "place_open"]
```

## Minimal bringup and run

```bash
# 1) Source environments
source /opt/ros/humble/setup.bash
source /home/agiuser/Omnihand-2025-SDK/linux/x64/ros2/humble/setup.bash
source /home/agiuser/franka_ros2_ws/install/setup.bash

# 2) Build this package
cd /home/agiuser/Omnihand-2025-SDK/linux/x64/ros2/humble
colcon build --packages-select hand_arm_task_runner
source install/setup.bash

# 3) Start OmniHand node + Franka bringup in separate terminals
ros2 run omnihand_node omnihand_2025_node
ros2 launch franka_bringup franka.launch.py robot_type:=fr3 robot_ip:=<robot_ip>

# 4) Record one waypoint
ros2 run hand_arm_task_runner record_node --ros-args -p waypoint_name:=pick_pre

# 5) Single-point playback (arm then hand)
ros2 run hand_arm_task_runner playback_node --ros-args -p waypoint_file:=waypoints/pick_pre.yaml

# 6) Sequence run
ros2 run hand_arm_task_runner sequence_node --ros-args -p sequence_file:=sequences/task_1.yaml
```
