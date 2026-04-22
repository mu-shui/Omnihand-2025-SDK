# 项目结构导航（File Map）

## 目录/文件结构

- `doc/`
  - 官方说明文档（中英文 API、快速开始、排障）。
- `docs/project_overview/`
  - 项目级总览、结构导航、统一变更记录。
- `docs/project_detailed/`
  - 按功能拆分的详细实现说明与功能级更新日志。
- `linux/x64/`
  - Linux 发布产物、安装脚本、Python 轮子与 ROS2 资源。
- `windows/x64/`
  - Windows 发布产物与平台相关资源。
- `scripts/validation/`
  - 验证脚本、测试日志、分析图表输出目录。

## 关键文件职责（文件一句话 + 何时修改）

- `linux/x64/install.sh`
  - 负责 Linux 运行时安装；当安装步骤、依赖版本或安装顺序变化时修改。
- `linux/x64/ros2/setup.bash`
  - 负责 ROS2 环境变量与路径装配；当 ROS2 包布局变化时修改。
- `scripts/validation/README.md`
  - 描述验证脚本范围与使用方式；当验证策略或入口变更时修改。
- `scripts/validation/l2_2_1_joint_sweep_0_4095_check.py`
  - 执行关节扫描验证；当角度范围、判定规则、输出格式变化时修改。
- `scripts/validation/l2_1_2_comm_frequency_packet_loss.py`
  - 执行通讯频率与丢包验证；当通讯阈值或统计方法变化时修改。
- `scripts/validation/l2_4_1_full_sensor_bandwidth_cpu.py`
  - 在 O10 上以目标频率连续请求全量触觉 Raw 数据，并行执行握拳/张开动作，实时观察阻塞/丢数/频率跌落并输出触觉 CSV；当触觉压力测试口径、动作编排或 CSV 字段变化时修改。
- `scripts/validation/l2_5_1_sensor_feedback_frequency.py`
  - 以可配置频率轮询触觉数据并自动统计“有效数据间隔/中位有效刷新频率”；当有效更新判定口径、阈值策略或 CSV 字段变化时修改。
- `scripts/validation/l2_5_1_sensor_feedback_maxrate.py`
  - 以无 `sleep` 的满速模式读取触觉反馈，并按“调用返回时刻”记录 `elapsed_ms` 与有效变化统计；当最大速率采样口径、时间戳语义或 CSV 字段变化时修改。
- `docs/project_overview/overview.md`
  - 记录项目目标、边界、主链路与风险；当目标/约束/运行方式变化时修改。
- `docs/project_overview/changelog.md`
  - 统一记录仓库级变更；每次实际改动后必须追加。
- `.vscode/settings.json`
  - 约束工作区编辑器行为（含 Markdown 文件关联与打开方式）；当出现文件类型误关联或编辑器打开异常时修改。
- `docs/project_detailed/full-sensor-bandwidth-cpu.md`
  - 记录 O10 全量触觉带宽与并行动作压测功能的目标、步骤与更新日志；当压测口径、动作策略或 CSV 结构调整时修改。
- `docs/project_detailed/sensor-feedback-frequency.md`
  - 记录 L2-5-1 触觉有效刷新频率统计功能（有效变化判定、自动统计、使用方法与更新日志）；当统计口径、参数语义或运行流程变化时修改。
- `docs/project_detailed/sensor-feedback-maxrate.md`
  - 记录 L2-5-1 最大速率采样功能（返回时刻打点、无节流循环、有效变化判定与统计口径）；当主循环节拍策略、字段定义或判定规则变化时修改。
- `docs/project_detailed/set-get-fist-reliability-csv.md`
  - 记录握拳/张开 Set+Reply 可靠性 CSV 功能的实现目标、使用方法与参数约束；当该脚本的动作流程、CSV 字段或参数语义变化时修改。

  以下脚本在/home/agiuser/文档/Omnihand-2025-SDK-dev-release-firmware/linux/x64/python/demo/omnihand_2025出现
  demo_100set_and_20tactile_reliability.py：100Hz 关节位置下发 + 10Hz 触觉读取联合可靠性测试，统计失败率与循环耗时；当要验证“控制与传感并行负载”稳定性时修改。
