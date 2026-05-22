# 下一阶段调试与测试计划

生成时间：2026-05-22

## 0. 当前判断

本项目选择的是题目六：基于 SDN 与机器学习的虚拟网络构建与智能流量调度。现有代码已经覆盖了大部分模块：

- 基础拓扑和手动流表：`topology/simple_topo.py`
- VLAN 控制器：`controller/vlan_controller.py`
- 端口统计和预测：`controller/monitor_controller.py`、`analysis/predictor.py`
- 背景流量生成：`traffic/traffic_generator.py`
- 扩展控制器：`controller/load_balancer.py`、`controller/dynamic_control.py`、`controller/entropy_detector.py`
- 胖树拓扑：`topology/fat_tree_topo.py`

目前最重要的问题是胖树拓扑：`k=2` 时 `pingall` 成功，但 `k=4` 不成功且内存占用很高。初步代码阅读后，最可疑的根因是 `controller/l2_switch.py` 在未知单播和广播场景下直接使用 `OFPP_FLOOD`。`k=4` 胖树存在大量二层环路，泛洪会导致广播风暴、PacketIn 放大、控制器和 OVS 流量膨胀；`k=2` 近似退化为无环树形结构，所以不容易暴露这个问题。

另一个需要优先修正的问题是胖树的 ECMP 代码尚未完成：`FatTreeNet._install_ecmp_on_switches()` 调用了不存在的 `_add_ecmp_rule()`，并且当前胖树拓扑脚本默认只是启动 Mininet CLI，没有安装无环转发策略或 ECMP group table。

## 本轮进展

已完成 P0 的第一版修复：

