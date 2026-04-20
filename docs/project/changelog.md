# 变更记录（最新在上）

## 2026-04-20 18:05

- 新增“暂停测试”能力（方案A）：
  - 在初始化页新增 `开启暂停测试 / 继续下一步 / 取消测试` 控件；
  - 暂停模式下，每个 arm motion 在下发前会停住，支持逐步放行用于排查多任务序列问题；
  - `取消测试` 会中止当前任务后续动作，避免继续下发新 motion。
- 新增 GUI 内置运行状态面板（替代外部终端查看）：
  - 在日志页新增“任务运行状态”区域，实时显示 `runtime/active_motion.json`；
  - 可直接看到 `running`、当前动作、最近一次错误、暂停测试状态等信息。
- 运行状态文件增强：
  - `active_motion.json` 新增 `pause_test` 字段（enabled/cancel_requested/waiting_context）。
- 调度异常处理增强：
  - 新增 `PauseTestCancelledError`，取消测试时标记为 `cancelled`，不再按普通失败处理。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `docs/project/changelog.md`
- `docs/project/file-map.md`
- `docs/project/overview.md`

## 2026-04-20 17:39

- 修复 GUI 异步执行竞态，改为严格串行拒绝新任务：
  - `MainApp._run_async()` 在主线程原子设置运行态（加锁），从源头避免“几乎同时点击”触发双线程并发下发 motion。
  - 运行中再次触发会直接提示“已有任务在运行，请稍后”，并在控制日志记录被拒绝任务与当前运行任务信息。
- 新增运行态可观测能力：
  - GUI 会持续写入 `runtime/active_motion.json`（当前运行任务 / 最近一次任务结果）。
  - 新增 `list_active_motion_jobs.py` 脚本用于命令行查看当前发放任务，支持 `--watch` 连续刷新。
- 在 `RobotExecutor` 增加机械臂 motion 级闸门（non-blocking lock）：
  - 一旦检测到并发 motion 请求，立即拒绝并抛错，避免并行进入 `send_goal_and_wait()`。
- 扩展 `status=6` 瞬时重试匹配条件：
  - `FrankaPTPClient` 现在同时识别 `unexpected motion started` 与 `attempted to start multiple motions` 两类报错文案。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/adapters/franka_ptp_client.py`
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/list_active_motion_jobs.py`
- `docs/project/changelog.md`

## 2026-04-20 16:23:27

- 按“多任务=串联单任务步骤”重构 `execute_plan()`：
  - 不再在计划执行中嵌套调用 `execute_task()`；
  - 改为在计划内直接按任务顺序展开并串行执行每个步骤（arm -> hand -> hold -> 可选手回位）。
- 目的：减少计划模式下嵌套调度导致的运动起动竞争，贴合“把单任务步骤连起来执行”的预期语义。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `docs/project/changelog.md`

## 2026-04-16（计划执行重复启动进一步修复）

- 修复 `execute_plan()` 的双重回初始位问题：
  - 当 `task_reset_enabled=true` 时，不再在计划开始处额外回初始位；
  - 由“每个任务前回初始位”单一路径负责，避免第一轮出现 back-to-back motion。
- 调整 `save_plan()`：
  - 新增参数 `popup`（默认 `True`）；
  - `run_plan()` 内部调用改为 `save_plan(popup=False)`，避免执行前弹“保存成功”干扰排错。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `docs/project/changelog.md`

## 2026-04-16（多任务连续启动修复）

- 修复计划执行中机械臂重复起动风险：
  - `execute_task()` 新增参数 `go_home_after`（默认 `True`）。
  - 在 `execute_plan()` 中调用任务时传入 `go_home_after=False`，避免“任务末尾回初始位”和“计划层回位”叠加导致 back-to-back motion。
- 目标是降低 `PTPMotion failed (status=6): Attempted to start multiple motions!` 的触发概率。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `docs/project/changelog.md`

## 2026-04-16（通道状态修复）

- 修复手控通道状态判断：从 `raw_hand is not None` 改为 `raw_hand_connected`，避免“对象存在但未初始化成功”时误走 raw 通道。
- 修复滑条隐式连手问题：未初始化手控时，滑条变更不再自动触发底层发送。
- 调整点位管理动作前检查逻辑：
  - 手控已连接时，不再调用 `ensure_hand_ready_or_warn()` 去抢另一套 hand client。
  - 手控未连接时仍走原有 ready 检查。
- 调整执行任务/执行计划冲突判断为基于 `raw_hand_connected`，减少误拦截或漏拦截。
- `同步当前位置到滑条` 增加前置检查：未初始化手控时给出提示，不再隐式创建连接。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `docs/project/changelog.md`

## 2026-04-16

- 新增手控页按钮 `同步当前位置到滑条`，支持一键将滑条值对齐设备当前关节位置。
- 新增 `sync_hand_positions()` 与 `_sync_hand_positions_worker()`：
  - 读取 `get_all_joint_positions()`
  - 校验长度并裁剪到 0~4096
  - 使用 `_hand_updating_from_device` 进行无副作用批量写回滑条
- 新增 `docs/project/overview.md`、`docs/project/file-map.md`，并建立文档约定。

影响范围：
- `linux/x64/ros2/humble/src/hand_arm_task_runner/hand_arm_task_runner/gui_app.py`
- `docs/project/overview.md`
- `docs/project/file-map.md`
- `docs/project/changelog.md`
