# 触觉反馈最大速率采样（L2-5-1 MaxRate）

当前步骤：4/4（已完成）

## D1. 功能总实现目标

- 解决问题：在不做脚本层定频（不 `sleep`）的情况下，测量触觉接口“请求-返回”链路能够达到的实际采样速率，并与定频脚本口径区分。
- 最终形态：提供独立脚本 `l2_5_1_sensor_feedback_maxrate.py`，持续读取触觉数据并在 CSV 中记录“返回时刻”时间戳、有效变化统计与异常状态。
- 交付标准：
  - 脚本支持 O10/O12、ZLGCAN/SocketCAN 连接参数。
  - CSV 字段包含 `elapsed_ms`、全量触觉区数据、分区求和、有效更新字段与错误字段。
  - 终端输出采样间隔中位数/平均值、采样中位频率、有效更新间隔统计。

## D2. 预期实现步骤（Plan 模式）

### 不确定项 / 待确认选项

- 是否默认将 `--request-interval-ms` 固定为 `1`：
  - 方案 A：默认 `0`（当前实现）。优点是测“链路上限”；缺点是不同主机负载下可重复性略弱。
  - 方案 B：默认 `1`。优点是口径更稳定；缺点是引入人为节流，不再是纯最大速率。
- O12 路径是否需要扩展到与 O10 一样的全量分区：
  - 方案 A：延续当前脚本，仅采 `thumb/index` 3D force。优点是实现稳定；缺点是与 O10 可比性有限。
  - 方案 B：补齐更多 O12 区域采集。优点是口径统一；缺点是依赖更多底层接口能力。

### 分步骤计划（一步一动作）

✅ 已完成 Step 1：复制并保留原有连接/解析基础能力
- 步骤目标：在不破坏原 L2-5-1 脚本的前提下，建立独立 MaxRate 脚本并复用连接、数据解析、统计函数。
- 涉及文件 / 模块：`scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
- 具体操作动作：保留 `connect_hand`、`_parse_o10_row`、`_collect_o10/_collect_o12`、统计函数与 CSV 字段组织逻辑。
- 依赖前置：已有 L2-5-1 稳定运行。
- 验收标准：`python3 ... --help` 正常，脚本可成功连接并输出 CSV 表头。
- 风险点：复制后若遗漏辅助函数，运行期会出现 `NameError`。

✅ 已完成 Step 2：切换到“最大速率采样”主循环
- 步骤目标：移除脚本层定频节流，改为“调用完成即下一轮”。
- 涉及文件 / 模块：`scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
- 具体操作动作：删除 `--tactile-hz` 与 `period/sleep` 逻辑，循环仅由 `duration` 终止条件控制。
- 依赖前置：Step 1 完成。
- 验收标准：代码中无 `time.sleep` 节流路径，实测 `avg_sample_hz` 显著高于低频定频采样场景。
- 风险点：满速采样会提升总线与 CPU 负载，数据抖动与偶发丢帧可能增加。

✅ 已完成 Step 3：将 `elapsed_ms` 定义为“调用返回时刻”
- 步骤目标：时间戳语义对齐 set/get 可靠性脚本，避免把“调用发起时刻”误当回包时刻。
- 涉及文件 / 模块：`scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
- 具体操作动作：先执行 SDK 读取，返回后再用 `perf_counter` 计算 `elapsed_ms`；同时用该时刻写入 `sample_ts/effective_ts`。
- 依赖前置：Step 2 完成。
- 验收标准：CSV 连续 `elapsed_ms` 差值可直接解释为“相邻返回间隔（ms）”。
- 风险点：O12 路径包含多次接口调用，时间戳反映的是整轮采集完成时刻。

✅ 已完成 Step 4：补全文档与仓库级导航
- 步骤目标：确保新脚本可被快速发现、理解和复用。
- 涉及文件 / 模块：
  - `docs/project_detailed/sensor-feedback-maxrate.md`
  - `docs/project_overview/overview.md`
  - `docs/project_overview/file-map.md`
  - `docs/project_overview/changelog.md`
- 具体操作动作：新增功能文档并更新总览、结构导航与统一变更记录。
- 依赖前置：Step 3 完成。
- 验收标准：文档齐全且中文；`changelog` 含时间、摘要、影响范围、关联路径。
- 风险点：若后续字段调整未同步文档，会导致统计口径理解偏差。

### Mermaid 流程图

```mermaid
flowchart TD
    A[输入参数: 连接信息/时长/阈值/请求最小间隔] --> B[创建设备并 init]
    B -->|失败| X1[打印错误并退出]
    B -->|成功| C[set_request_interval]
    C --> D[进入 while(duration) 主循环]
    D --> E[调用触觉读取接口]
    E --> F[返回后记录 sample_time 与 elapsed_ms]
    F --> G[写入 CSV 行: 数据+状态+有效变化字段]
    G --> H{到达时长上限?}
    H -->|否| D
    H -->|是| I[计算 sample/effective 间隔统计并打印]
    E -->|异常| X2[写入 error 行并继续]