demo_all_tactile_sensor_raw_reliability.py：单次请求批量读取全部触觉 Raw 数据并做长时间可靠性统计；当要评估 get_all_tactile_sensor_data_raw() 稳定性时修改。
demo_canfd_id.py：基于 canfd_device_id 创建设备，覆盖单手/双手综合控制（设备信息、传感、角度控制）；当设备按索引接入时作为首选连通性脚本。
demo_canfd_serial.py：基于 USB-CAN 序列号创建设备，覆盖单手/双手综合控制；当现场存在多适配器、需要按序列号精确绑定时修改。
demo_get_hardware_info.py：读取并打印厂商信息与设备通信参数；当排查设备识别、版本、配置问题时使用。
demo_monitor_current.py：读取单关节与全部关节电流报告；当验证电流回传链路或做电流监控接入时修改。
demo_monitor_error.py：读取单关节与全关节错误报告（如 motor_except）；当做故障告警映射时修改。
demo_monitor_temperature.py：读取单关节与全关节温度报告；当做温升监测或保护阈值验证时修改。
demo_set_angle.py：基于角度接口执行 reset -> fist -> reset 动作序列并回读角度；当验证角度控制基本闭环时使用。
demo_set_angle_and_tactile_sensor_reliability.py：在同一循环中执行“设角度 + 读角度 + 读触觉 Raw”并统计综合可靠性/时延；当验证复合业务负载稳定性时修改。
demo_set_get_fist_reliability_csv.py：交替下发“握拳/张开”位置并记录请求与回包到 CSV；当需要动作序列可回放日志时修改。
demo_set_get_reliability_csv.py：循环下发关节位置并将指令值/回包值写入 CSV；当需要量化位置跟踪一致性时修改。
demo_set_motion.py：交互式手势菜单（预置动作编号）并回读实际角度；当需要快速人工测试多手势切换时修改。
demo_set_motor.py：单关节位置控制 + 全关节位置设置/回读；当验证位置接口最小闭环时修改。
demo_set_motor_via_multicans.py：通过多 CAN 设备（或序列号映射）同时控制左右手；当验证多设备并行接入时修改。
demo_set_motor_via_multichannels.py：通过同一设备多通道同时控制左右手，并演示手势+单关节控制；当验证双通道并发时修改。
demo_set_motor_via_multisocketcans.py：通过 can0/can1 两个 SocketCAN 接口控制左右手；当验证 Linux 原生 SocketCAN 双手通信时修改。
demo_set_torque.py：读取全部关节控制模式（扭矩/位置等模式相关检查入口）；当排查控制模式配置问题时修改。
demo_socketcan.py：SocketCAN 综合示例（left/right/both），含接口配置提示与控制流程；当现场使用板载 CAN/SocketCAN 生态时使用。
demo_tactile_sensor.py：读取 7 个触觉区域的处理后数据并输出总和；当验证触觉基础读数链路时使用。
demo_tactile_sensor_raw.py：展示 Raw 触觉读取、全量读取、连续读取与 Raw/下采样对比；当分析触觉分辨率差异时修改。
demo_tactile_sensor_raw_reliability.py：按传感器逐个读取 Raw 数据并做可靠性统计（当前聚焦 Palm/Dorsum）；当排查特定传感器稳定性时修改。
demo_zlgcan_tcp.py：通过 ZLG CAN-TCP 网关连接并执行基础动作；当部署在 WiFi/以太网转 CAN 网关场景时修改。


## 核心符号索引

- `OmniHand2025::createHandByZlgcan`
  - 作用：通过 ZLG CANFD 创建 O10 灵巧手实例。
  - 核心原理：封装通讯初始化与对象构建，返回可执行控制指令的手对象。

- `SetAllActiveJointAngles`（C++/Python 同名能力）
  - 作用：批量设置可动关节角度目标值。
  - 核心原理：将目标角度向量写入控制通道，设备端按控制周期执行并反馈状态。

- `/omnihand/omnihand_2025/left/set_joint_angles`（ROS2 服务）
  - 作用：通过 ROS2 服务设置关节目标角度。
  - 核心原理：请求中包含关节向量与超时时间，节点将其转换为设备控制命令。

- `/omnihand/omnihand_2025/left/get_joint_angles`（ROS2 服务）
  - 作用：查询当前关节状态。
  - 核心原理：从节点/设备缓存中读取当前状态并封装服务响应返回。

- `OmniHand2025::get_all_tactile_sensor_data_raw`
  - 作用：一次请求返回全量触觉 Raw 数据（多区域）。
  - 核心原理：底层按传感器区域聚合回包，脚本侧可按区域切分后做求和和变化判定。
