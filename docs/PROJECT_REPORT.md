# 基于 SDN 与机器学习的虚拟网络构建与智能流量调度

## 1. 项目概述

本项目围绕题目六“基于 SDN 与机器学习的虚拟网络构建与智能流量调度”展开，使用 Mininet 构建虚拟网络拓扑，使用 Ryu 控制器通过 OpenFlow 1.3 下发流表，实现主机隔离、VLAN 标签处理、端口统计采集、流量预测和多项扩展功能。

项目实现了基础 2 交换机 4 主机拓扑，并在此基础上完成 VLAN 10 / VLAN 20 的逻辑隔离。系统还实现了动态背景流量生成、端口统计轮询和简单流量预测。扩展功能方面，实现了动态网络控制、链路性能限制、k=4 胖树拓扑和 edge 层 ECMP 多路径分流。

## 2. 实验环境

实验环境如下：

- 操作系统：Linux
- 网络仿真：Mininet
- 虚拟交换机：Open vSwitch
- SDN 控制器：Ryu 4.34
- 控制协议：OpenFlow 1.3
- 流量工具：iperf3
- 抓包工具：tshark / Wireshark
- 编程语言：Python
- Python 环境：conda `network`

每次运行 Mininet 拓扑前，先执行：

```bash
sudo mn -c
```

该命令用于清理上一次实验遗留的交换机、虚拟网卡和 namespace。

## 3. 系统架构

系统由三部分组成：

1. Mininet 拓扑层
   - `topology/simple_topo.py`：基础拓扑，包含 s1、s2、h1-h4。
   - `topology/fat_tree_topo.py`：k-ary 胖树拓扑，支持 k=4。

2. Ryu 控制器层
   - `controller/vlan_controller.py`：VLAN Push/Pop 和隔离控制。
   - `controller/monitor_controller.py`：端口统计轮询和 CSV 记录。
   - `controller/dynamic_control.py`：hard_timeout 动态阻断。
   - `controller/fat_tree_controller.py`：胖树确定性转发和 ECMP 分流。

3. 实验与分析层
   - `traffic/traffic_generator.py`：动态背景流量生成。
   - `analysis/predictor.py`：滑动平均和线性回归预测。
   - `run_experiment.py`：常用实验入口。
   - `data/`、`captures/`：实验日志、抓包和报告文件。

## 4. 基础拓扑与手动流表

基础拓扑包含 2 台交换机和 4 台主机：

```text
h1 -- s1 -- s2 -- h3
h2 --/       \-- h4
```

主机地址：

- h1：`10.0.0.1`
- h2：`10.0.0.2`
- h3：`10.0.0.3`
- h4：`10.0.0.4`

交换机 s1、s2 使用 OpenFlow 1.3，并固定 DPID：

- s1：`0000000000000001`
- s2：`0000000000000002`

项目实现了手动流表模式，通过 `ovs-ofctl -O OpenFlow13 add-flow` 安装规则，实现：

- h1 <-> h3 可达
- h2 <-> h4 可达
- 其他主机对阻断

证据文件：

- `data/flow_config.json`
- `data/manual_flow_report.txt`

验证结果显示 8 个定向连通性检查均为 PASS，并记录了 s1、s2 的 `dump-flows` 输出。

## 5. VLAN 隔离设计

VLAN 控制器为两组主机分配不同 VLAN：

- VLAN 10：h1、h3
- VLAN 20：h2、h4

在接入端口进入交换机时，控制器下发 Push VLAN 规则；在流量从 trunk 链路离开并转发到目标主机端口时，下发 Pop VLAN 规则。

s1 的静态规则逻辑：

- h1 端口进入：Push VLAN 10，输出到 s1-s2 trunk。
- h2 端口进入：Push VLAN 20，输出到 s1-s2 trunk。
- trunk 进入 VLAN 10：Pop VLAN，输出到 h1。
- trunk 进入 VLAN 20：Pop VLAN，输出到 h2。

s2 的逻辑与 s1 对称。

定向连通性结果：

- h1 -> h3：`0.0% loss`
- h3 -> h1：`0.0% loss`
- h2 -> h4：`0.0% loss`
- h4 -> h2：`0.0% loss`
- 跨 VLAN 主机对：`100.0% loss`

VLAN 抓包证据：

- `captures/vlan_trunk.pcapng`
- `captures/vlan_trunk.txt`

抓包摘要中可见：

```text
vlan.id=10  10.0.0.1 <-> 10.0.0.3
vlan.id=20  10.0.0.2 <-> 10.0.0.4
```

说明 trunk 链路上存在正确的 802.1Q 标签。

## 6. 流量监控与预测

