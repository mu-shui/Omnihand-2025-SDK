# Project File Map

## Structure

- `doc/`
  - Product and API documentation (English/Chinese), quick start, troubleshooting.
- `linux/x64/`
  - Linux release artifacts, install scripts, Python wheels, ROS2 overlay files.
- `windows/x64/`
  - Windows release artifacts and platform-specific assets.
- `scripts/validation/`
  - Firmware validation scripts, logs, and generated artifacts.
- `scripts/validation/README.md`
  - Validation-scope description and usage context for firmware validation.
- `docs/project/`
  - Project-maintenance docs for overview, structure map, and changelog.

## Key File Responsibilities

- `linux/x64/install.sh`
  - Installs SDK runtime components; modify when install flow or runtime dependencies change.
- `linux/x64/ros2/setup.bash`
  - Exposes ROS2 overlay environment variables; modify when ROS2 package layout changes.
- `scripts/validation/l2_2_1_joint_sweep_0_4095_check.py`
  - Joint sweep validation logic and data checks; modify when sweep test logic or limits change.
- `scripts/validation/l2_1_2_comm_frequency_packet_loss.py`
  - Communication frequency and packet-loss validation; modify when comm acceptance criteria change.
- `scripts/validation/README.md`
  - Human-readable entry doc for firmware validation code; modify when validation scope or paths change.
- `docs/project/overview.md`
  - Project purpose, architecture, and risk baseline; modify whenever goals/constraints/flows change.
- `docs/project/changelog.md`
  - Reverse-chronological change record; update for every actual repository change.

## Core Symbol Index

- `OmniHand2025::createHandByZlgcan`
  - Role: create O10 hand instance via ZLG CANFD.
  - Principle: wraps communication initialization and returns a controllable hand object.
- `SetAllActiveJointAngles` (C++/Python API equivalents)
  - Role: command active joints to target positions.
  - Principle: sends target joint setpoints to device control pipeline.
- `/omnihand/omnihand_2025/left/set_joint_angles` (ROS2 service)
  - Role: set O10 joint targets through ROS2 interface.
  - Principle: service request provides full joint vector and timeout for motion completion.
- `/omnihand/omnihand_2025/left/get_joint_angles` (ROS2 service)
  - Role: query current O10 joint angles and readiness.
  - Principle: returns current state snapshot from node/device interface.
