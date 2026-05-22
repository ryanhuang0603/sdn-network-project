# 截图清单

截图建议保存到：

```text
docs/screenshots/
```

建议命名使用两位序号，便于报告引用。

## 1. 必须截图

### 01_manual_flow_report.png

内容：

- `data/manual_flow_report.txt` 中的 Directed connectivity 部分。
- 至少截到 8 个 `PASS`。

命令：

```bash
cat data/manual_flow_report.txt
```

用途：

- 证明手动 `ovs-ofctl` 流表满足 h1-h3、h2-h4 互通，其余阻断。

### 02_manual_dump_flows.png

内容：

- `data/manual_flow_report.txt` 中 s1 或 s2 的 `dump-flows` 部分。
- 截到 `priority=400 ... actions=drop` 和 `priority=300 ... actions=output`。

用途：

- 证明流表确实通过 OpenFlow 1.3 下发到 OVS。

### 03_vlan_connectivity.png

内容：

- `python3 run_experiment.py basic` 输出中的 `*** Testing connectivity`。
- 截到 VLAN 内可达和跨 VLAN 阻断。

用途：

- 证明 VLAN 隔离逻辑正确。

### 04_vlan_wireshark.png

内容：

- 用 Wireshark 打开 `captures/vlan_trunk.pcapng`。
- 显示 802.1Q VLAN tag。
- 至少截到 VLAN ID 10 或 VLAN ID 20，最好两张都能显示。

替代文本截图：

```bash
cat captures/vlan_trunk.txt
```

用途：

- 证明 trunk 链路上存在 VLAN tag。

### 05_monitor_prediction.png

内容：

- `data/traffic_log.csv` 和 `data/port_stats_log.csv` 的关键行。

命令：

```bash
tail -n 10 data/traffic_log.csv
tail -n 10 data/port_stats_log.csv
```

用途：

- 证明动态流量、端口速率和预测值存在。

### 06_dynamic_hard_timeout.png

内容：

- `python3 run_experiment.py dynamic --block-delay 8 --block-duration 20 --duration 45`
- 截到：
  - `state=reachable`
  - `state=blocked`
  - 后续再次 `state=reachable`

用途：

- 证明 hard_timeout 临时阻断和自动恢复。

### 07_performance_report.png

内容：

- `data/performance_report.txt` 中 ping RTT 和 iperf3 receiver 结果。

命令：

```bash
cat data/performance_report.txt
```

用途：

- 证明 TCLink 带宽、延迟、丢包限制生效。

### 08_fattree_pingall.png

内容：

- k=4 胖树 `pingall` 的结果。
- 截到：

```text
0% dropped (240/240 received)
```

用途：

- 证明 k=4 胖树全网连通。

### 09_fattree_ecmp_group.png

内容：

- `data/fat_tree_ecmp_report.txt` 中 `dump-groups e00/e01`。
- 截到：

```text
group_id=1,type=select
```

用途：

- 证明 edge 交换机安装了 OpenFlow SELECT group。

### 10_fattree_ecmp_ports.png

内容：

- `data/fat_tree_ecmp_report.txt` 中 `dump-ports e00/e01`。
- 截到两个上行端口都有大量 byte 计数。

用途：

- 证明流量分布到多条上行路径。

## 2. 可选截图

### 11_fattree_iperf.png

内容：

- `data/fat_tree_ecmp_report.txt` 中 h1->h16、h2->h15、h3->h14、h4->h13 的 iperf3 receiver 结果。

用途：

- 证明跨 pod 多流并发成功。

### 12_unit_tests.png

内容：

```bash
python3 tests/test_predictor.py
python3 tests/test_traffic_generator.py
```

用途：

- 证明预测模块和流量生成器有基本自动化测试。

## 3. 截图建议

- 终端字体调到 12-14pt，避免报告里看不清。
- 每张图只截关键区域，不要截整屏太多无关输出。
- Wireshark 截图中展开 `Ethernet II` 下的 `802.1Q Virtual LAN` 字段。
- 每张截图在报告正文里配 1-2 句话说明结论。
- 如果现场 demo 失败，可用这些截图作为备用证据。