- `topology/fat_tree_topo.py` 已支持 `--k`、`--pingall`、`--no-cli` 等参数。
- 胖树主机已设置确定性 MAC 地址，便于控制器直接计算 ARP 和转发路径。
- 胖树链路带宽参数已实际传给 `TCLink`。
- 新增 `controller/fat_tree_controller.py`，避免 `OFPP_FLOOD`，使用 ARP proxy 和目的 IP 确定性流表。
- 原先未完成的 ECMP wrapper 入口改为显式 `NotImplementedError`，避免调用时出现隐藏的 `_add_ecmp_rule` 缺失错误。
- 已通过本地 `py_compile` 静态语法检查。
- 修复 `tests/test_topology.py` 项目根目录计算错误。
- 新增 `tests/test_predictor.py`，使用标准库 `unittest` 覆盖滑动平均、线性回归、统一预测器和拥塞检测器；当前 5 个测试均通过。
- 修复 `traffic/traffic_generator.py`：iperf3 client 现在通过源 Mininet host 的 `popen()` 启动，server 通过目标 host 的 `popen()` 持续运行，不再用 `-1` 单连接退出；日志增加 source/target IP 字段。
- 新增 `tests/test_traffic_generator.py`，用 fake Mininet host 验证 server/client 命令运行位置和日志字段；当前 4 个测试均通过。
- 增强 `topology/simple_topo.py`：支持 `--no-cli`、`--traffic`、`--traffic-duration` 等参数，可自动启动动态 iperf3 流量。
- 更新 `run_experiment.py monitor`：会启动 `monitor_controller.py`，再自动启动 simple topology、手动流表和 h1 -> h3 动态流量。
- 修复 `monitor_controller.py`、`dynamic_control.py`、`entropy_detector.py`、`load_balancer.py` 的 `EventOFPStateChange` 状态判断。
- `monitor_controller.py` 已通过短时 Ryu 启动测试；`run_experiment.py --help` 参数正常。
- 增强 `vlan_controller.py`：针对当前 `SimpleTopo` 直接安装静态 VLAN Push/Pop 规则，避免依赖 PacketIn 学习端口后才下发规则。
- 调整 `run_experiment.py basic`：启动 simple topology 时加 `--no-manual-flows`，避免手动 ovs-ofctl 流表覆盖 VLAN 控制器验证。
- `vlan_controller.py` 已通过短时 Ryu 启动测试。
- VLAN 首次集成验证失败时，Ryu 只显示 DPID=2 安装规则，s1 未见 DPID=1 日志；已修复 `topology/simple_topo.py`，显式固定 s1/s2 DPID，并在测试前调用 `net.waitConnected(timeout=10)` 再等待 `--startup-wait` 秒。
- VLAN 第二次集成验证中，两个 DPID 均已安装规则；普通 `pingall` 显示 66% dropped 是预期现象，因为跨 VLAN 主机对应该不通。已修复 `test_connectivity()`，改为每个方向 `ping -c 3` 并按“可达/阻断”判断；`run_experiment.py basic` 不再自动执行普通 `pingall`。
- VLAN 第三次集成验证通过：h1->h3、h3->h1、h2->h4、h4->h2 均为 `0.0% loss`；h1->h2、h1->h4、h2->h3、h3->h4 均为 `100.0% loss`，符合 VLAN 隔离要求。
- VLAN 抓包验证通过：`captures/vlan_trunk.txt` 中可见 VLAN ID 10 承载 h1 `10.0.0.1` <-> h3 `10.0.0.3` 的 ARP/ICMP，VLAN ID 20 承载 h2 `10.0.0.2` <-> h4 `10.0.0.4` 的 ARP/ICMP；`captures/vlan_trunk.pcapng` 可作为报告/Wireshark 证据。
- 动态控制 hard_timeout demo 已实现：`dynamic_control.py` 支持 `DYNAMIC_DEMO=1` 自动延迟下发 h1-h3 双向 drop 流，`hard_timeout` 到期自动恢复；`simple_topo.py` 支持 `--dynamic-demo` 周期 ping；`run_experiment.py` 新增 `dynamic` 模式。
- 动态控制首次集成验证显示 `blocked -> reachable`，证明 hard_timeout 自动恢复有效；为补齐“阻断前可达”画面，`dynamic_control.py` 已改为等待 datapath 连接后再延迟 `DYNAMIC_DEMO_DELAY` 秒下发阻断。
- 动态控制第二次集成验证通过：h1->h3 在 0.0s `state=reachable`，7.0s/15.1s `state=blocked`，23.2s 后恢复 `state=reachable`，符合 hard_timeout 阻断后自动恢复预期。
- 网络性能限制自动测试已实现：`simple_topo.py --perf-test` 会自动运行 h1->h3、h2->h4 的 ping 与 iperf3，并保存到 `data/performance_report.txt`，用于证明 `TCLink` 的带宽、延迟、丢包配置。
- 网络性能限制验证通过：`data/performance_report.txt` 中 h1->h3、h2->h4 的稳定 RTT 约 26-27ms，符合两条 5ms host-switch 链路加一条 3ms trunk 的往返延迟量级；iperf3 receiver 约 2.92-3.75 Mbits/sec，并伴随 TCP retransmission，体现 10Mbps 接入带宽、链路丢包和延迟共同限制后的吞吐效果。
- 胖树 ECMP 已实现待集成验证：`fat_tree_controller.py` 支持 `FAT_TREE_ECMP=1`，在 edge/aggregation 交换机安装 OpenFlow `SELECT` group；`fat_tree_topo.py --ecmp-demo` 会并发运行跨 pod iperf3 流，并保存 `data/fat_tree_ecmp_report.txt`，包含 dump-groups 和 dump-ports 证据。
- 胖树 ECMP 小范围验证通过：`data/fat_tree_ecmp_report.txt` 中 h1->h16、h2->h15、h3->h14、h4->h13 四条跨 pod iperf3 均成功；e00/e01 存在 `group_id=1,type=select`，且两个上行端口均有接近 10MB 级流量计数，证明 edge 层 ECMP 分流生效。a00/a01 无 group 属于当前稳定策略预期：aggregation 到 core 使用确定性端口，避免此前 aggregation SELECT group 导致跨 pod 断路。
- 胖树 ECMP 完整连通性验证通过：k=4、16 主机 `pingall` 结果为 `0% dropped (240/240 received)`，说明启用 edge 层 SELECT group 后仍保持全网连通。
- 手动 `ovs-ofctl` 流表证据已完成：`data/manual_flow_report.txt` 中 h1<->h3、h2<->h4 可达，其余定向主机对阻断，8 项均 `PASS`；报告同时包含 s1/s2 的 `ovs-ofctl -O OpenFlow13 dump-flows` 输出。

