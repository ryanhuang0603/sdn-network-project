# SDN 综合实验项目计划

---

## 一、项目整体架构

```
┌──────────────────────────────────────────────────────┐
│                   Ryu Controller                      │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ VLAN Manager │  │ Port Stats   │  │ Load Balancer│ │
│  │             │  │ Poller       │  │ (预测+调度)  │ │
│  └─────────────┘  └──────────────┘  └─────────────┘ │
│         │                │                 │          │
│  ┌──────────────────────────────────────────────┐    │
│  │              REST API (Northbound)           │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
                         │ OpenFlow 1.3
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐     ┌─────────┐     ┌─────────┐
   │   s1    │─────│   s2    │─────│   s3    │
   │ (OVS)   │     │ (OVS)   │     │ (OVS)   │
   └─────────┘     └─────────┘     └─────────┘
     │    │           │    │           │    │
    h1   h2          h3   h4         h5   h6
  VLAN10 VLAN20     VLAN10 VLAN20
```

---

## 二、文件目录结构

```
bighomework/
├── PLAN.md                    # 本计划文档
├── README.md                  # 项目说明
├── topology/
│   ├── simple_topo.py         # 基础拓扑（2交换机+4主机）
│   └── fat_tree_topo.py       # 扩展：胖树拓扑
├── controller/
│   ├── vlan_controller.py     # VLAN 划分与隔离控制器
│   ├── monitor_controller.py  # 流量监控与预测控制器
│   ├── load_balancer.py       # 扩展：智能路由调度控制器
│   └── dynamic_control.py     # 扩展：动态网络控制
├── traffic/
│   ├── traffic_generator.py   # 背景流量生成器（正弦波/高峰模拟）
│   └── traffic_config.json    # 流量配置参数
├── analysis/
│   ├── predictor.py           # 流量预测算法模块
│   ├── sliding_window.py      # 滑动平均实现
│   └── linear_regression.py   # 简单线性回归实现
├── utils/
│   ├── rest_client.py         # 控制器 REST API 客户端
│   ├── flow_manager.py        # 流表管理工具
│   └── logger.py              # 日志工具
├── data/
│   ├── traffic_log.csv        # 流量日志（运行时生成）
│   └── flow_config.json       # 流表配置
├── tests/
│   ├── test_topology.py       # 拓扑连通性测试
│   ├── test_vlan.py           # VLAN 隔离测试
│   └── test_predictor.py      # 预测算法测试
├── captures/                  # Wireshark 抓包文件
└── docs/
    └── screenshots/           # 实验截图
```

---

## 三、基础功能实现计划（必做）

### 3.1 拓扑与控制器配置

#### 步骤 1：环境准备
- 安装 Mininet
- 安装 Ryu 控制器
- 安装 Open vSwitch (OVS)
- 安装 Wireshark、iperf
- 验证 OpenFlow 1.3 支持

#### 步骤 2：编写基础拓扑脚本 (`topology/simple_topo.py`)
- 创建 2 台 OVS 交换机 (s1, s2)，OpenFlow 1.3 协议
- 创建 4 台主机 (h1, h2, h3, h4)
- 连接方式：h1–s1, h2–s1, h3–s2, h4–s2, s1–s2
- 指定控制器为远程 Ryu 控制器（端口 6653）

#### 步骤 3：手动流表下发 (ovs-ofctl)
```bash
# s1 流表
ovs-ofctl -O OpenFlow13 add-flow s1 "priority=10,in_port=s1-eth1,actions=output:s1-eth3"    # h1->s2
ovs-ofctl -O OpenFlow13 add-flow s1 "priority=10,in_port=s1-eth2,actions=output:s1-eth3"    # h2->s2
ovs-ofctl -O OpenFlow13 add-flow s1 "priority=10,in_port=s1-eth3,dl_dst=00:00:00:00:00:01,actions=output:s1-eth1"  # s2->h1
ovs-ofctl -O OpenFlow13 add-flow s1 "priority=10,in_port=s1-eth3,dl_dst=00:00:00:00:00:02,actions=output:s1-eth2"  # s2->h2
# s2 流表（镜像规则）
# 达到：h1<->h3, h2<->h4 互通，其余禁止
```

#### 步骤 4：VLAN 划分 (`controller/vlan_controller.py`)
- **h1–h3 → VLAN 10**，**h2–h4 → VLAN 20**
- 在入口交换机端口执行 **Push VLAN Tag** 操作
- 在出口交换机端口执行 **Pop VLAN Tag** 操作
- 使用 Ryu 控制器 REST API 或 Ryu App 实现

