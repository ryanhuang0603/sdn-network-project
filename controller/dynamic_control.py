#!/usr/bin/env python3
"""Dynamic Network Control Controller: supports hard_timeout flow rules
to temporarily block or modify traffic paths via REST API or direct flow mod."""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls,
)
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
import json
import os
import time


class DynamicControlController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(DynamicControlController, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.active_blocks = {}
        if os.environ.get("DYNAMIC_DEMO") == "1":
            self.demo_thread = hub.spawn(self._demo_block_loop)

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
            self.logger.info("Switch connected: DPID=%d", datapath.id)
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                del self.datapaths[datapath.id]

    def block_flow(self, dpid, priority=900, hard_timeout=20,
                   in_port=None, dl_src=None, dl_dst=None, dl_type=None,
                   nw_src=None, nw_dst=None, nw_proto=None, tp_src=None, tp_dst=None):
        """Install a block rule (drop action) with hard_timeout on a switch."""
        datapath = self.datapaths.get(dpid)
        if not datapath:
            self.logger.error("Switch DPID=%d not connected", dpid)
            return False

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match_kwargs = {}
        if in_port is not None:
            match_kwargs["in_port"] = in_port
        if dl_src is not None:
            match_kwargs["eth_src"] = dl_src
        if dl_dst is not None:
            match_kwargs["eth_dst"] = dl_dst
        if dl_type is not None:
            match_kwargs["eth_type"] = dl_type
        if nw_src is not None:
            match_kwargs["ipv4_src"] = nw_src
        if nw_dst is not None:
            match_kwargs["ipv4_dst"] = nw_dst
        if nw_proto is not None:
            match_kwargs["ip_proto"] = nw_proto
        if tp_src is not None:
            match_kwargs["tcp_src"] = tp_src
        if tp_dst is not None:
            match_kwargs["tcp_dst"] = tp_dst

        match = parser.OFPMatch(**match_kwargs)
        actions = []
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            hard_timeout=hard_timeout,
            cookie=0xDEAD,
        )
        datapath.send_msg(mod)

        block_id = f"{dpid}_{hash(json.dumps(match_kwargs, sort_keys=True))}"
        self.active_blocks[block_id] = {
            "dpid": dpid,
            "match": match_kwargs,
            "hard_timeout": hard_timeout,
        }

        self.logger.info("Block flow installed on DPID=%d, hard_timeout=%ds, match=%s",
                         dpid, hard_timeout, match_kwargs)
        return True

    def block_host_pair(self, host_a_mac, host_b_mac, duration=20):
        """Block communication between two hosts on all connected switches."""
        for dpid in self.datapaths:
            self.block_flow(
                dpid=dpid, priority=900, hard_timeout=duration,
                dl_src=host_a_mac, dl_dst=host_b_mac,
            )
            self.block_flow(
                dpid=dpid, priority=900, hard_timeout=duration,
                dl_src=host_b_mac, dl_dst=host_a_mac,
            )
        self.logger.info("Blocked %s <-> %s for %ds", host_a_mac, host_b_mac, duration)
        return True

    def block_port(self, dpid, port_no, duration=20):
        """Block all traffic on a specific port for a duration."""
        return self.block_flow(dpid=dpid, priority=400, hard_timeout=duration,
                               in_port=port_no)

    def clear_all_blocks(self):
        """Remove all active block rules."""
        for dpid in self.datapaths:
            self._clear_switch_blocks(dpid)
        self.active_blocks.clear()

    def _clear_switch_blocks(self, dpid):
        datapath = self.datapaths.get(dpid)
        if not datapath:
            return
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        mod = parser.OFPFlowMod(
            datapath=datapath, cookie=0xDEAD, cookie_mask=0xFFFFFFFFFFFFFFFF,
            command=ofproto.OFPFC_DELETE, out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
        )
        datapath.send_msg(mod)

    def get_active_blocks(self):
        return dict(self.active_blocks)

    def _demo_block_loop(self):
        delay = float(os.environ.get("DYNAMIC_DEMO_DELAY", "8"))
        duration = int(os.environ.get("DYNAMIC_DEMO_DURATION", "20"))
        host_a = os.environ.get("DYNAMIC_DEMO_HOST_A", "00:00:00:00:00:01")
        host_b = os.environ.get("DYNAMIC_DEMO_HOST_B", "00:00:00:00:00:03")

        self.logger.info(
            "[DEMO] Dynamic block scheduled: %s <-> %s %.1fs after datapath connection for %ds",
            host_a, host_b, delay, duration,
        )

        wait_start = time.time()
        while not self.datapaths and time.time() - wait_start < 10:
            hub.sleep(0.5)

        if not self.datapaths:
            self.logger.error("[DEMO] No datapaths connected; dynamic block skipped")
            return

        hub.sleep(delay)
        self.block_host_pair(host_a, host_b, duration=duration)
        self.logger.info(
            "[DEMO] hard_timeout block installed for %s <-> %s; expected auto-recovery in %ds",
            host_a, host_b, duration,
        )