验证结果：激活 `network` conda 环境后，`ryu-manager 4.34`、Ryu 和 Mininet 均可导入；`controller/fat_tree_controller.py` 已能完成 Ryu app 加载和初始化。用户实际运行 `sudo -E python3 topology/fat_tree_topo.py --k 4 --pingall --no-cli` 后，16 台主机 `pingall` 结果为 `0% dropped (240/240 received)`，P0 胖树连通性问题第一阶段完成。

监控验证结果：用户运行 `python3 run_experiment.py monitor --duration 30 --traffic-src h1 --traffic-dst h3` 后，`data/traffic_log.csv` 记录到 h1 `10.0.0.1` -> h3 `10.0.0.3` 的正弦动态流量，`data/port_stats_log.csv` 记录到端口速率和预测值变化，说明“动态背景流量 + 端口统计 + 预测输出”链路已跑通。待清理问题：CSV 中出现 `4294967294`，这是 `OFPP_LOCAL` 本地端口，应过滤。

下一条集成验证命令：

```bash
python3 run_experiment.py monitor --duration 30 --traffic-src h1 --traffic-dst h3
```

运行后检查：

```bash
tail -n 20 data/port_stats_log.csv
tail -n 20 data/traffic_log.csv
```

VLAN 控制器验证命令：

```bash
python3 run_experiment.py basic
```

或手动两终端运行：

```bash
ryu-manager --ofp-tcp-listen-port 6653 controller/vlan_controller.py
sudo -E python3 topology/simple_topo.py --no-manual-flows --no-cli
```

抓包验证 VLAN tag 时，建议先启动控制器，再启动拓扑但不要加 `--no-cli`，然后在另一个终端抓 s1-s2 trunk 链路：

```bash
sudo tshark -i s1-eth3 -Y vlan
```

如果无法输入 Mininet CLI，可用自动抓包模式：

```bash
ryu-manager --ofp-tcp-listen-port 6653 controller/vlan_controller.py
sudo -E python3 topology/simple_topo.py --no-manual-flows --no-cli --skip-tests --vlan-capture
```

输出文件：

- `captures/vlan_trunk.pcapng`
- `captures/vlan_trunk.txt`

动态控制 hard_timeout 验证命令：

```bash
sudo mn -c
python3 run_experiment.py dynamic --block-delay 8 --block-duration 20 --duration 40
```

预期输出中 h1->h3 会经历：

- block 前：`state=reachable`
- block 中：`state=blocked`
- hard_timeout 后：`state=reachable`

网络性能限制验证命令：

```bash
ryu-manager --ofp-tcp-listen-port 6653 controller/vlan_controller.py
sudo -E python3 topology/simple_topo.py --no-manual-flows --no-cli --skip-tests --perf-test
cat data/performance_report.txt
```

胖树 ECMP 验证命令：

```bash
FAT_TREE_K=4 FAT_TREE_ECMP=1 ryu-manager --ofp-tcp-listen-port 6653 controller/fat_tree_controller.py
sudo -E python3 topology/fat_tree_topo.py --k 4 --pingall --ecmp-demo --no-cli
cat data/fat_tree_ecmp_report.txt
```

## 1. 优先级 P0：让胖树 k=4 可稳定连通

目标：`sudo -E python3 topology/fat_tree_topo.py --k 4` 或等价命令启动后，所有主机可按预期互通，`pingall` 不触发内存暴涨。

计划：

1. 复现并记录现象
   - 分别运行 `k=2` 和 `k=4`。
   - 记录 `pingall` 丢包率、Ryu 日志中的 PacketIn 频率、系统内存占用、OVS 流表数量。
   - 保存关键命令输出到 `data/test_runs/`，用于后续报告截图和对比。

2. 停用胖树中的二层泛洪路径
   - 不再用 `controller/l2_switch.py` 的 `OFPP_FLOOD` 作为胖树默认控制器。
   - 新增或重写胖树专用控制器，例如 `controller/fat_tree_controller.py`。
   - 控制器策略优先选择“可解释、可演示”的确定性路由：根据 FatTree 的 pod、edge、aggregation、core 层级计算路径，主动下发双向流表。

3. 处理 ARP
   - 方案 A：实现 ARP proxy，由控制器根据 host IP/MAC 表直接回复 ARP，避免广播进入胖树环路。
   - 方案 B：只在确定的生成树路径上转发 ARP 广播，禁止跨所有上行链路泛洪。
   - 优先选方案 A，因为它最能控制 PacketIn 数量，也便于报告说明。

