#!/usr/bin/env python3
"""Load Balancer Controller: monitors link utilization via prediction,
detects congestion and reroutes traffic when thresholds exceeded."""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from collections import deque
import time


class LoadBalancerController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    POLL_INTERVAL = 2
    CONGESTION_THRESHOLD = 0.35
    COOL_DOWN = 8

    def __init__(self, *args, **kwargs):
        super(LoadBalancerController, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.port_stats = {}
        self.port_history = {}
        self.link_capacity = {}
        self.reroute_history = {}
        self.monitor_thread = hub.spawn(self._monitor_loop)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        self.logger.info("[LB] Switch connected: DPID=%d", datapath.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)

    def _monitor_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(self.POLL_INTERVAL)

    def _request_stats(self, datapath):
        req = datapath.ofproto_parser.OFPPortStatsRequest(
            datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id
        timestamp = time.time()

        for stat in body:
            port_no = stat.port_no
            if port_no >= 0xffffff00:
                continue

            key = (dpid, port_no)
            if key not in self.link_capacity:
                self.link_capacity[key] = 3.0

            previous = self.port_stats.get(key)
            self.port_stats[key] = (timestamp, stat.tx_bytes, stat.rx_bytes)

            if previous is None:
                continue

            prev_time, prev_tx, prev_rx = previous
            delta = timestamp - prev_time
            if delta <= 0:
                continue

            tx_rate = (stat.tx_bytes - prev_tx) * 8.0 / delta / 1e6

            self.port_history.setdefault(key, deque(maxlen=20))
            self.port_history[key].append((timestamp, tx_rate))

            predicted = self._predict(key)
            capacity = self.link_capacity.get(key, 10.0)

            if predicted > capacity * self.CONGESTION_THRESHOLD:
                now = time.time()
                last = self.reroute_history.get(key, 0)
                if now - last > self.COOL_DOWN:
                    self.logger.warning(
                        "[CONGESTION] DPID=%d port=%d | rate=%.2f Mbps | "
                        "predicted=%.2f Mbps | capacity=%.0f Mbps (%.0f%%)",
                        dpid, port_no, tx_rate, predicted, capacity,
                        (predicted / capacity) * 100,
                    )
                    self._reroute(dpid, port_no)
                    self.reroute_history[key] = now

    def _predict(self, key):
        history = self.port_history.get(key)
        if not history or len(history) < 2:
            return 0.0
        recent = [r[1] for r in list(history)[-5:]]
        avg = sum(recent) / len(recent)
        trend = recent[-1] - recent[-2] if len(recent) >= 2 else 0
        return max(0, avg + trend)

    def _reroute(self, dpid, congested_port):
        datapath = self.datapaths.get(dpid)
        if not datapath:
            return

        all_ports = [
            p.port_no for p in datapath.ports.values()
            if p.port_no <= 0xffffff00 and p.port_no != congested_port
        ]
        if not all_ports:
            self.logger.info("[LB] No alternate ports on DPID=%d (single-path topology)", dpid)
            return

        alt_port = all_ports[0]
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(in_port=congested_port)
        actions = [parser.OFPActionOutput(alt_port)]

        self._add_flow(datapath, 400, match, actions, idle_timeout=15)
        self.logger.info("[LB] Rerouted DPID=%d: port %d -> %d (idle_timeout=15s)", dpid, congested_port, alt_port)

    def _add_flow(self, datapath, priority, match, actions, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            instructions=inst, idle_timeout=idle_timeout,
        )
        datapath.send_msg(mod)
