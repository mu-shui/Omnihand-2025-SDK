# 文件导航

## 目录结构（关键部分）
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/`
  - `gui_app.py`：主 GUI，包含初始化、点位、任务、计划、手控、日志
  - `joint_state_reader.py`：读取机械臂 `/joint_states` 并返回前 7 关节
  - `models.py`：点位模型与 YAML 读写
  - `adapters/franka_ptp_client.py`：机械臂 PTP action 调用与结果处理
  - `adapters/omnihand_client.py`：手后端（python_sdk / ros_service）封装
  - `list_active_motion_jobs.py`：读取 `runtime/active_motion.json`，输出当前运行任务状态（支持 watch）
- `docs/project/`
  - `overview.md`：项目目标、边界、风险
  - `file-map.md`：文件职责导航
  - `changelog.md`：变更记录

## 关键文件职责
- `gui_app.py`
  - 负责 UI 与业务编排，调用 `RobotExecutor` 执行动作。
  - 何时修改：新增按钮、交互逻辑、任务执行顺序、冲突保护、运行态可观测（状态文件）策略、暂停测试流程。
- `joint_state_reader.py`
  - 负责从 ROS topic 读取机械臂关节状态。
  - 何时修改：记录点位的臂关节采样策略变化、超时策略变化。
- `adapters/franka_ptp_client.py`
  - 封装 goal 发送、等待、错误码处理。
  - 何时修改：PTP 重试机制、超时策略、状态码处理策略变化。
- `list_active_motion_jobs.py`
  - 负责命令行读取/展示 GUI 运行状态，辅助排查“当前是否并发发放任务”。
  - 何时修改：状态文件字段变更、排障输出格式变更、watch 逻辑变更。
- `adapters/omnihand_client.py`
  - 封装手角度读写与就绪检测。
  - 何时修改：手通信后端切换、异常识别、读写行为变化。

## 关键函数/类（名称 + 作用 + 原理）
- `RobotExecutor._go_home()`
  - 作用：执行回初始位（手、臂及等待节奏）。
  - 原理：先手后臂，加入手稳定等待和臂稳定等待，降低机械/控制冲突。
- `RobotExecutor._set_hand_angles()`
  - 作用：统一手下发入口，按当前通道自动选择 `raw_hand` 或 `OmniHandClient`。
  - 原理：手控开启时优先 raw_hand，避免双通道竞争同一 CAN。
- `MainApp.sync_hand_positions() / _sync_hand_positions_worker()`
  - 作用：将滑条值同步为手当前位置。
  - 原理：读取 `get_all_joint_positions()`，批量更新 `hand_pos_vars`，并通过 `_hand_updating_from_device` 防止触发二次下发。
- `MainApp._run_async()`
  - 作用：统一后台任务调度，强制“同一时刻仅允许一个任务运行”。
  - 原理：主线程先加锁并原子设置 `running`，同时写入 `runtime/active_motion.json`，结束后记录最后一次任务结果。
- `MainApp.wait_for_pause_test_gate()`
  - 作用：在每个 arm motion 下发前执行“暂停测试闸门”，支持继续/取消测试。
  - 原理：通过线程事件和状态锁控制放行；取消测试会抛出 `PauseTestCancelledError`，终止后续步骤。