4. 固定胖树主机标识
   - 在 `FatTreeTopo` 中为主机设置确定性 MAC，例如 `00:00:00:00:pod:host_index` 或类似格式。
   - 保留当前 IP 规则 `10.pod.edge.host/8`，并建立 IP、MAC、接入 edge、端口的映射。
   - 这样控制器可以在不依赖学习泛洪的情况下计算转发路径。

5. 实现路径计算与流表下发
   - 同一 edge 下：edge 本地转发。
   - 同一 pod 不同 edge：edge -> aggregation -> edge。
   - 不同 pod：edge -> aggregation -> core -> aggregation -> edge。
   - 先做确定性单路径，保证 `pingall` 稳定；之后再做 ECMP 或负载均衡。

6. 验证通过标准
   - `k=4` 胖树启动后 `pingall` 丢包率为 0% 或仅首次 ARP 学习有少量可解释丢包。
   - 连续运行 3 轮 `pingall`，内存不持续增长。
   - `ovs-ofctl -O OpenFlow13 dump-flows <switch>` 中能看到主动下发的主机间转发规则。

## 2. 优先级 P1：修正基础测试框架

目标：把“手动试一下”变成可重复执行的测试脚本。

计划：

1. 修正 `tests/test_topology.py`
   - 当前 `project_dir = os.path.dirname(os.path.abspath(__file__))` 指向 `tests/`，后续拼出的 `tests/controller/vlan_controller.py` 和 `tests/topology/simple_topo.py` 路径是错的。
   - 改为项目根目录：`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`。

2. 拆分测试入口
   - `test_basic_manual.py`：验证 `simple_topo.py` 手动流表规则。
   - `test_vlan_controller.py`：验证 VLAN 控制器下发的 Push/Pop 规则和隔离效果。
   - `test_monitor_predictor.py`：验证端口统计 CSV 和预测字段持续生成。
   - `test_fat_tree.py`：验证 `k=2`、`k=4` 胖树连通性和资源占用。

3. 增加非 Mininet 单元测试
   - `analysis/predictor.py`：测试滑动平均、线性回归、拥塞判断。
   - `utils/flow_manager.py`：通过 mock subprocess 测试命令生成。
   - 这些测试不需要 sudo，作为快速回归测试。

4. 增加集成测试清理
   - 每次测试前后执行 `mn -c`。
   - 清理旧 Ryu、iperf3 进程。
   - 保存测试日志，避免失败后只能靠终端回滚查原因。

## 3. 优先级 P1：基础功能逐项验收

目标：确认题目六基础要求都能演示并留下证据。

验收项：

1. 基础拓扑和控制器识别
   - 2 台交换机、4 台主机。
   - OpenFlow 1.3。
   - Ryu 能看到交换机连接日志。

2. 手动流表隔离
   - h1 <-> h3 互通。
   - h2 <-> h4 互通。
   - 其他主机对不通。
   - 保存 `ping` 输出和 `dump-flows`。

3. VLAN Push/Pop
   - VLAN 10：h1 <-> h3。
   - VLAN 20：h2 <-> h4。
   - 在 s1-s2 trunk 链路抓包，确认存在 802.1Q tag。
   - 保存 `tshark` 或 Wireshark 截图。

4. 端口统计和预测
   - `data/port_stats_log.csv` 持续写入。
   - 字段包含当前 tx/rx rate 和 predicted tx/rx rate。
   - 控制台或 CSV 能展示实时预测变化。

5. 背景流量生成
   - 明确使用 `iperf3`，并在文档中写清依赖。
   - 检查 `TrafficGenerator` 是否真正从 Mininet 源主机发流量。目前 `_traffic_loop()` 使用宿主机 `subprocess.Popen()` 跑 iperf3 client，而不是 `src_host.popen()`，这可能导致流量不在 Mininet 主机命名空间内，需要修正。

## 4. 优先级 P2：扩展功能可演示化

目标：扩展功能不只是有文件，而是能被启动、验证、截图。

计划：

1. 智能路由调度
   - 先基于修复后的胖树或冗余拓扑实现。
   - 当前 `load_balancer.py` 只是选择“非拥塞端口中的第一个端口”，没有全局拓扑和路径计算，可能会把流量导向错误端口。
   - 下一步应接入胖树路径计算结果，或维护明确的冗余拓扑端口表。

