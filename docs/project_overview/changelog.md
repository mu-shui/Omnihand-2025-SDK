# 项目变更记录（Changelog）

> 记录规则：按倒序追加（最新在最上）；时间格式统一为 `YYYY-MM-DD HH:mm TZ`。

## 2026-04-22 14:42 CST

- 变更摘要：
  - 新增 `l2_5_1_sensor_feedback_maxrate.py`，提供无 `sleep` 的满速触觉采样模式，按“调用返回时刻”记录 `elapsed_ms`。
  - 保留有效变化判定与异常字段，输出与原 L2-5-1 脚本一致风格的统计结果（采样间隔/有效间隔）。
  - 新增功能文档 `sensor-feedback-maxrate.md`，并同步更新总览与结构导航对新脚本的说明。
- 影响范围：
  - 新增一个 L2-5-1 扩展验证脚本与相关文档，不改变既有 SDK API 与原 `l2_5_1_sensor_feedback_frequency.py` 行为。
- 关联路径：
  - `scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
  - `docs/project_detailed/sensor-feedback-maxrate.md`
  - `docs/project_overview/overview.md`
  - `docs/project_overview/file-map.md`
  - `docs/project_overview/changelog.md`

## 2026-04-22 10:57 CST

- 变更摘要：
  - 调整 `l2_5_1_sensor_feedback_frequency.py` 的 CSV 输出结构，前半段字段与 `l2_4_1_tactile_o10.csv` 对齐：`elapsed_ms + 全量点位 + 分区求和 + total_sum`。
  - 保留有效刷新分析字段作为扩展列，并将差值字段统一为 `delta_total_sum`。
  - 在 O10 采样路径中改为按完整行解析与落盘，便于与 L2-4 数据做同结构对比。
- 影响范围：
  - 影响 L2-5-1 触觉 CSV 列结构与统计辅助字段命名，不影响 SDK 对外 API。
- 关联路径：
  - `scripts/validation/l2_5_1_sensor_feedback_frequency.py`

## 2026-04-22 10:32 CST

- 变更摘要：
  - 修复 `l2_5_1_sensor_feedback_frequency.py` 在 `delta_sum_raw` 计算阶段的类型判断缺陷，避免出现 `int - NoneType` 异常。
  - 新增数值类型检查函数，仅在前后两次 `sum_raw` 均为数值时才计算差值。
- 影响范围：
  - 影响 L2-5-1 脚本运行稳定性与 CSV 中 `delta_sum_raw` 字段计算逻辑；不影响 SDK 对外 API。
- 关联路径：
  - `scripts/validation/l2_5_1_sensor_feedback_frequency.py`

## 2026-04-22 10:25 CST

- 变更摘要：
  - 重构 `l2_5_1_sensor_feedback_frequency.py`：支持按 `--tactile-hz` 周期读取触觉数据并输出结构化 CSV。
  - 新增“有效数据变化”统计逻辑：基于多区域聚合值变化判定有效更新，输出有效间隔中位数、平均值、最小值与中位有效刷新频率。
  - 新增参数 `--change-threshold`、`--request-interval-ms`、`--log-interval`，并保留异常采样标记字段（`status/error`）用于复盘。
- 影响范围：
  - 影响 L2-5-1 验证脚本的数据采集节拍、统计口径与终端结果解释方式；不影响 SDK 对外 API。
- 关联路径：
  - `scripts/validation/l2_5_1_sensor_feedback_frequency.py`

## 2026-04-21 20:04 CST

- 变更摘要：
  - 新增工作区配置 `.vscode/settings.json`，将 `*.md` 明确关联到 Markdown 并使用默认编辑器打开，规避“文件可读模式/自定义编辑器”导致的打开异常。
  - 同步更新 `file-map.md`，补充该配置文件职责与维护触发场景。
- 影响范围：
  - 仅影响当前仓库在 Cursor/VSCode 的 Markdown 打开行为，不影响 SDK 运行时逻辑与对外 API。
- 关联路径：
  - `.vscode/settings.json`
  - `docs/project_overview/file-map.md`
  - `docs/project_overview/changelog.md`

## 2026-04-21 19:28 CST

- 变更摘要：
  - 在 `full-sensor-bandwidth-cpu.md` 补充实时日志字段逐项释义，并加入基于真实运行输出的示例解读。
  - 在同一文档补充 `MultiFrame timeout` 与 `Incomplete data (expected xx, got 10)` 的详细含义与诊断关系说明。
- 影响范围：
  - 功能文档解释能力增强，便于现场定位“频率正常但数据偶发不完整”的问题；不影响脚本执行逻辑。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `docs/project_overview/changelog.md`

## 2026-04-21 19:18 CST

- 变更摘要：
  - 在 `l2_4_1_full_sensor_bandwidth_cpu.py` 内补充参数说明（文件头说明 + `--help` 参数速览），覆盖默认值与用途。
  - 重构功能文档 `full-sensor-bandwidth-cpu.md`，新增参数说明、使用方式、输出字段与判定口径，强化联机可操作性。
- 影响范围：
  - 压测脚本使用说明与功能文档结构更新，不改变 SDK 对外 API。
- 关联路径：
  - `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `docs/project_overview/changelog.md`

## 2026-04-21 18:05 CST

- 变更摘要：
  - 按“新功能模块”判定，新建 `docs/project_detailed/full-sensor-bandwidth-cpu.md`，用于持续维护 O10 全量触觉带宽与并行动作压测功能。
  - 同步更新 `file-map.md`，补充该功能文档在项目结构导航中的职责说明。
- 影响范围：
  - 文档结构与导航完善，不影响 SDK 运行时行为与对外 API。
- 关联路径：
  - `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - `docs/project_overview/file-map.md`

## 2026-04-21 18:02 CST

- 变更摘要：
  - 更新 `l2_4_1_full_sensor_bandwidth_cpu.py` 的验证目标说明：仅聚焦 O10，全量触觉 Raw 连续请求与握拳/张开动作并行执行。
  - 明确脚本输出关注点：实时观测阻塞/丢数/频率跌落，CSV 仅保存触觉相关数据（含分区求和）。
- 影响范围：
  - 验证脚本职责与输出约定更新，不影响 SDK 对外 API。
- 关联路径：
  - `docs/project_overview/file-map.md`
  - `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`

## 2026-04-21 16:19 CST

- 变更摘要：
  - 按新文档规范创建 `docs/project_overview/`，新增 `overview.md`、`file-map.md`、`changelog.md`。
  - 新建 `docs/project_detailed/README.md`，定义功能文档命名与内容模板（中文，英文短横线文件名）。
  - 将“统一变更记录”明确收敛到 `docs/project_overview/changelog.md`。
- 影响范围：
  - 文档治理结构与维护流程更新；不影响 SDK 运行时行为与对外 API。
- 关联路径：
  - `docs/project_overview/overview.md`
  - `docs/project_overview/file-map.md`
  - `docs/project_overview/changelog.md`
  - `docs/project_detailed/README.md`
- 同步更新触发条件：
  - 每次代码、配置、脚本、文档有实际改动后，必须同步检查并更新本文件。
  - 新增原来不存在的功能时，必须在 `docs/project_detailed/` 新建对应 `<feature-name>.md`。
  - 若无法判断是否属于新功能，必须先向用户确认后再决定是否新建功能文档。
