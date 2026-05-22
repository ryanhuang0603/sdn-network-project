# SDN 虚拟网络构建与智能流量调度

题目六：基于 SDN 与机器学习的虚拟网络构建与智能流量调度。

本项目使用 Mininet + Open vSwitch 构建虚拟网络，使用 Ryu 控制器通过 OpenFlow 1.3 下发流表，实现 VLAN 隔离、端口统计监控、流量预测，并完成动态网络控制、网络性能限制、胖树拓扑和 ECMP 多路径分流等扩展功能。

## 1. 环境要求

已验证环境：

- Ubuntu Linux
- Python 3.14.4
- numpy 2.4.6
- Ryu 4.34
- Mininet
- Open vSwitch / OpenFlow 1.3
- iperf3
- tshark / Wireshark
- Python conda 环境：`network`

系统依赖：

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch iperf3 tshark wireshark
```

Python 依赖：

```bash
conda env create -f environment.yml
conda activate network
```

如果已经有 `network` 环境：

```bash
conda activate network
pip install -r requirements.txt
```

依赖说明详见：

```text
docs/DEPENDENCIES.md
```

每次启动新的 Mininet 拓扑前，建议先清理旧状态：

```bash
sudo mn -c
```

注意：`sudo mn -c` 应在启动本轮拓扑之前执行，不要在拓扑运行中执行。

## 2. 目录结构

```text
controller/
  vlan_controller.py        VLAN Push/Pop 与隔离控制器
  monitor_controller.py     OpenFlow Port Stats 监控与预测记录
  dynamic_control.py        hard_timeout 动态控制
  fat_tree_controller.py    胖树确定性转发与 ECMP

topology/
  simple_topo.py            2 交换机 4 主机基础拓扑
  fat_tree_topo.py          k-ary 胖树拓扑

traffic/
  traffic_generator.py      Mininet 内 iperf3 动态流量生成

analysis/
  predictor.py              滑动平均和线性回归预测

tests/
  test_predictor.py         预测模块单元测试
  test_traffic_generator.py 流量生成器单元测试

