#!/usr/bin/env python3
"""VLAN Controller v5: clean ingress/egress VLAN Push/Pop logic.
- Host ingress (no tag): Push VLAN, flood
- Trunk ingress (already tagged): Forward as-is
- Host egress: Pop VLAN before delivering"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, vlan


class VLANController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    SIMPLE_TOPO_PORTS = {
        1: {"trunk": 3, "hosts": {1: 10, 2: 20}},
        2: {"trunk": 1, "hosts": {2: 10, 3: 20}},
    }

    HOST_VLAN = {
        "00:00:00:00:00:01": 10, "00:00:00:00:00:03": 10,
        "00:00:00:00:00:02": 20, "00:00:00:00:00:04": 20,
    }

    def __init__(self, *args, **kwargs):
        super(VLANController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.port_vlans = {}
        self.host_ports_done = set()

    def _add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, priority=priority,
            match=match, instructions=inst))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        self.logger.info("Switch connected: DPID=%d", datapath.id)
        self._add_flow(datapath, 0, parser.OFPMatch(),
                       [parser.OFPActionOutput(datapath.ofproto.OFPP_CONTROLLER,
                                                datapath.ofproto.OFPCML_NO_BUFFER)])
        if datapath.id in self.SIMPLE_TOPO_PORTS:
            self._install_static_simple_topo_rules(datapath)

    def _install_static_simple_topo_rules(self, datapath):
        dpid = datapath.id
        parser = datapath.ofproto_parser
        cfg = self.SIMPLE_TOPO_PORTS[dpid]
        trunk = cfg["trunk"]

        self.logger.info("[DPID=%d] Installing static SimpleTopo VLAN rules: %s",
                         dpid, cfg)

        for host_port, v_id in cfg["hosts"].items():
            push_actions = [
                parser.OFPActionPushVlan(0x8100),
                parser.OFPActionSetField(vlan_vid=(0x1000 | v_id)),
                parser.OFPActionOutput(trunk),
            ]
            self._add_flow(datapath, 500, parser.OFPMatch(in_port=host_port), push_actions)
            self.logger.info("  PUSH port=%d VLAN=%d -> trunk=%d",
                             host_port, v_id, trunk)

            pop_match = parser.OFPMatch(in_port=trunk, vlan_vid=(0x1000 | v_id))
            pop_actions = [parser.OFPActionPopVlan(), parser.OFPActionOutput(host_port)]
            self._add_flow(datapath, 500, pop_match, pop_actions)
            self.logger.info("  POP  trunk=%d VLAN=%d -> port=%d",
                             trunk, v_id, host_port)

        self._add_flow(datapath, 1, parser.OFPMatch(), [])
        self.host_ports_done.add(dpid)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match.get("in_port", 0)

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth:
            return

        src, dst = eth.src, eth.dst
        has_tag = pkt.get_protocol(vlan.vlan) is not None

        self.mac_to_port.setdefault(dpid, {})[src] = in_port
        if src in self.HOST_VLAN:
            self.port_vlans.setdefault((dpid, in_port), set()).add(self.HOST_VLAN[src])
            if not has_tag and dpid not in self.host_ports_done:
                host_p = self._get_host_ports(dpid)
                all_p = self._get_all_known_ports(dpid)
                has_trunk = any(len(self.port_vlans.get((dpid, p), set())) > 1
                                for p in all_p)
                if len(host_p) >= 2 and len(all_p) >= 3 and has_trunk:
                    self._install_vlan_rules(datapath)
                    self.host_ports_done.add(dpid)

        actions = []
        out_port = ofproto.OFPP_FLOOD

        src_vid = self.HOST_VLAN.get(src)
        dst_vid = self.HOST_VLAN.get(dst)

        if src_vid and not has_tag:
            actions.append(parser.OFPActionPushVlan(0x8100))
            actions.append(parser.OFPActionSetField(vlan_vid=(0x1000 | src_vid)))

        if dst_vid:
            if dst in self.mac_to_port.get(dpid, {}):
                out_port = self.mac_to_port[dpid][dst]
                host_ports = self._get_host_ports(dpid)
                if out_port in host_ports:
                    actions.append(parser.OFPActionPopVlan())
                actions.append(parser.OFPActionOutput(out_port))
                return self._send_packet_out(msg, actions)

        actions.append(parser.OFPActionOutput(ofproto.OFPP_FLOOD))
        self._send_packet_out(msg, actions)

    def _send_packet_out(self, msg, actions):
        datapath = msg.datapath
        data = msg.data if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER else None
        datapath.send_msg(datapath.ofproto_parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id,
            in_port=msg.match.get("in_port", 0),
            actions=actions, data=data))

    def _is_host_port(self, dpid, port_no):
        vlans = self.port_vlans.get((dpid, port_no), set())
        return len(vlans) == 1

    def _get_host_ports(self, dpid):
        result = {}
        for (sw, port), vlans in self.port_vlans.items():
            if sw == dpid and len(vlans) == 1:
                result[port] = list(vlans)[0]
        return result

    def _get_all_known_ports(self, dpid):
        return {p for (sw, p) in self.port_vlans if sw == dpid}

    def _install_vlan_rules(self, datapath):
        dpid = datapath.id
        parser = datapath.ofproto_parser
        host_ports = self._get_host_ports(dpid)
        all_ports = self._get_all_known_ports(dpid)

        if len(host_ports) < 2:
            return

        trunk_ports = all_ports - set(host_ports.keys())

        self.logger.info("[DPID=%d] Installing VLAN rules: hosts=%s, trunk=%s",
                         dpid, host_ports, trunk_ports)

        for host_port, v_id in host_ports.items():
            push_actions = [
                parser.OFPActionPushVlan(0x8100),
                parser.OFPActionSetField(vlan_vid=(0x1000 | v_id)),
            ]
            for tp in sorted(trunk_ports):
                push_actions.append(parser.OFPActionOutput(int(tp)))

            self._add_flow(datapath, 500, parser.OFPMatch(in_port=host_port), push_actions)
            self.logger.info("  PUSH port=%d VLAN=%d -> trunk=%s", host_port, v_id, sorted(trunk_ports))

            pop_match = parser.OFPMatch(vlan_vid=(0x1000 | v_id))
            pop_actions = [parser.OFPActionPopVlan(), parser.OFPActionOutput(host_port)]
            self._add_flow(datapath, 500, pop_match, pop_actions)
            self.logger.info("  POP  VLAN=%d -> port=%d", v_id, host_port)
