#!/usr/bin/env python3
"""Entropy-Based Anomaly Detection Controller

Custom open problem: Detects abnormal traffic patterns (e.g., DDoS attacks, port scans)
using source/destination IP entropy analysis. When entropy drops below a threshold
(indicating traffic concentration), automatic block rules are installed.

Principle:
  - Normal traffic has high entropy (diverse source/destination IPs)
  - Anomalous traffic (DDoS, scans) has low entropy (concentrated IP ranges)
  - H(X) = -Σ p(x_i) * log2(p(x_i))
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4
from ryu.lib import hub
import math
from collections import Counter, defaultdict, deque
import csv
import os
import time


class EntropyAnomalyDetector(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    WINDOW_SIZE = 100
    ENTROPY_THRESHOLD = 1.5
    CHECK_INTERVAL = 5
    BLOCK_DURATION = 30

    def __init__(self, *args, **kwargs):
        super(EntropyAnomalyDetector, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.packet_windows = defaultdict(lambda: deque(maxlen=self.WINDOW_SIZE))
        self.src_ip_counter = Counter()
        self.dst_ip_counter = Counter()
        self.total_packets = 0
        self.blocked_sources = {}
        self.csv_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "entropy_log.csv"
        )
        self._init_csv()
        self.monitor_thread = hub.spawn(self._entropy_loop)

    def _init_csv(self):
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        if not os.path.isfile(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "src_entropy", "dst_entropy",
                                 "total_packets", "is_anomaly", "action"])

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        ip_pkt = pkt.get_protocol(ipv4.ipv4)

        if ip_pkt is None:
            return

        src_ip = ip_pkt.src
        dst_ip = ip_pkt.dst

        self.packet_windows["src"].append(src_ip)
        self.packet_windows["dst"].append(dst_ip)
        self.src_ip_counter[src_ip] += 1
        self.dst_ip_counter[dst_ip] += 1
        self.total_packets += 1

        if self.total_packets >= 10000:
            scale_factor = 0.5
            for key in list(self.src_ip_counter.keys()):
                self.src_ip_counter[key] = int(self.src_ip_counter[key] * scale_factor)
                if self.src_ip_counter[key] < 1:
                    del self.src_ip_counter[key]
            for key in list(self.dst_ip_counter.keys()):
                self.dst_ip_counter[key] = int(self.dst_ip_counter[key] * scale_factor)
                if self.dst_ip_counter[key] < 1:
                    del self.dst_ip_counter[key]
            self.total_packets = sum(self.src_ip_counter.values())

    def _compute_entropy(self, counter, total):
        if total == 0:
            return 0.0
        entropy = 0.0
        for count in counter.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)
        return entropy

    def _entropy_loop(self):
        while True:
            hub.sleep(self.CHECK_INTERVAL)

            if self.total_packets == 0:
                continue

            src_entropy = self._compute_entropy(self.src_ip_counter, self.total_packets)
            dst_entropy = self._compute_entropy(self.dst_ip_counter, self.total_packets)

            is_anomaly = False
            action = "none"

            max_entropy = min(src_entropy, dst_entropy)

            if max_entropy < self.ENTROPY_THRESHOLD and self.total_packets > 50:
                is_anomaly = True
                action = "block_concentrated_sources"

                for ip, count in self.src_ip_counter.most_common(3):
                    if count > self.total_packets * 0.4:
                        self._block_source(ip)
                        action = f"blocked_{ip}"

                self.logger.warning(
                    "ANOMALY detected! src_entropy=%.3f dst_entropy=%.3f "
                    "total_pkts=%d action=%s",
                    src_entropy, dst_entropy, self.total_packets, action,
                )
            else:
                self.logger.info(
                    "Normal: src_entropy=%.3f dst_entropy=%.3f total_pkts=%d",
                    src_entropy, dst_entropy, self.total_packets,
                )

            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp, f"{src_entropy:.3f}", f"{dst_entropy:.3f}",
                    self.total_packets, str(is_anomaly), action,
                ])

    def _block_source(self, src_ip):
        now = time.time()
        if src_ip in self.blocked_sources:
            if now - self.blocked_sources[src_ip] < self.BLOCK_DURATION:
                return
        self.blocked_sources[src_ip] = now

        for dpid, datapath in self.datapaths.items():
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip)
            actions = []
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=600, match=match,
                instructions=inst, hard_timeout=self.BLOCK_DURATION,
            )
            datapath.send_msg(mod)

        self.logger.warning("Blocked source IP %s on all switches for %ds",
                            src_ip, self.BLOCK_DURATION)

    def get_entropy_stats(self):
        return {
            "src_entropy": self._compute_entropy(self.src_ip_counter, self.total_packets),
            "dst_entropy": self._compute_entropy(self.dst_ip_counter, self.total_packets),
            "total_packets": self.total_packets,
            "unique_src_ips": len(self.src_ip_counter),
            "unique_dst_ips": len(self.dst_ip_counter),
            "blocked_sources": list(self.blocked_sources.keys()),
        }