data/                       实验输出和报告数据
captures/                   VLAN 抓包文件
docs/                       测试报告、项目报告、截图指南
```

## 3. 已完成功能

基础功能：

- 2 交换机 4 主机拓扑，OpenFlow 1.3。
- 手动 `ovs-ofctl` 流表：h1-h3、h2-h4 互通，其余阻断。
- VLAN 10 / VLAN 20 Push/Pop 与隔离。
- VLAN trunk 抓包验证。
- 动态背景流量生成。
- 端口统计轮询。
- 滑动平均 / 线性回归流量预测。

扩展功能：

- 动态网络控制：`hard_timeout` 临时阻断并自动恢复。
- 网络性能限制：TCLink 带宽、延迟、丢包。
- k=4 胖树拓扑。
- 胖树 ECMP：edge 层 OpenFlow `SELECT` group 多路径分流。

未作为最终演示功能：

- `controller/load_balancer.py`：实验性智能调度雏形。
- `controller/entropy_detector.py`：实验性异常检测雏形。

## 4. 快速验收命令

以下命令按功能分组。需要两个终端的实验会明确标出。

### 4.1 手动 ovs-ofctl 流表

该实验不依赖 Ryu 控制器。

```bash
sudo mn -c
sudo -E python3 topology/simple_topo.py --no-cli --manual-flow-report
cat data/manual_flow_report.txt
```

证据文件：

- `data/flow_config.json`
- `data/manual_flow_report.txt`

### 4.2 VLAN 隔离

```bash
sudo mn -c
python3 run_experiment.py basic
```

预期：

- h1 <-> h3 可达。
- h2 <-> h4 可达。
- 其他跨 VLAN 主机对阻断。

### 4.3 VLAN Tag 抓包

终端 1：

```bash
ryu-manager --ofp-tcp-listen-port 6653 controller/vlan_controller.py
```

终端 2：

```bash
sudo mn -c
sudo -E python3 topology/simple_topo.py --no-manual-flows --no-cli --skip-tests --vlan-capture
cat captures/vlan_trunk.txt
```

证据文件：

- `captures/vlan_trunk.pcapng`
- `captures/vlan_trunk.txt`

### 4.4 动态流量监控与预测

```bash
sudo mn -c
python3 run_experiment.py monitor --duration 30 --traffic-src h1 --traffic-dst h3
tail -n 20 data/traffic_log.csv
tail -n 20 data/port_stats_log.csv
```

证据文件：

- `data/traffic_log.csv`
- `data/port_stats_log.csv`

### 4.5 动态控制 hard_timeout

```bash
sudo mn -c
python3 run_experiment.py dynamic --block-delay 8 --block-duration 20 --duration 45
```

预期输出中 h1 -> h3 会经历：

```text
state=reachable
state=blocked
state=reachable
```

### 4.6 网络性能限制

终端 1：

```bash
ryu-manager --ofp-tcp-listen-port 6653 controller/vlan_controller.py
```

终端 2：

```bash
sudo mn -c
sudo -E python3 topology/simple_topo.py --no-manual-flows --no-cli --skip-tests --perf-test
cat data/performance_report.txt
```

证据文件：

- `data/performance_report.txt`

### 4.7 胖树 k=4 连通性

终端 1：

```bash
FAT_TREE_K=4 ryu-manager --ofp-tcp-listen-port 6653 controller/fat_tree_controller.py
```

终端 2：

```bash
sudo mn -c
sudo -E python3 topology/fat_tree_topo.py --k 4 --pingall --no-cli
```

预期：

```text
0% dropped (240/240 received)
```

### 4.8 胖树 ECMP

终端 1：

```bash
FAT_TREE_K=4 FAT_TREE_ECMP=1 ryu-manager --ofp-tcp-listen-port 6653 controller/fat_tree_controller.py
```

终端 2：

```bash
sudo mn -c
sudo -E python3 topology/fat_tree_topo.py --k 4 --pingall --ecmp-demo --no-cli
cat data/fat_tree_ecmp_report.txt
```

报告重点：

- `pingall` 为 `0% dropped (240/240 received)`。
- `dump-groups e00/e01` 出现 `type=select`。
- `dump-ports e00/e01` 两个上行端口均有流量计数。

## 5. 自动化测试

无需 sudo 的快速测试：

```bash
python3 tests/test_predictor.py
python3 tests/test_traffic_generator.py
```

语法检查：

```bash
python3 -m py_compile \
  topology/simple_topo.py \
  topology/fat_tree_topo.py \
  controller/vlan_controller.py \
  controller/monitor_controller.py \
  controller/dynamic_control.py \
  controller/fat_tree_controller.py \
  run_experiment.py
```

## 6. 关键证据文件

| 文件 | 内容 |
| --- | --- |
| `data/manual_flow_report.txt` | 手动 ovs-ofctl 连通性和 dump-flows |
| `data/flow_config.json` | 手动流表规则配置 |
| `captures/vlan_trunk.pcapng` | VLAN trunk 抓包 |
| `captures/vlan_trunk.txt` | VLAN tag 文本摘要 |
| `data/traffic_log.csv` | 动态背景流量日志 |
| `data/port_stats_log.csv` | 端口统计和预测日志 |
| `data/performance_report.txt` | ping/iperf3 性能限制报告 |
| `data/fat_tree_ecmp_report.txt` | 胖树 ECMP 证据 |
| `docs/DEPENDENCIES.md` | 依赖安装与环境说明 |
| `docs/TEST_REPORT.md` | 测试报告与证据索引 |
| `docs/PROJECT_REPORT.md` | 项目报告初稿 |
| `docs/SCREENSHOT_GUIDE.md` | 截图清单 |

## 7. 报告与截图

报告初稿：

```text
docs/PROJECT_REPORT.md
```

测试报告：

```text
docs/TEST_REPORT.md
```

截图指南：

```text
docs/SCREENSHOT_GUIDE.md
```

建议将截图保存到：

```text
docs/screenshots/
```

## 8. 注意事项

- `run_experiment.py` 启动的 Mininet 不是交互式直连 CLI，不适合手动输入 Mininet 命令。
- 需要手动输入 Mininet CLI 时，建议直接运行 `topology/simple_topo.py` 或 `topology/fat_tree_topo.py`，不要通过 `run_experiment.py` 包一层。
- 胖树 ECMP 正式演示只启用 `FAT_TREE_ECMP=1`，不要启用 `FAT_TREE_AGG_SELECT=1`。
- Eventlet 的 deprecation warning 不影响 Ryu 控制器运行。