**VLAN 流表逻辑：**
```
s1 port1 (h1):
  in: 无tag → push_vlan(0x8100), set_vlan_vid(10) → output:trunk
  out: vlan_vid=10 → pop_vlan → output:port1

s1 port2 (h2):
  in: 无tag → push_vlan(0x8100), set_vlan_vid(20) → output:trunk
  out: vlan_vid=20 → pop_vlan → output:port2

s2 port1 (h3): 类似处理
s2 port2 (h4): 类似处理
```

---

### 3.2 流量监控与预测

#### 步骤 1：背景流量生成器 (`traffic/traffic_generator.py`)
- 使用 `iperf` 在 h1→h3 之间生成动态流量
- 流量模式实现两种：
  1. **正弦波模式**：`rate(t) = base + amplitude * sin(2π * t / period)`
  2. **早晚高峰模式**：模拟 8:00-9:00, 18:00-19:00 峰值
- 通过 Python `subprocess` 动态调整 iperf 速率参数
- 周期性运行多个 iperf 客户端，持续记录时间戳与速率

#### 步骤 2：端口统计轮询 (`controller/monitor_controller.py`)
- Ryu App 周期性发送 `OFPMPPortStatsRequest` 消息（间隔 1-2 秒）
- 解析端口 `tx_bytes` 和 `rx_bytes` 字段
- 计算链路利用率：`rate = (byte2 - byte1) / (time2 - time1)`
- 将数据写入 `data/traffic_log.csv`：
  ```
  timestamp, switch_id, port_no, tx_bytes, rx_bytes, tx_rate_mbps, rx_rate_mbps
  ```

#### 步骤 3：流量预测模块 (`analysis/predictor.py`)
**算法选项：**
- **滑动平均 (Moving Average)**：`pred[t+1] = (1/N) * Σ val[t-i], i=0..N-1`
- **简单线性回归**：用最近 N 个点拟合直线 `y = ax + b`，预测下一时刻

**实现要点：**
- 维护滑动窗口队列（最近 30 个采样点）
- 每收到新数据点即更新预测值
- 控制台实时输出：当前速率 + 预测速率
- 支持配置窗口大小、采样间隔

---

### 3.3 流表验证与测试

#### 测试流程：
1. **连通性测试**：`pingall` 验证 — 应只有 h1↔h3, h2↔h4 互通
2. **VLAN 验证**：Wireshark 在 s1-s2 链路上抓包，检查：
   - `802.1Q` VLAN 标签存在
   - VLAN ID 正确（10 或 20）
3. **流表查看**：`ovs-ofctl -O OpenFlow13 dump-flows s1` 截图留存
4. **实时日志展示**：
   ```
   [14:30:01] s1-port1 | rx: 5.2 Mbps | predicted: 5.8 Mbps
   [14:30:01] s1-port2 | rx: 2.1 Mbps | predicted: 2.3 Mbps
   ```

---

## 四、扩展功能实现计划

### 4.1 智能路由调度 (25分)

#### 前提：在拓扑中增加冗余链路或额外交换机
```
   s1 ──── s2
   │  ╲    ╱  │
   │   ╲  ╱   │
   │   ╱  ╲   │
   │  ╱    ╲  │
   s3 ──── s4
```

#### 实现逻辑 (`controller/load_balancer.py`)：
1. **拥塞检测**：预测值 > 链路带宽 × 80% → 触发调度
2. **路径计算**：Dijkstra 最短路径，排除拥塞链路
3. **流表下发**：通过 Flow Mod 修改匹配流量的出端口
4. **闭环控制**：持续监控，预测值回落 → 恢复原路径

**关键点**：使用 `EventOFPFlowStatsReply` 获取各端口统计，结合预测值触发重路由。

---

### 4.2 动态网络控制 (15分)

#### 实现方式 (`controller/dynamic_control.py`)：
1. 通过 Ryu REST API 或直接在 Ryu App 中发送 `OFPFlowMod`
2. 下发流表时设置 `hard_timeout=20`（秒）
3. 20 秒后流表自动过期，恢复原规则
4. 示例命令（ovs-ofctl）：
   ```bash
   ovs-ofctl add-flow s1 "hard_timeout=20,priority=100,in_port=1,actions=drop"
   ```

#### REST API 方式（若使用 Ryu REST API）：
```
POST /stats/flowentry/add
{
  "dpid": 1,
  "priority": 100,
  "hard_timeout": 20,
  "match": {"in_port": 1},
  "actions": []
}
```

