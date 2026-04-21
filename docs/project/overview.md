# Project Overview

## What We Are Building

### Problem Definition

This repository provides the OmniHand 2025 SDK and validation tooling for controlling and testing dexterous hand devices (O10/O12) on Linux and Windows.

### System Boundary

- Responsible for SDK APIs (C++/Python), ROS2 integration (Linux), demos, and validation scripts.
- Not responsible for robot whole-body planning, external motion planners, or hardware manufacturing diagnostics outside exposed device interfaces.

### Input / Output

- Inputs:
  - User commands (Python/C++/ROS2/service/topic).
  - Device connection parameters (CANFD/RS485, device IDs, serial numbers).
  - Validation script arguments and runtime options.
- Outputs:
  - Device actions (joint movement commands).
  - Device feedback (joint angles, status reports, topic/service responses).
  - Validation artifacts (CSV logs, plots, terminal logs).

## Purpose

### Target Scenarios and Business Value

- Fast integration of OmniHand into robotics applications.
- Repeatable firmware and communication validation before deployment.
- Reduced integration risk through standardized demos and checks.

### Quantifiable Goals

- Launch ROS2 hand node successfully on supported Linux environments.
- Execute validation scripts under `scripts/validation` and produce reproducible logs.
- Verify joint command/feedback loops operate within expected timing and stability constraints.

## How It Works

### Main Flow

1. Install SDK runtime (`linux/x64/install.sh`) and source ROS2 overlays as needed.
2. Connect hand hardware and communication adapter.
3. Start control node or run API-based scripts.
4. Run validation scripts and inspect generated logs/plots.

### Core Dependencies

- ROS2 Humble (Linux path for ROS2 usage).
- Python 3.10 runtime for Python demos/tests.
- CANFD/RS485 communication stack and adapter drivers.
- Prebuilt OmniHand shared libraries from release package.

### Runtime and Entry Points

- SDK install: `linux/x64/install.sh`
- ROS2 setup: `linux/x64/ros2/setup.bash`
- Validation scripts root: `scripts/validation`

## Feasibility and Risk

### Assumptions

- Supported OS and architecture are used.
- Communication adapter driver and permissions are correctly configured.
- Device firmware is compatible with the SDK release.

### Known Limitations

- ROS2 interface is Linux-only.
- Runtime behavior depends on external device state and communication quality.
- Release package completeness directly affects message/service runtime (shared-library dependencies).

### Failure Modes and Fallback

- Failure mode: device cannot initialize due to adapter/permission mismatch.
  - Fallback: verify adapter visibility, udev/permission setup, and connection parameters.
- Failure mode: ROS2 custom message type support cannot load due to missing shared libraries.
  - Fallback: use updated release package or rebuild message artifacts from source package.

### Currently Not Supported

- No guarantee of stable behavior on unsupported OS/distribution combinations.
- No support for Windows ROS2 interface in this release structure.
