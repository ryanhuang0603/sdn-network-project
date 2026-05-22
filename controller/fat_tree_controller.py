#!/usr/bin/env python3
"""Fat-tree controller with deterministic forwarding and ARP proxy.

This controller intentionally avoids OFPP_FLOOD. A k=4 fat tree has L2 loops,
so a learning-switch flood strategy can create broadcast storms. The topology
script assigns deterministic DPIDs, IPs, MACs, and port orders; this controller
uses those conventions to install destination-IP forwarding rules.
"""

import os

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import arp, ethernet, ether_types, ipv4, packet
from ryu.ofproto import ofproto_v1_3


class FatTreeController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(FatTreeController, self).__init__(*args, **kwargs)
        self.k = int(os.environ.get("FAT_TREE_K", "4"))
        if self.k <= 0 or self.k % 2:
            raise ValueError("FAT_TREE_K must be a positive even integer")

        self.datapaths = {}
        self.agg_count = self.k // 2
        self.edge_count = self.k // 2
        self.hosts_per_edge = self.k // 2
        self.num_core = self.agg_count ** 2
        self.switches_per_pod = self.agg_count + self.edge_count
        self.hosts_by_ip = self._build_host_table()
        self.enable_ecmp = os.environ.get("FAT_TREE_ECMP", "0") == "1"
        self.enable_agg_select = os.environ.get("FAT_TREE_AGG_SELECT", "0") == "1"
        self.ecmp_group_id = 1

        self.logger.info(
            "FatTreeController initialized: k=%d switches=%d hosts=%d ecmp=%s agg_select=%s",
            self.k, self.num_core + self.k * self.switches_per_pod,
            len(self.hosts_by_ip), self.enable_ecmp, self.enable_agg_select,
        )

    def _build_host_table(self):
        hosts = {}
        for pod in range(self.k):
            for edge in range(self.edge_count):
                for host in range(1, self.hosts_per_edge + 1):
                    ip_addr = "10.%d.%d.%d" % (pod, edge, host)
                    hosts[ip_addr] = {
                        "ip": ip_addr,
                        "mac": "00:00:00:%02x:%02x:%02x" % (pod, edge, host),
                        "pod": pod,
                        "edge": edge,
                        "host": host,
                    }
        return hosts

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        self._add_flow(
            datapath, 0, parser.OFPMatch(),
            [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                    ofproto.OFPCML_NO_BUFFER)],
        )
        if self.enable_ecmp:
            self._install_ecmp_group(datapath)
        self._install_ipv4_routes(datapath)
        self.logger.info("Switch connected: DPID=%d role=%s",
                         datapath.id, self._switch_role(datapath.id))

    def _install_ecmp_group(self, datapath):
        role = self._switch_role(datapath.id)
        role_type = role["type"]
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        if role_type == "edge":
            output_ports = list(range(1, self.agg_count + 1))
        elif role_type == "agg" and self.enable_agg_select:
            output_ports = list(range(self.edge_count + 1,
                                      self.edge_count + self.agg_count + 1))
        else:
            return

        delete = parser.OFPGroupMod(
            datapath, ofproto.OFPGC_DELETE, ofproto.OFPGT_SELECT,
            self.ecmp_group_id, [],
        )
        datapath.send_msg(delete)

        buckets = [
            parser.OFPBucket(
                weight=100,
                watch_port=ofproto.OFPP_ANY,
                watch_group=ofproto.OFPG_ANY,
                actions=[parser.OFPActionOutput(port)],
            )
            for port in output_ports
        ]
        add = parser.OFPGroupMod(
            datapath, ofproto.OFPGC_ADD, ofproto.OFPGT_SELECT,
            self.ecmp_group_id, buckets,
        )
        datapath.send_msg(add)
        self.logger.info("[ECMP] DPID=%d role=%s group=%d ports=%s",
                         datapath.id, role_type, self.ecmp_group_id, output_ports)

    def _install_ipv4_routes(self, datapath):
        parser = datapath.ofproto_parser
        for host in self.hosts_by_ip.values():
            actions = self._actions_to_host(datapath, host)
            if not actions:
                continue
            match = parser.OFPMatch(
                eth_type=ether_types.ETH_TYPE_IP,
                ipv4_dst=host["ip"],
            )
            self._add_flow(datapath, 100, match, actions)

    def _add_flow(self, datapath, priority, match, actions):
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(
            datapath.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
        )
        datapath.send_msg(mod)

    def _switch_role(self, dpid):
        if dpid <= self.num_core:
            core_index = dpid - 1
            return {
                "type": "core",
                "core": core_index,
                "group": core_index // self.agg_count,
                "offset": core_index % self.agg_count,
            }

        pod_offset = dpid - self.num_core - 1
        if pod_offset < 0:
            return {"type": "unknown"}

        pod = pod_offset // self.switches_per_pod
        pos = pod_offset % self.switches_per_pod
        if pod >= self.k:
            return {"type": "unknown"}
        if pos < self.agg_count:
            return {"type": "agg", "pod": pod, "agg": pos}
        return {"type": "edge", "pod": pod, "edge": pos - self.agg_count}

    def _preferred_agg(self, host):
        return host["edge"] % self.agg_count

    def _preferred_core_offset(self, host):
        return (host["host"] - 1) % self.agg_count

    def _next_port_to_host(self, dpid, host):
        role = self._switch_role(dpid)
        role_type = role["type"]

        if role_type == "core":
            return host["pod"] + 1

        if role_type == "agg":
            if role["pod"] == host["pod"]:
                return host["edge"] + 1
            return self.edge_count + self._preferred_core_offset(host) + 1

        if role_type == "edge":
            if role["pod"] == host["pod"] and role["edge"] == host["edge"]:
                return self.agg_count + host["host"]
            return self._preferred_agg(host) + 1

        return None

    def _actions_to_host(self, datapath, host):
        role = self._switch_role(datapath.id)
        parser = datapath.ofproto_parser

        if self.enable_ecmp:
            if role["type"] == "edge":
                is_local = role["pod"] == host["pod"] and role["edge"] == host["edge"]
                if not is_local:
                    return [parser.OFPActionGroup(self.ecmp_group_id)]
            elif (role["type"] == "agg" and role["pod"] != host["pod"]
                  and self.enable_agg_select):
                return [parser.OFPActionGroup(self.ecmp_group_id)]

        out_port = self._next_port_to_host(datapath.id, host)
        if out_port is None:
            return []
        return [parser.OFPActionOutput(out_port)]

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match.get("in_port", 0)

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is not None:
            self._handle_arp(datapath, in_port, eth, arp_pkt)
            return

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt is not None:
            self._forward_ipv4_packet(msg, ip_pkt.dst)

    def _handle_arp(self, datapath, in_port, eth, arp_pkt):
        if arp_pkt.opcode != arp.ARP_REQUEST:
            return

        target = self.hosts_by_ip.get(arp_pkt.dst_ip)
        if target is None:
            self.logger.warning("Unknown ARP target: %s", arp_pkt.dst_ip)
            return

        reply = packet.Packet()
        reply.add_protocol(ethernet.ethernet(
            ethertype=ether_types.ETH_TYPE_ARP,
            dst=eth.src,
            src=target["mac"],
        ))
        reply.add_protocol(arp.arp(
            opcode=arp.ARP_REPLY,
            src_mac=target["mac"],
            src_ip=target["ip"],
            dst_mac=arp_pkt.src_mac,
            dst_ip=arp_pkt.src_ip,
        ))
        reply.serialize()

        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(in_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=datapath.ofproto.OFP_NO_BUFFER,
            in_port=datapath.ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=reply.data,
        )
        datapath.send_msg(out)

    def _forward_ipv4_packet(self, msg, dst_ip):
        datapath = msg.datapath
        target = self.hosts_by_ip.get(dst_ip)
        if target is None:
            self.logger.warning("Unknown IPv4 target: %s", dst_ip)
            return

        actions = self._actions_to_host(datapath, target)
        if not actions:
            self.logger.warning("No route on DPID=%d for dst=%s",
                                datapath.id, dst_ip)
            return

        parser = datapath.ofproto_parser
        data = msg.data if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=msg.match.get("in_port", 0),
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)
