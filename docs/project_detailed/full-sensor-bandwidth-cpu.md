# 全量触觉带宽与并行动作压测（O10）

## 该功能的总实现目标

- 在 O10 设备上，以目标频率连续读取全量触觉 Raw 数据，同时并行执行握拳/张开动作循环。
- 在同一测试任务中识别长期阻塞、数据丢失、刷新频率跌落现象，支撑总线负载与稳定性评估。
- 产出可复盘 CSV：从程序启动时刻开始计时，记录全部触觉原始点位与各区域求和。

## 功能入口与关联脚本

- 主脚本：`scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`
- 参考动作脚本：`linux/x64/python/demo/omnihand_2025/demo_set_get_fist_reliability_csv.py`
- 参考触觉脚本：`linux/x64/python/demo/omnihand_2025/demo_tactile_sensor.py`

### 与 L2-5-1 的底层读取接口关系

- 本脚本（L2-4-1）在主循环中使用 `hand.get_all_tactile_sensor_data_raw()` 读取 O10 全量触觉 Raw 数据。
- `scripts/validation/l2_5_1_sensor_feedback_frequency.py` 在 `--product o10` 分支下同样使用 `hand.get_all_tactile_sensor_data_raw()`。
- 因此两者在 O10 下共享同一条 Raw 读取链路：若出现 `MultiFrame timeout / Incomplete data`，通常会在两脚本中同时出现。
- 说明：两脚本不是调用 `linux/x64/python/demo/omnihand_2025/demo_tactile_sensor_raw.py` 这个 demo 文件；它们与该 demo 一样，都是直接调用 `omnihand` SDK 接口。

## 实现步骤（当前步骤：Step 4）

1. Step 1：确定测试输入（设备连接参数、测试时长、目标触觉频率）。
2. Step 2：实现并行动作线程，循环执行“握拳/张开”目标位姿。
3. Step 3：实现全量触觉高频采样、实时状态输出、触觉专用 CSV 导出。
4. Step 4：联机验证与阈值调优（根据现场总线负载调整 `tactile-hz`、`drop-multiplier`、`block-threshold-s`）。

## 参数说明（脚本内置）

- `--hand {left,right}`：左右手，默认 `left`
- `--hand-device-id`：默认 `1`
- `--canfd-device-id`：默认 `0`
- `--canfd-channel-id`：默认 `0`
- `--duration`：测试时长（秒），默认 `10.0`
- `--tactile-hz`：目标触觉频率 Hz，默认 `50.0`
- `--request-interval-ms`：SDK 最小请求间隔，默认 `2`
- `--motion-hold-s`：握拳/张开每个姿态保持时长，默认 `0.7`
- `--log-interval`：实时日志打印周期（秒），默认 `1.0`
- `--drop-multiplier`：频率跌落判定倍数，默认 `2.0`
- `--block-threshold-s`：长期阻塞阈值（秒），默认 `0.5`
- `-o / --output`：输出 CSV 文件名，默认 `l2_4_1_tactile_o10.csv`

## 使用方式

- 查看参数帮助：
  - `python3 scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py --help`
- 默认测试：
  - `python3 scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`
- 20Hz 连续 30 秒并指定输出文件：
  - `python3 scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py --tactile-hz 20 --duration 30 -o tactile_20hz_30s.csv`

## 输出与判定口径

- 实时输出：
  - 触觉分区实时求和预览（thumb/index/middle/ring/little/palm/dorsum）
  - 丢数事件计数（`data_loss`）
  - 频率跌落计数（`freq_drop`）
  - 长期阻塞计数（`block`）
  - CPU 占用率（终端显示，不写入 CSV）
- CSV 输出：
  - `elapsed_ms`
  - 全部触觉原始值列（按分区展开）
  - 各分区求和列（`*_sum`）
  - `total_sum`
- O10 各区域原始点位数量（Raw）：
  - `thumb`: 16
  - `index`: 18
  - `middle`: 18
  - `ring`: 18
  - `little`: 18
  - `palm`: 78
  - `dorsum`: 102
- 判定口径：
  - `dt > tactile_period * drop_multiplier` 记为一次频率跌落
  - `dt > block-threshold-s` 记为一次长期阻塞

## 实时日志字段解释（详细）

以下为脚本每隔 `log-interval` 打印的一行状态：

- 示例行：
  - `t=25.27s samples=502 data_loss=4 freq_drop=0 block=0 inst_hz=20.0 avg_hz=19.9 cpu%=6.7 | thumb:0, index:0, middle:0, ring:0, little:0, palm:0, dorsum:0`