---

### 4.3 网络性能限制 (10分)

#### 在拓扑脚本中添加 TCLink：
```python
# simple_topo.py 中
self.addLink(h1, s1, bw=10, delay='5ms', loss=1)  # 带宽10Mbps, 延迟5ms, 丢包1%
self.addLink(h2, s1, bw=5, delay='2ms')
self.addLink(s1, s2, bw=20, delay='3ms', loss=0.5)
```

**验证**：iperf 测速、ping 测延迟、丢包统计

---

### 4.4 胖树拓扑构建 (25分)

#### 拓扑设计 (`topology/fat_tree_topo.py`)：
```
Pod 0:
             core1    core2
            /    \   /    \
        agg1.0  agg1.1  agg1.0  agg1.1
          |       |       |       |
        edge1.0 edge1.1 edge1.0 edge1.1
          h  h    h  h    h  h    h  h

k=4 胖树：4个Pod，共20台交换机，16台主机
```

#### 实现细节：
- **类 `FatTreeTopo(k=4)`**：参数化 k 值
- 网络层次：Core、Aggregation、Edge
- ECMP (Equal-Cost Multi-Path) 多路径负载均衡
- 使用 `addLink(use_htb=True)` 设置各层链路不同的带宽约束
- 验证：iperf 多流并发，观察多路径流量分布

---

### 4.5 自定义开放问题 (10-25分)

#### 建议方向（选择其一或自定义）：

**方向 A：基于 MAC 地址学习的自愈网络 (15分)**
- 监听 `PacketIn` 做自学习交换机
- 链路断开时自动重路由（使用备用路径）
- 实现恢复时间统计

**方向 B：基于熵的异常检测 (20分)**
- 对每条链路流量计算信息熵
- 设定阈值检测异常流量（如 DDoS 前兆）
- 异常时自动下发 Block 流表

**方向 C：QoS 差分服务 (25分)**
- 在 VLAN 基础上划分优先级队列
- 使用 OFPQ_MIN_RATE 保证最低带宽
- 结合 iperf 不同优先级流量验证

**方向 D：Web 可视化看板 (20分)**
- 使用 Flask/FastAPI + Chart.js 搭建 Web 界面
- 实时展示拓扑图、链路利用率、预测趋势曲线
- 通过 REST API 允许用户手动下发流表

---

## 五、执行步骤与时间线

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| **阶段 1** | 环境安装与验证 | 第 1 天 |
| **阶段 2** | 基础拓扑 + 手动流表 | 第 2 天 |
| **阶段 3** | VLAN 控制器开发 | 第 3 天 |
| **阶段 4** | 流量生成器 + 监控轮询 | 第 4 天 |
| **阶段 5** | 预测算法实现 | 第 5 天 |
| **阶段 6** | 基础功能集成测试 | 第 6 天 |
| **阶段 7** | 扩展功能开发（并行） | 第 7-9 天 |
| **阶段 8** | 全功能联调 + 文档 | 第 10 天 |

---

## 六、技术选型

| 组件 | 选择 | 原因 |
|------|------|------|
| 控制器 | **Ryu** | Python 原生支持，学习成本低，社区活跃 |
| 拓扑模拟 | **Mininet** | 标准 SDN 实验平台 |
| 流量生成 | **iperf** | 稳定可靠，CLI 可脚本化 |
| 预测算法 | **滑动平均 + 线性回归** | 简单可解释，满足实验要求 |
| 数据存储 | **CSV** | 轻量，便于 Python pandas 分析 |
| 抓包分析 | **Wireshark / tcpdump** | 标准网络分析工具 |
| Web 可视化 | **Flask + Chart.js**（如选方向 D） | 轻量 Python 框架 |

---

## 七、关键技术难点与对策

| 难点 | 对策 |
|------|------|
| Ryu 多 App 同时运行 | 使用 `ryu-manager app1.py app2.py` 或合并为单一 App |
| OpenFlow 1.3 流表匹配 | 仔细阅读 OVS 手册，理解多级流表 pipeline |
| VLAN Push/Pop 操作 | 使用 `push_vlan` 和 `pop_vlan` action，注意 EtherType 0x8100 |
| 流量预测准确性 | 增加采样频率，适当增大滑动窗口 |
| 多路径负载均衡 | 利用 OVS group table 的 `select` 类型实现 ECMP |

---

*本计划将随开发进展持续更新。*
