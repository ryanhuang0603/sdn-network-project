#!/usr/bin/env python3
"""Monitor Controller: polls OpenFlow port statistics from switches periodically
and computes moving-average predictions in real time."""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
import csv
import os
import time
from collections import deque


class MonitorController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    POLL_INTERVAL = 2

    def __init__(self, *args, **kwargs):
        super(MonitorController, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.port_stats = {}
        self.port_history = {}
        self.csv_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "port_stats_log.csv"
        )
        self._init_csv()
        self.monitor_thread = hub.spawn(self._monitor_loop)

    def _init_csv(self):
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        if not os.path.isfile(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "switch_dpid", "port_no",
                    "tx_bytes", "rx_bytes", "tx_rate_mbps", "rx_rate_mbps",
                    "predicted_tx_mbps", "predicted_rx_mbps",
                ])

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        self.logger.info("Switch connected: DPID=%d", datapath.id)

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
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
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

            tx_bytes, rx_bytes = stat.tx_bytes, stat.rx_bytes
            key = (dpid, port_no)
            previous = self.port_stats.get(key)
            self.port_stats[key] = (timestamp, tx_bytes, rx_bytes)

            if previous is None:
                continue

            prev_time, prev_tx, prev_rx = previous
            delta = timestamp - prev_time
            if delta <= 0:
                continue

            tx_rate = (tx_bytes - prev_tx) * 8.0 / delta / 1e6
            rx_rate = (rx_bytes - prev_rx) * 8.0 / delta / 1e6

            self.port_history.setdefault(key, deque(maxlen=50))
            self.port_history[key].append((timestamp, tx_rate, rx_rate))

            pred_tx, pred_rx = self._predict(key)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

            self._log_csv([ts, dpid, port_no, tx_bytes, rx_bytes,
                          f"{tx_rate:.2f}", f"{rx_rate:.2f}",
                          f"{pred_tx:.2f}", f"{pred_rx:.2f}"])

    def _predict(self, key):
        history = self.port_history.get(key)
        if not history or len(history) < 2:
            return 0.0, 0.0
        window = min(5, len(history))
        recent_tx = [r[1] for r in list(history)[-window:]]
        recent_rx = [r[2] for r in list(history)[-window:]]
        avg_tx = sum(recent_tx) / window
        avg_rx = sum(recent_rx) / window
        trend_tx = recent_tx[-1] - recent_tx[-2] if len(recent_tx) >= 2 else 0
        trend_rx = recent_rx[-1] - recent_rx[-2] if len(recent_rx) >= 2 else 0
        return max(0, avg_tx + trend_tx), max(0, avg_rx + trend_rx)

    def _log_csv(self, row):
        try:
            with open(self.csv_path, "a", newline="") as f:
                csv.writer(f).writerow(row)
        except Exception:
            pass

    def get_history(self, dpid, port_no):
        return list(self.port_history.get((dpid, port_no), []))