项目通过 `traffic/traffic_generator.py` 在 Mininet 主机内运行 iperf3，生成动态背景流量。正式验证中使用 h1 到 h3 的正弦流量。

控制器 `monitor_controller.py` 周期性发送 `OFPPortStatsRequest`，采集端口的 tx/rx bytes，根据相邻采样点计算速率：

```text
rate = (bytes_now - bytes_previous) * 8 / delta_time
```

预测模块 `analysis/predictor.py` 实现了两种基础算法：

1. 滑动平均 + 最近趋势
2. 简单线性回归

监控数据保存到：

- `data/traffic_log.csv`
- `data/port_stats_log.csv`

当前 `port_stats_log.csv` 包含 64139 条记录，其中 20774 条存在非零速率，19234 条存在非零预测值，说明监控和预测链路已正常运行。

## 7. 扩展功能一：动态网络控制

动态网络控制由 `controller/dynamic_control.py` 实现。控制器下发带 `hard_timeout` 的 drop 流表，临时阻断 h1 和 h3 通信，到期后交换机自动删除规则，通信恢复。

验证命令：

```bash
python3 run_experiment.py dynamic --block-delay 8 --block-duration 20 --duration 45
```

验证结果：

```text
0.0s   h1->h3 state=reachable
7.0s   h1->h3 state=blocked
15.1s  h1->h3 state=blocked
23.2s  h1->h3 state=reachable
31.2s  h1->h3 state=reachable
38.3s  h1->h3 state=reachable
```

该结果说明控制器成功下发临时阻断规则，并且 `hard_timeout` 到期后通信自动恢复。

## 8. 扩展功能二：网络性能限制

基础拓扑使用 `TCLink` 设置链路性能参数：

- host-switch 链路：`bw=10Mbps delay=5ms loss=1%`
- s1-s2 trunk：`bw=20Mbps delay=3ms loss=0.5%`

测试报告保存到：

- `data/performance_report.txt`

结果显示 h1->h3、h2->h4 稳定 RTT 约为 `26-27ms`。这与路径上的 `5ms + 3ms + 5ms` 单向延迟和往返时延量级一致。iperf3 receiver 约为 `2.92-3.75 Mbits/sec`，并伴随 TCP retransmission，说明带宽限制、延迟和丢包共同影响了 TCP 吞吐。

## 9. 扩展功能三：胖树拓扑与 ECMP

项目实现了 k-ary fat-tree 拓扑。k=4 时规模如下：

- core switches：4
- aggregation switches：8
- edge switches：8
- hosts：16

早期使用学习交换机泛洪时，k=4 拓扑会出现环路泛洪和内存增长问题。最终使用 `controller/fat_tree_controller.py` 实现胖树专用控制器，避免 `OFPP_FLOOD`，改为基于主机 IP 和拓扑编号的确定性转发，并实现 ARP proxy。

全网连通性验证：

```text
0% dropped (240/240 received)
```

ECMP 模式通过环境变量启用：

```bash
FAT_TREE_ECMP=1
```

在 ECMP 模式下，edge 交换机安装 OpenFlow `SELECT` group，把跨 pod 流量分配到多个 aggregation 上行端口。aggregation 到 core 使用确定性端口选择，以保证跨 pod 连通稳定性。

证据文件：

- `data/fat_tree_ecmp_report.txt`

验证结果：

- h1 -> h16、h2 -> h15、h3 -> h14、h4 -> h13 四条跨 pod iperf3 均成功。
- `e00` 和 `e01` 存在 `type=select` group。
- `dump-ports e00/e01` 显示两个上行端口均有大量流量。
- ECMP 模式下 k=4 `pingall` 仍为 `0% dropped (240/240 received)`。

## 10. 自动化测试

项目包含无需 sudo 的快速测试：

```bash
python3 tests/test_predictor.py
python3 tests/test_traffic_generator.py
```

验证结果：

- `tests/test_predictor.py`：5 tests OK
- `tests/test_traffic_generator.py`：4 tests OK

## 11. 总结

本项目完成了 SDN 虚拟网络构建、VLAN 隔离、流表下发、端口统计采集、流量预测和多项扩展功能。基础功能部分覆盖了拓扑搭建、手动流表、控制器流表、VLAN 抓包、流量生成和预测输出。扩展功能部分完成了动态网络控制、性能限制、k=4 胖树拓扑和 edge 层 ECMP 分流。

当前稳定演示功能包括：

- 手动 `ovs-ofctl` 流表验证
- VLAN 隔离与抓包
- 动态流量监控与预测
- hard_timeout 动态阻断与恢复
- 链路性能限制
- k=4 胖树与 ECMP

实验性但未作为最终演示的模块包括：

- `controller/load_balancer.py`
- `controller/entropy_detector.py`