```

## D3. 当前代码详解

### 文件与入口

- 文件：`scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
- 入口：`main()`
- 实现原理：
  - 复用原 L2-5-1 的连接与数据解析逻辑；
  - 改为“无 sleep”循环，持续触发接口读取；
  - 在每次读取返回后记录时间戳并落盘；
  - 基于区域和变化阈值判定有效更新。

### 调用链路

- CLI 参数解析 -> `connect_hand(args)` -> `hand.set_request_interval(...)`
- 主循环读取：
  - O10：`get_all_tactile_sensor_data_raw()` -> `_parse_o10_row(...)`
  - O12：`get_tactile_sensor_3d_data(Finger.THUMB/INDEX)` -> 组装行数据
- 回包后打点 `elapsed_ms` -> 写 CSV -> 计算有效变化 -> 周期日志打印
- 退出后统计 `sample_dt/effective_dt`

### 关键参数

- `--duration`：
  - 类型：`float`，单位秒；默认 `10.0`
  - 含义：总采样时长，不影响单轮节拍。
- `--request-interval-ms`：
  - 类型：`int`，单位毫秒；默认 `0`
  - 含义：SDK 层最小请求间隔。`0` 表示尽快请求。
- `--change-threshold`：
  - 类型：`int`；默认 `0`
  - 含义：有效变化阈值，`abs(delta)` 超过阈值才计为变化。
- `--log-interval`：
  - 类型：`float`，单位秒；默认 `1.0`
  - 含义：终端状态打印间隔。

### 输入 / 输出

- 输入：
  - 设备触觉接口返回值（O10 全量 Raw / O12 3D force）。
  - CLI 连接参数、时长与阈值参数。
- 输出：
  - CSV：含 `elapsed_ms`、分区点位、分区求和、`is_effective_update`、`status/error`。
  - 终端：`avg_sample_hz` 与最终间隔统计。

### 边界条件与常见误区

- 边界条件：
  - 当部分区域无数据时，`status=invalid`，对应字段为空并计入 `data_loss_events`。
  - 有效变化次数不足 2 次时，无法计算有效更新间隔统计。
- 常见误区：
  - `elapsed_ms` 不是设备原生时间戳，而是脚本本地单调时钟的相对时间。
  - “每 1ms 一个样本”不代表手部动作完成，仅代表一次请求返回完成。

### 现象与原因定位（实测）

- 典型现象（命令：`python3 scripts/validation/l2_5_1_sensor_feedback_maxrate.py --product o10 --link zlgcan --duration 1`）：
  - 日志持续出现 `MultiFrame timeout waiting for frame 1/5`。
  - 同时出现 `Incomplete data for sensor X, expected xx bytes, got 10`。
  - 汇总结果表现为 `samples=22 valid=11 data_loss=11`，`sample_interval_median≈51ms`，频率约 `20Hz`。
- 根因解释：
  - 脚本确实在“持续请求”，但 O10 全量触觉 Raw 响应属于多帧拼包链路。
  - 当前链路下，多帧响应经常只收到首帧（10 字节）就超时，导致该轮样本被判定为 `invalid`。
  - 因此 `data_loss` 持续上升，本质是“响应不完整”，不是“脚本没有发请求”。
- 为什么与 `set_get` 的 ~1ms 不同：
  - `set/get` 关节位置接口数据量小、交互轻，单次请求-返回可接近 1ms。
  - `get_all_tactile_sensor_data_raw()` 返回数据量大、依赖多帧拼包，天然更慢且更易受总线/超时窗口影响。
- 结论：
  - 当前瓶颈主要在触觉多帧通信链路（设备刷新周期 + 总线传输 + SDK 拼包等待策略），而非 Python 主循环节流。
  - `request_interval_ms=0` 只表示“尽快发请求”，不保证“每 1ms 必有完整全量触觉回包”。

## D4. 使用方法

