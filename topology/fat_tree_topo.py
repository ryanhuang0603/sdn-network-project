#!/usr/bin/env python3
"""Fat-tree topology for data center networks. Supports ECMP multi-path load balancing.

k=4 configuration:
  - 4 pods, each pod has k/2=2 aggregation switches and k/2=2 edge switches
  - (k/2)^2=4 core switches
  - k^3/4=16 hosts

Layers:
  Core:    k^2/4 switches
  Aggregation: k^2/2 switches (k/2 per pod)
  Edge:    k^2/2 switches (k/2 per pod)
  Hosts:   k^3/4 hosts
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import argparse
import os
import subprocess
import time


class FatTreeTopo(Topo):
    """k-ary fat tree topology."""

    def __init__(self, k=4, bw_core=100, bw_agg=50, bw_edge=10, **opts):
        """
        Args:
            k: number of ports per switch (must be even, typically 4)
            bw_core: bandwidth of core-aggregation links in Mbps
            bw_agg: bandwidth of aggregation-edge links in Mbps
            bw_edge: bandwidth of edge-host links in Mbps
        """
        Topo.__init__(self, **opts)
        if k % 2 != 0:
            raise ValueError("k must be even")
        self.k = k
        self.bw_core = bw_core
        self.bw_agg = bw_agg
        self.bw_edge = bw_edge
        self._build()

    def _build(self):
        k = self.k
        num_pods = k
        num_core = (k // 2) ** 2
        num_agg_per_pod = k // 2
        num_edge_per_pod = k // 2
        num_hosts_per_edge = k // 2

        info("*** Building Fat-Tree (k=%d)\n" % k)
        info("    Core switches: %d\n" % num_core)
        info("    Pods: %d (each: %d agg + %d edge)\n" %
             (num_pods, num_agg_per_pod, num_edge_per_pod))
        info("    Hosts: %d\n" % (k ** 3 // 4))

        dpid_counter = 1

        core_switches = []
        for i in range(num_core):
            name = "c%d" % (i + 1)
            dpid = "%016x" % dpid_counter
            dpid_counter += 1
            sw = self.addSwitch(name, dpid=dpid, protocols="OpenFlow13")
            core_switches.append(sw)

        hosts = []
        host_idx = 0

        for pod in range(num_pods):
            agg_switches = []
            for a in range(num_agg_per_pod):
                name = "a%d%d" % (pod, a)
                dpid = "%016x" % dpid_counter
                dpid_counter += 1
                sw = self.addSwitch(name, dpid=dpid, protocols="OpenFlow13")
                agg_switches.append(sw)

            edge_switches = []
            for e in range(num_edge_per_pod):
                name = "e%d%d" % (pod, e)
                dpid = "%016x" % dpid_counter
                dpid_counter += 1
                sw = self.addSwitch(name, dpid=dpid, protocols="OpenFlow13")
                edge_switches.append(sw)

            for a, agg in enumerate(agg_switches):
                for e, edge in enumerate(edge_switches):
                    self.addLink(agg, edge, bw=self.bw_agg)

            for c, core in enumerate(core_switches):
                for a, agg in enumerate(agg_switches):
                    core_group = c // (k // 2)
                    if core_group == a:
                        self.addLink(core, agg, bw=self.bw_core)

            for e, edge in enumerate(edge_switches):
                for h in range(num_hosts_per_edge):
                    host_idx += 1
                    host_ip = "10.%d.%d.%d" % (pod, e, h + 1)
                    host_mac = "00:00:00:%02x:%02x:%02x" % (pod, e, h + 1)
                    host_name = "h%d" % host_idx
                    host = self.addHost(host_name, ip=host_ip + "/8", mac=host_mac)
                    self.addLink(host, edge, bw=self.bw_edge)
                    hosts.append(host)

        info("*** Fat-Tree built successfully\n")


class FatTreeNet:
    """Wrapper for creating and managing a fat-tree Mininet network."""

    def __init__(self, k=4, controller_ip="127.0.0.1", controller_port=6653,
                 bw_core=100, bw_agg=50, bw_edge=10):
        self.k = k
        self.controller_ip = controller_ip
        self.controller_port = controller_port
        self.bw_core = bw_core
        self.bw_agg = bw_agg
        self.bw_edge = bw_edge
        self.net = None

    def start(self):
        topo = FatTreeTopo(
            k=self.k, bw_core=self.bw_core,
            bw_agg=self.bw_agg, bw_edge=self.bw_edge,
        )
        self.net = Mininet(
            topo=topo,
            controller=lambda name: RemoteController(
                name, ip=self.controller_ip, port=self.controller_port,
            ),
            switch=OVSSwitch,
            link=TCLink,
        )
        self.net.start()
        info("*** Fat-tree network started\n")
        return self.net

    def stop(self):
        if self.net:
            self.net.stop()

    def cli(self):
        if self.net:
            CLI(self.net)

    def get_hosts(self):
        if self.net:
            return self.net.hosts
        return []

    def install_ecmp_groups(self):
        """Install ECMP group tables on edge/agg switches for multi-path load balancing."""
        raise NotImplementedError(
            "ECMP group installation is not implemented yet. "
            "Use controller/fat_tree_controller.py with FAT_TREE_ECMP=1."
        )


def run_ecmp_demo(net, report_file, duration=8):
    """Run cross-pod iperf3 flows and save group/port evidence."""
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    pairs = [
        ("h1", "h16", 5201),
        ("h2", "h15", 5202),
        ("h3", "h14", 5203),
        ("h4", "h13", 5204),
    ]
    lines = [
        "Fat-tree ECMP demo report",
        "Expected controller mode: FAT_TREE_ECMP=1",
        "",
    ]

    info("\n*** Running ECMP demo flows\n")
    servers = []
    for _src_name, dst_name, port in pairs:
        dst = net.get(dst_name)
        servers.append((dst_name, dst.popen(
            ["iperf3", "-s", "-1", "-p", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )))

    time.sleep(1)

    clients = []
    for src_name, dst_name, port in pairs:
        src = net.get(src_name)
        dst = net.get(dst_name)
        lines.append("$ %s iperf3 -c %s -p %d -t %d -f m" %
                     (src_name, dst.IP(), port, duration))
        clients.append((src_name, src.popen(
            ["iperf3", "-c", dst.IP(), "-p", str(port), "-t", str(duration), "-f", "m"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )))

    for src_name, proc in clients:
        output, _ = proc.communicate()
        lines.append("=== client %s ===" % src_name)
        lines.append((output or "").strip())
        lines.append("")

    for dst_name, proc in servers:
        try:
            output, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.terminate()
            output, _ = proc.communicate(timeout=3)
        lines.append("=== server %s ===" % dst_name)
        lines.append((output or "").strip())
        lines.append("")

    for sw_name in ["e00", "a00", "a01", "e01"]:
        lines.append("=== ovs-ofctl dump-groups %s ===" % sw_name)
        lines.append(_run_ovs_ofctl(["dump-groups", sw_name]))
        lines.append("")
        lines.append("=== ovs-ofctl dump-ports %s ===" % sw_name)
        lines.append(_run_ovs_ofctl(["dump-ports", sw_name]))
        lines.append("")

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")
    os.chmod(report_file, 0o644)
    info("*** ECMP report saved to %s\n" % report_file)


def _run_ovs_ofctl(args):
    result = subprocess.run(
        ["ovs-ofctl", "-O", "OpenFlow13"] + args,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result.stderr.strip()
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Start a k-ary fat-tree Mininet topology.")
    parser.add_argument("--k", type=int, default=4, help="Fat-tree k value, must be even.")
    parser.add_argument("--controller-ip", default="127.0.0.1", help="Remote controller IP.")
    parser.add_argument("--controller-port", type=int, default=6653, help="Remote controller port.")
    parser.add_argument("--bw-core", type=float, default=100, help="Core-aggregation bandwidth in Mbps.")
    parser.add_argument("--bw-agg", type=float, default=50, help="Aggregation-edge bandwidth in Mbps.")
    parser.add_argument("--bw-edge", type=float, default=10, help="Edge-host bandwidth in Mbps.")
    parser.add_argument("--pingall", action="store_true", help="Run pingall after startup.")
    parser.add_argument("--startup-wait", type=float, default=2.0,
                        help="Seconds to wait before optional pingall.")
    parser.add_argument("--ecmp-demo", action="store_true",
                        help="Run cross-pod iperf3 flows and save ECMP evidence.")
    parser.add_argument("--ecmp-duration", type=int, default=8,
                        help="iperf3 duration for --ecmp-demo.")
    parser.add_argument("--ecmp-report", default=os.path.join("data", "fat_tree_ecmp_report.txt"),
                        help="Output report for --ecmp-demo.")
    parser.add_argument("--no-cli", action="store_true", help="Exit after optional tests instead of opening CLI.")
    args = parser.parse_args()

    setLogLevel("info")
    topo = FatTreeTopo(
        k=args.k,
        bw_core=args.bw_core,
        bw_agg=args.bw_agg,
        bw_edge=args.bw_edge,
    )
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip=args.controller_ip, port=args.controller_port),
        switch=OVSSwitch,
        link=TCLink,
    )
    try:
        net.start()
        if args.pingall:
            time.sleep(args.startup_wait)
            info("\n*** Running pingall\n")
            net.pingAll()

        if args.ecmp_demo:
            time.sleep(args.startup_wait)
            run_ecmp_demo(net, args.ecmp_report, duration=args.ecmp_duration)

        if not args.no_cli:
            info("\n*** Starting CLI\n")
            CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    main()