- 字段含义：
  - `t=25.27s`：从脚本启动算起已运行 25.27 秒。
  - `samples=502`：已完成 502 次触觉采样循环（每次循环尝试读取一次全量触觉）。
  - `data_loss=4`：累计出现 4 次“数据不完整事件”（例如某分区缺失、长度不足、或读取异常）。
  - `freq_drop=0`：累计 0 次“频率明显跌落”事件（`dt > period * drop_multiplier`）。
  - `block=0`：累计 0 次“长期阻塞”事件（`dt > block-threshold-s`）。
  - `inst_hz=20.0`：最近一个采样间隔换算的瞬时频率约 20Hz。
  - `avg_hz=19.9`：从启动到当前时刻的平均采样频率约 19.9Hz。
  - `cpu%=6.7`：当前 CPU 利用率快照（仅终端显示，不写入 CSV）。
  - `| thumb:... dorsum:...`：当前采样周期各触觉分区的求和值快照（单位由 SDK 定义，常用于观察刷新是否“卡死”）。
- 示例解读（以上述行为例）：
  - 在 25 秒时系统仍稳定接近目标 `20Hz`；
  - 全程无频率跌落/长期阻塞；
  - 但出现了 4 次数据不完整事件，需要结合下方 Warning/Debug 日志排查总线多帧响应稳定性。

## Warning/Debug 日志解释（详细）

你提供的典型日志如下：

- `[DEBUG][MultiFrame] timeout waiting for frame 1/5 ... frames_received=1 ...`
- `[Warning]: Incomplete data for sensor 4, expected 18 bytes, got 10`
- `[Warning]: Incomplete data for sensor 5, expected 18 bytes, got 10`
- `[Warning]: Incomplete data for sensor 6, expected 78 bytes, got 10`
- `[Warning]: Incomplete data for sensor 7, expected 102 bytes, got 10`

解释：

- `MultiFrame timeout waiting for frame 1/5`：
  - 底层正在等待一条需要多帧拼包的响应（总计预期 5 帧），但在超时窗口内只收到部分帧（日志里可见 `frames_received=1`）。
  - 这是 SDK 底层的多帧通信调试信息，通常说明该次请求响应未完整到达。
- `expected xx bytes, got 10`：
  - 某些触觉分区本次仅拿到 10 字节，而该分区协议期望字节数更高（18/78/102）。
  - 因此该次采样被记为一次 `data_loss` 事件。
- 为什么脚本还在继续跑：
  - 这是“单次采样不完整”，不是进程级致命错误；脚本设计为持续压测，记录异常并继续后续采样。
- 与汇总指标的关系：
  - 每发生一次这类不完整采样，`data_loss` 会增加；
  - 如果采样周期仍保持在阈值内，`freq_drop` 与 `block` 可能仍为 0（你这次日志就是这种情况）。

## 更新日志

### 2026-04-22 14:24 CST

- 变更内容：
  - 新增“与 L2-5-1 的底层读取接口关系”章节，明确 L2-4-1 与 L2-5-1 在 O10 下都调用 `hand.get_all_tactile_sensor_data_raw()`。
  - 补充“不是调用 `demo_tactile_sensor_raw.py` 文件，而是共同调用 `omnihand` SDK 接口”的说明。
- 本次推进步骤：Step 4（保持）
- 影响范围：
  - 文档链路说明增强，便于跨脚本定位同源通信问题，不改变代码行为。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`
  - `scripts/validation/l2_5_1_sensor_feedback_frequency.py`

### 2026-04-22 11:10 CST

- 变更内容：
  - 在“输出与判定口径”中补充 O10 触觉各区域原始点位数量（thumb/index/middle/ring/little/palm/dorsum）。
- 本次推进步骤：Step 4（保持）
- 影响范围：
  - 文档解释信息增强，便于核对 `len(data)` 与 CSV 列长度，不改变脚本逻辑。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`

### 2026-04-21 19:28 CST

- 变更内容：
  - 新增“实时日志字段解释（详细）”，逐项说明 `t/samples/data_loss/freq_drop/block/inst_hz/avg_hz/cpu%/分区sum` 的语义与判读方式。
  - 新增“Warning/Debug 日志解释（详细）”，解释 `MultiFrame timeout` 与 `Incomplete data ... expected xx got 10` 的含义及与 `data_loss` 的关系。
  - 增加基于实际运行日志的示例解读，明确“频率稳定但存在偶发数据不完整”这一诊断结论。
- 本次推进步骤：Step 4（保持）
- 影响范围：
  - 功能文档可解释性增强，便于现场测试人员快速定位日志含义，不改变脚本逻辑。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`

### 2026-04-21 19:18 CST

- 变更内容：
  - 重构功能文档结构，补充“功能入口、参数说明、使用方式、输出与判定口径”。
  - 参数清单与脚本内置帮助保持一致，降低联机测试使用门槛。
- 本次推进步骤：Step 4（保持）
- 影响范围：
  - 功能文档可读性与可执行性增强，不改变脚本控制逻辑。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`

### 2026-04-21 18:05 CST

- 变更内容：
  - 新建本功能文档，定义 O10 全量触觉并行动作压测的目标、步骤与交付物。
  - 将当前实现状态标记到 Step 4（已具备脚本能力，待按现场负载做联机调优）。
- 本次推进步骤：Step 1 -> Step 4
- 影响范围：
  - 功能级文档体系新增一个可持续维护条目，不改变运行时代码行为。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`