2. 动态网络控制
   - 当前 `dynamic_control.py` 提供了方法，但没有 REST API 暴露入口，也没有独立演示脚本。
   - 增加 `scripts/demo_dynamic_block.py` 或 Ryu WSGI REST 接口，用于阻断 h1-h3 20 秒并自动恢复。

3. 网络性能限制
   - `simple_topo.py` 已经使用 `TCLink` 设置了带宽、延迟、丢包。
   - 需要补测试：`iperf3` 测带宽、`ping` 测 RTT 和丢包，并把结果写入测试报告。

4. 胖树拓扑与多路径负载均衡
   - 第一阶段只要求 k=4 稳定连通。
   - 第二阶段再实现 ECMP group table 或控制器级多路径选择。
   - 补齐 `_add_ecmp_rule()` 或删除未完成接口，避免误导。

5. 自定义开放问题：熵异常检测
   - 当前 `entropy_detector.py` 依赖 PacketIn 统计。如果主转发逻辑改为主动下发流表，普通流量不会持续 PacketIn，检测数据可能不足。
   - 需要决定演示方式：保留特定采样流量上送控制器，或改用 Port Stats/Flow Stats 做异常检测。

## 5. 建议的文件改动顺序

1. `topology/fat_tree_topo.py`
   - 增加 argparse 支持 `--k`。
   - 为 host 设置确定性 MAC。
   - 暴露 host/switch 命名和端口映射规律，方便测试和控制器使用。

2. `controller/fat_tree_controller.py`
   - 新增胖树专用控制器。
   - 实现 ARP proxy。
   - 主动下发确定性路径流表。

3. `tests/test_topology.py`
   - 修复项目根路径 bug。
   - 增加 k=4 胖树集成测试入口。

4. `traffic/traffic_generator.py`
   - 修正 iperf3 client 在源 Mininet host 内运行的问题。
   - 处理 server `-1` 只接收一次连接的问题，改为生命周期可控的 server。

5. `controller/load_balancer.py`
   - 从“本交换机随便找备用端口”改为“基于拓扑路径的重路由”。

6. `run_experiment.py`
   - 增加 `fat-tree`、`vlan`、`monitor`、`full` 的明确模式。
   - 运行结束自动保存流表、日志和 ping 结果。

## 6. 测试矩阵

| 类别 | 命令/动作 | 通过标准 |
| --- | --- | --- |
| 快速语法测试 | `python3 -m py_compile analysis/predictor.py traffic/traffic_generator.py utils/flow_manager.py utils/logger.py run_experiment.py` | 无错误 |
| 预测单元测试 | `pytest tests/test_predictor.py` | 滑动平均/线性回归输出符合预期 |
| 基础拓扑 | `sudo -E python3 topology/simple_topo.py` 后执行指定 ping | 仅 h1-h3、h2-h4 互通 |
| VLAN 控制器 | `ryu-manager controller/vlan_controller.py` + `topology/controller_topo.py` | VLAN 对互通，跨 VLAN 不通 |
| VLAN 抓包 | `tshark -i s1-eth3 -Y vlan` | 可见 VLAN ID 10/20 |
| 监控预测 | `ryu-manager controller/monitor_controller.py` | CSV 持续产生速率和预测值 |
| 胖树 k=2 | `fat_tree_topo.py --k 2` | `pingall` 成功，资源稳定 |
| 胖树 k=4 | `fat_tree_topo.py --k 4` | `pingall` 成功，PacketIn 不爆炸 |
| 动态控制 | 阻断 h1-h3 20 秒 | 阻断期间不通，超时后恢复 |
| 负载均衡 | 构造拥塞流量 | 控制器下发新路径，流量改走备用链路 |

## 7. 完成定义

下一阶段可以认为完成，当且仅当：

1. `k=4` 胖树可以稳定 `pingall`，没有持续内存增长。
2. 基础功能的连通性、VLAN、监控预测、流量生成都有可重复测试和日志证据。
3. 至少一个扩展功能有完整演示路径，推荐优先选择“胖树拓扑构建”加“网络性能限制”；如时间允许再补“智能路由调度”。
4. 报告所需截图和命令输出已经沉淀到 `data/` 或 `docs/`，不用临近提交时重新摸索。