- 入口脚本：
  - `scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
- 常用命令：
  - 查看帮助：
    - `python3 scripts/validation/l2_5_1_sensor_feedback_maxrate.py --help`
  - O10 + ZLGCAN + 10 秒满速：
    - `python3 scripts/validation/l2_5_1_sensor_feedback_maxrate.py --product o10 --link zlgcan --duration 10 -o l2_5_1_sensor_feedback_maxrate.csv`
  - 限制 SDK 最小请求间隔为 1ms：
    - `python3 scripts/validation/l2_5_1_sensor_feedback_maxrate.py --request-interval-ms 1 --duration 10`

适用场景：
- 评估触觉接口在当前主机+总线+设备状态下的采样速率上限。
- 对比“定频采样脚本”与“满速采样脚本”的间隔分布差异。
- 排查高负载下的异常样本、丢数和有效更新抖动。

## D5. 参数说明

- `--product`
  - 含义：设备型号路径；默认 `o10`
  - 可选：`o10/o12`
  - 影响：决定触觉采集接口与数据解析分支。
- `--hand`
  - 含义：左右手选择；默认 `left`
  - 可选：`left/right`
  - 影响：创建设备时使用的手型。
- `--link`
  - 含义：通讯链路类型；默认 `zlgcan`
  - 可选：`zlgcan/socketcan`
  - 影响：决定底层建链函数与参数解释方式。
- `--request-interval-ms`
  - 含义：SDK 最小请求间隔（ms）；默认 `0`
  - 可选：整数 `>=0`
  - 影响：值越小越趋向满速，CPU/总线压力更高。
- `--duration`
  - 含义：采样持续时长（秒）；默认 `10.0`
  - 可选：正数
  - 影响：样本量与统计稳定性。
- `--change-threshold`
  - 含义：有效变化阈值；默认 `0`
  - 可选：整数 `>=0`
  - 影响：阈值越高，有效更新次数通常越少。
- `--log-interval`
  - 含义：日志打印间隔（秒）；默认 `1.0`
  - 可选：`>=0.2` 实际生效更明显
  - 影响：调试可视化频率，不影响 CSV 内容。
- `-o/--output`
  - 含义：输出 CSV 路径；默认 `l2_5_1_sensor_feedback_maxrate.csv`
  - 可选：任意可写路径
  - 影响：决定结果文件保存位置。

## D6. 输入输出说明

### 输入

- 来源：
  - 设备触觉接口返回。
  - 命令行参数。
- 格式与字段：
  - O10：多区域 Raw 数据集合（`thumb/index/middle/ring/little/palm/dorsum`）。
  - O12：当前脚本聚焦 `thumb/index` 的 `normal_force`。
- 约束：
  - `request_interval_ms` 应为非负整数；
  - `duration` 需为正数；
  - 设备链路需先初始化成功。

### 输出

- CSV 关键字段：
  - `elapsed_ms`：从脚本起点到“本次读取返回”的相对时间（毫秒）。
  - `*_sum`：各区域求和；例如 `thumb_sum` 表示拇指区域总和。
  - `total_sum`：所有有效区域的总和。
  - `is_effective_update`：是否判定为有效变化（0/1）。
  - `effective_change_count`：本样本相对上样本发生变化的区域数量。
  - `changed_regions`：变化区域名（`|` 分隔）。
  - `delta_total_sum`：本次 `total_sum` 相对上次差值。
  - `status`：`ok/invalid/error`。
  - `error`：异常信息字符串（仅错误时非空）。
- 去向：
  - 本地 CSV 文件（由 `--output` 决定）。
  - 终端统计摘要。
- 异常情况：
  - 链路初始化失败：脚本退出并打印失败原因。
  - 单轮采样异常：写入 `error` 行并继续执行后续采样。

## D7. 更新日志

### 2026-04-22 15:12 CST

- 改了什么：
  - 在 D3 新增“现象与原因定位（实测）”章节，归档 1 秒实测中 `samples=22/valid=11/data_loss=11` 的表现。
  - 明确 `MultiFrame timeout` 与 `Incomplete data` 对 `status=invalid` 和 `data_loss` 的触发关系。
  - 解释“为何 `set_get` 可接近 1ms，而全量触觉 Raw 常见约 20Hz”的链路差异。
- 为什么改：
  - 避免将“持续请求”误解为“必然高频完整回包”，帮助快速区分脚本节拍问题与多帧通信瓶颈。
- 影响范围：
  - 仅文档说明增强，不改变 `l2_5_1_sensor_feedback_maxrate.py` 代码行为。

### 2026-04-22 14:42 CST

- 改了什么：
  - 新增 `l2_5_1_sensor_feedback_maxrate.py`，提供无 `sleep` 的最大速率触觉采样模式。
  - 将 `elapsed_ms` 口径定义为“SDK 读取调用返回后打点”。
  - 保留有效更新判定字段与异常字段，兼容既有分析方式。
- 为什么改：
  - 对齐 set/get 可靠性脚本的“返回时刻”统计语义，避免把定频采样口径与满速采样口径混用。
- 影响范围：
  - 新增脚本与文档，不改变原 `l2_5_1_sensor_feedback_frequency.py` 既有行为。
  