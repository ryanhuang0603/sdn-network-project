#!/usr/bin/env python3
"""Topology startup for controller mode: no manual flow rules, relies on Ryu controller."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from topology.simple_topo import SimpleTopo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink


def main():
    setLogLevel("info")
    topo = SimpleTopo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(name, ip="127.0.0.1", port=6653),
        switch=OVSSwitch,
        link=TCLink,
    )
    net.start()

    info("\n*** Topology started with remote controller\n")
    info("*** Waiting for controller to install flow rules...\n")
    info("*** Try 'pingall' in CLI after rules are installed\n\n")

    CLI(net)

    info("\n*** Dumping flow tables\n")
    for sw in net.switches:
        info(f"\n=== {sw.name} flows ===\n")
        os.system(f"ovs-ofctl -O OpenFlow13 dump-flows {sw.name}")

    net.stop()


if __name__ == "__main__":
    main()
