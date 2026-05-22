# 测试报告与证据索引

生成时间：2026-05-22

## 1. 基础功能验收

### 1.1 基础拓扑与 OpenFlow 1.3

实现文件：

- `topology/simple_topo.py`
- `controller/vlan_controller.py`

结论：

- 基础拓扑包含 2 台交换机、4 台主机。
- 交换机固定使用 OpenFlow 1.3。
- Ryu 控制器可识别 s1/s2，并下发流表。

### 1.2 VLAN 隔离与连通性

实现文件：

- `controller/vlan_controller.py`

验证结果：

- h1 <-> h3：`0.0% loss`
- h2 <-> h4：`0.0% loss`
- h1 -> h2：`100.0% loss`
- h1 -> h4：`100.0% loss`
- h2 -> h3：`100.0% loss`
- h3 -> h4：`100.0% loss`

结论：

- VLAN 10 承载 h1/h3。
- VLAN 20 承载 h2/h4。
- 跨 VLAN 流量被阻断。

### 1.2.1 手动 ovs-ofctl 流表

实现文件：

- `topology/simple_topo.py`

证据文件：

- `data/flow_config.json`
- `data/manual_flow_report.txt`

验证命令：

```bash
sudo -E python3 topology/simple_topo.py --no-cli --manual-flow-report
```

结论：

- 该测试不依赖 Ryu 流表下发，由 `ovs-ofctl -O OpenFlow13 add-flow` 安装手动流表。
- 报告文件中包含定向连通性结果和 s1/s2 的 `dump-flows` 输出。
- 已验证 `data/manual_flow_report.txt` 中 8 个定向连通性检查均为 `PASS`。

### 1.3 VLAN Tag 抓包

证据文件：

- `captures/vlan_trunk.pcapng`
- `captures/vlan_trunk.txt`

关键摘要：

```text
vlan.id=10  10.0.0.1 <-> 10.0.0.3
vlan.id=20  10.0.0.2 <-> 10.0.0.4
```

结论：

- s1-s2 trunk 链路上存在 802.1Q VLAN tag。
- VLAN ID 与设计一致。

### 1.4 动态流量、端口统计与预测

实现文件：

- `traffic/traffic_generator.py`
- `controller/monitor_controller.py`
- `analysis/predictor.py`

证据文件：

- `data/traffic_log.csv`
- `data/port_stats_log.csv`

验证结果：

- `traffic_log.csv` 中记录 h1 `10.0.0.1` 到 h3 `10.0.0.3` 的正弦动态流量。
- `port_stats_log.csv` 中记录交换机端口 tx/rx rate 和 predicted tx/rx rate。

结论：

- 动态背景流量生成、Port Stats 轮询和预测输出链路已跑通。

## 2. 扩展功能验收

### 2.1 动态网络控制 hard_timeout

实现文件：

- `controller/dynamic_control.py`
- `run_experiment.py`
- `topology/simple_topo.py`

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

结论：

- 控制器成功下发临时 drop 流表。
- `hard_timeout` 到期后通信自动恢复。

### 2.2 网络性能限制

实现文件：

- `topology/simple_topo.py`

证据文件：

- `data/performance_report.txt`

配置：

- host-switch：`bw=10Mbps delay=5ms loss=1%`
- s1-s2 trunk：`bw=20Mbps delay=3ms loss=0.5%`

验证结果：

- h1 -> h3 稳定 RTT 约 `26-27ms`。
- h2 -> h4 稳定 RTT 约 `26-27ms`。
- iperf3 receiver 约 `2.92-3.75 Mbits/sec`，并存在 TCP retransmission。

结论：

- 延迟配置与路径往返时延量级一致。
- 带宽、丢包和延迟限制对 TCP 吞吐产生明显影响。

### 2.3 胖树拓扑 k=4

实现文件：

- `topology/fat_tree_topo.py`
- `controller/fat_tree_controller.py`

规模：

- core switches：4
- aggregation switches：8
- edge switches：8
- hosts：16

验证结果：

```text
0% dropped (240/240 received)
```

结论：

- k=4 胖树全网连通性验证通过。

### 2.4 胖树 ECMP

实现文件：

- `controller/fat_tree_controller.py`
- `topology/fat_tree_topo.py`

证据文件：

- `data/fat_tree_ecmp_report.txt`

验证结果：

- h1 -> h16、h2 -> h15、h3 -> h14、h4 -> h13 四条跨 pod iperf3 均成功。
- `e00` 和 `e01` 存在 OpenFlow `SELECT` group：

```text
group_id=1,type=select,bucket=weight:100,actions=output:1,bucket=weight:100,actions=output:2
```

- `dump-ports e00/e01` 显示两个上行端口均有大量流量计数。
- ECMP 模式下完整 k=4 `pingall` 结果为 `0% dropped (240/240 received)`。

结论：

- edge 层通过 OpenFlow `SELECT` group 实现多路径分流。
- aggregation 到 core 采用确定性路径选择，保证跨 pod 连通稳定性。

## 3. 自动化测试

无需 sudo 的单元测试：

```bash
python3 tests/test_predictor.py
python3 tests/test_traffic_generator.py
```

验证结果：

- `tests/test_predictor.py`：5 tests OK
- `tests/test_traffic_generator.py`：4 tests OK

## 4. 已知边界

- `controller/load_balancer.py` 仍是实验性代码，未作为最终演示功能。
- `controller/entropy_detector.py` 有初步实现，但未完成正式集成验收。
- 胖树 ECMP 当前采用 edge 层 `SELECT` group；aggregation 层 `SELECT` group 曾导致跨 pod 断路，因此正式演示中不启用 `FAT_TREE_AGG_SELECT=1`。
