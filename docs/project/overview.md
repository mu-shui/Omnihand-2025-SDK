# 项目概览

## 在做什么
本项目提供一套基于 Python + ROS2 的手臂协同任务 GUI（`gui_app.py`），用于：
- 初始化运行环境与机械臂 bringup
- 记录点位（臂关节 + 手关节）
- 编辑任务与多任务计划
- 执行任务、计划并记录日志
- 手动手控（0-4096 滑条）与在线监控

系统边界：
- 机械臂侧通过 `franka_msgs/PTPMotion` action 控制。
- 手侧通过 `omnihand` Python SDK 或 ROS service 控制。
- 点位、任务、计划通过 YAML 文件落盘与读取。

## 目的
- 让现场操作人员用 GUI 快速完成点位采集、任务编排和执行。
- 提供手动手控与自动执行共存的可控工作流，尽量减少总线冲突与误操作。
- 将手臂动作参数（速度、等待时间、回位策略）可配置化，降低现场调试门槛。

## 如何实现
- 主入口：`linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- 机械臂动作适配：`adapters/franka_ptp_client.py`
- 手动作适配：`adapters/omnihand_client.py`
- 臂状态读取：`joint_state_reader.py`
- 运行态排障脚本：`list_active_motion_jobs.py`（读取 `runtime/active_motion.json`）
- 调度约束：GUI 后台任务统一走串行调度（运行中拒绝新任务），避免并发下发多个 motion
- 测试排障能力：支持“暂停测试”逐步放行每个 arm motion，并支持取消当前测试
- 可视化观测：日志页内置运行状态面板，实时显示 active motion 与最近错误
- 运行方式（示例）：
  - `/bin/python linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`

## 能否实现 / 风险
- 已实现：点位/任务/计划全流程、手控、冲突拦截、弹窗提示、多选批量添加。
- 主要风险：
  - 现场 CAN 通信不稳定时，手侧读取与下发会失败。
  - Franka 控制器在状态竞争下可能出现 `status=6`（动作拒绝/中止）。
  - 机械臂与手同时控制时需严格避免多进程/多通道竞争；当前进程内已做串行闸门，但外部进程仍可能造成竞争。
  - 暂停测试的“取消”属于安全点中止：若当前 motion 已在控制器执行中，会在下一次下发前停止后续动作。
