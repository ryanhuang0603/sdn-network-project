#!/usr/bin/env python3
"""Simple topology: 2 switches (OpenFlow 1.3), 4 hosts, remote Ryu controller."""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import argparse
import os
import json
import re
import shutil
import subprocess
import sys
import time


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)


class SimpleTopo(Topo):
    def __init__(self, **opts):
        Topo.__init__(self, **opts)

        s1 = self.addSwitch("s1", dpid="0000000000000001", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", dpid="0000000000000002", protocols="OpenFlow13")

        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
        h3 = self.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
        h4 = self.addHost("h4", ip="10.0.0.4/24", mac="00:00:00:00:00:04")

        self.addLink(h1, s1, bw=10, delay="5ms", loss=1)
        self.addLink(h2, s1, bw=10, delay="5ms", loss=1)
        self.addLink(s1, s2, bw=20, delay="3ms", loss=0.5)
        self.addLink(h3, s2, bw=10, delay="5ms", loss=1)
        self.addLink(h4, s2, bw=10, delay="5ms", loss=1)


def manual_flow_rules(net):
    """Install manual flow rules via ovs-ofctl for basic communication rules:
    h1 <-> h3, h2 <-> h4, others blocked.

    Strategy (per switch):
      Priority 300: Unicast forwarding host->trunk (MAC-based)
      Priority 300: Unicast forwarding trunk->host (MAC-based)
      Priority 200: Broadcast flood (trunk <-> all host ports)
      Priority 150: Drop cross-VLAN traffic
      Priority 0:   Drop all (default)
    """
    s1 = net.get("s1")
    s2 = net.get("s2")

    info("\n*** Installing manual flow rules via ovs-ofctl\n")

    s1_ph1 = s1.ports[s1.connectionsTo(net.get("h1"))[0][0]]
    s1_ph2 = s1.ports[s1.connectionsTo(net.get("h2"))[0][0]]
    s1_ps2 = s1.ports[s1.connectionsTo(s2)[0][0]]

    s2_ph3 = s2.ports[s2.connectionsTo(net.get("h3"))[0][0]]
    s2_ph4 = s2.ports[s2.connectionsTo(net.get("h4"))[0][0]]
    s2_ps1 = s2.ports[s2.connectionsTo(s1)[0][0]]

    MAC = {
        "h1": "00:00:00:00:00:01", "h2": "00:00:00:00:00:02",
        "h3": "00:00:00:00:00:03", "h4": "00:00:00:00:00:04",
    }

    s1_hosts = [("h1", s1_ph1), ("h2", s1_ph2)]
    s2_hosts = [("h3", s2_ph3), ("h4", s2_ph4)]

    rules = []

    for sw, host_list, trunk_port in [
        (s1, s1_hosts, s1_ps2),
        (s2, s2_hosts, s2_ps1),
    ]:
        name = sw.name
        hports = [p for _, p in host_list]

        for hname, hport in host_list:
            mac = MAC[hname]
            rules.append((name, f"priority=300,in_port={hport},dl_src={mac},actions=output:{trunk_port}"))
            rules.append((name, f"priority=300,in_port={trunk_port},dl_dst={mac},actions=output:{hport}"))

        broadcast_forward = f"output:{','.join(str(p) for p in hports)}"
        rules.append((name, f"priority=200,in_port={trunk_port},dl_dst=ff:ff:ff:ff:ff:ff,actions={broadcast_forward}"))
        rules.append((name, f"priority=200,arp,in_port={trunk_port},actions={broadcast_forward}"))

        for hname, hport in host_list:
            rules.append((name, f"priority=200,arp,in_port={hport},actions=output:{trunk_port}"))

    allowed_pairs = {(MAC["h1"], MAC["h3"]), (MAC["h3"], MAC["h1"]),
                     (MAC["h2"], MAC["h4"]), (MAC["h4"], MAC["h2"])}
    all_macs = [MAC["h1"], MAC["h2"], MAC["h3"], MAC["h4"]]
    for smac in all_macs:
        for dmac in all_macs:
            if smac == dmac:
                continue
            if (smac, dmac) not in allowed_pairs:
                rules.append(("s1", f"priority=400,dl_src={smac},dl_dst={dmac},actions=drop"))
                rules.append(("s2", f"priority=400,dl_src={smac},dl_dst={dmac},actions=drop"))

    for name, rule in rules:
        cmd = f"ovs-ofctl -O OpenFlow13 add-flow {name} \"{rule}\""
        info(f"  [{name}] {cmd}\n")
        os.system(cmd)

    config = {
        "switch_ports": {
            "s1": {"h1": s1_ph1, "h2": s1_ph2, "s2": s1_ps2},
            "s2": {"h3": s2_ph3, "h4": s2_ph4, "s1": s2_ps1},
        },
        "rules": [[name, rule] for name, rule in rules],
    }
    flow_config_path = os.path.join(PROJECT_DIR, "data", "flow_config.json")
    os.makedirs(os.path.dirname(flow_config_path), exist_ok=True)
    with open(flow_config_path, "w") as f:
        json.dump(config, f, indent=2)
    info("\n*** Flow config saved to %s\n" % flow_config_path)


def test_connectivity(net):
    """Run connectivity tests after flow rules are installed."""
    info("\n*** Testing connectivity\n")
    h1, h2, h3, h4 = net.get("h1", "h2", "h3", "h4")

    for src, dst, label, expected in [
        (h1, h3, "h1->h3", True),
        (h3, h1, "h3->h1", True),
        (h2, h4, "h2->h4", True),
        (h4, h2, "h4->h2", True),
        (h1, h2, "h1->h2", False),
        (h1, h4, "h1->h4", False),
        (h2, h3, "h2->h3", False),
        (h3, h4, "h3->h4", False),
    ]:
        result = _directed_ping_loss(src, dst)
        ok = result < 100.0 if expected else result == 100.0
        status = "PASS" if ok else "FAIL"
        expectation = "reachable" if expected else "blocked"
        info(f"  [{status}] {label}: {result}% loss (expected {expectation})\n")


def _directed_ping_loss(src, dst, count=3):
    output = src.cmd("ping -c %d -W 1 %s" % (count, dst.IP()))
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    if not match:
        return 100.0
    return float(match.group(1))


def capture_vlan_tags(net, capture_file, summary_file, ping_count=3, capture_duration=8):
    """Capture VLAN-tagged frames on the s1-s2 trunk while generating test traffic."""
    os.makedirs(os.path.dirname(capture_file), exist_ok=True)
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)
    tmp_capture_file = os.path.join(
        "/tmp", "bighomework_vlan_trunk_%d.pcapng" % os.getpid())

    info("\n*** Starting VLAN capture on s1-eth3 -> %s\n" % capture_file)
    capture_cmd = [
        "tshark", "-i", "s1-eth3",
        "-f", "vlan",
        "-a", "duration:%d" % capture_duration,
        "-w", tmp_capture_file,
    ]
    try:
        capture_proc = subprocess.Popen(
            capture_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        info("*** VLAN capture skipped: tshark is not installed or not in PATH\n")
        return

    try:
        time.sleep(2)
        for src_name, dst_name in [("h1", "h3"), ("h2", "h4")]:
            src = net.get(src_name)
            dst = net.get(dst_name)
            info("*** Capturing VLAN traffic: %s -> %s\n" % (src_name, dst_name))
            src.cmd("ping -c %d -W 1 %s" % (ping_count, dst.IP()))
            time.sleep(1)
        capture_proc.wait(timeout=capture_duration + 5)
    finally:
        if capture_proc.poll() is None:
            capture_proc.terminate()
        _, stderr = capture_proc.communicate()
        if capture_proc.returncode not in (0, -15):
            info("*** VLAN capture warning: tshark exited with %s: %s\n" %
                 (capture_proc.returncode, stderr.strip()))

    if not os.path.isfile(tmp_capture_file):
        info("*** VLAN capture failed: %s was not created\n" % tmp_capture_file)
        return

    try:
        shutil.copyfile(tmp_capture_file, capture_file)
        os.chmod(capture_file, 0o644)
    except OSError as e:
        info("*** VLAN capture warning: could not copy pcap to %s: %s\n" %
             (capture_file, e))
        capture_file = tmp_capture_file

    summary_cmd = [
        "tshark", "-r", capture_file, "-Y", "vlan",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "vlan.id",
        "-e", "ip.src",
        "-e", "ip.dst",
        "-e", "arp.src.proto_ipv4",
        "-e", "arp.dst.proto_ipv4",
    ]
    result = subprocess.run(summary_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("frame\tvlan.id\tip.src\tip.dst\tarp.src\tarp.dst\n")
            f.write(result.stdout)
        os.chmod(summary_file, 0o644)
        info("*** VLAN capture summary saved to %s\n" % summary_file)
    else:
        info("*** VLAN summary warning: %s\n" % result.stderr.strip())


def run_dynamic_control_demo(net, total_duration=40, interval=5, src_name="h1", dst_name="h3"):
    """Periodically ping a host pair to show hard_timeout block and recovery."""
    src = net.get(src_name)
    dst = net.get(dst_name)
    start = time.time()
    info("\n*** Dynamic control demo: probing %s -> %s for %.1fs\n" %
         (src_name, dst_name, total_duration))
    while time.time() - start < total_duration:
        elapsed = time.time() - start
        loss = _directed_ping_loss(src, dst, count=3)
        state = "reachable" if loss < 100.0 else "blocked"
        info("*** [dynamic-demo %.1fs] %s->%s loss=%.1f%% state=%s\n" %
             (elapsed, src_name, dst_name, loss, state))
        time.sleep(interval)


def run_performance_test(net, report_file, iperf_duration=5):
    """Run ping and iperf3 tests to demonstrate TCLink bw/delay/loss settings."""
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    pairs = [("h1", "h3", 5201), ("h2", "h4", 5202)]
    lines = [
        "SDN performance limit test",
        "Topology settings:",
        "  host-switch links: bw=10Mbps delay=5ms loss=1%",
        "  s1-s2 trunk:       bw=20Mbps delay=3ms loss=0.5%",
        "",
    ]

    info("\n*** Running performance tests -> %s\n" % report_file)
    for src_name, dst_name, port in pairs:
        src = net.get(src_name)
        dst = net.get(dst_name)

        lines.append("=== %s -> %s ===" % (src_name, dst_name))
        lines.append("$ %s ping -c 10 -W 1 %s" % (src_name, dst.IP()))
        ping_output = src.cmd("ping -c 10 -W 1 %s" % dst.IP())
        lines.append(ping_output.strip())
        lines.append("")

        server = dst.popen(
            ["iperf3", "-s", "-1", "-p", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(1)
        lines.append("$ %s iperf3 -c %s -p %d -t %d -f m" %
                     (src_name, dst.IP(), port, iperf_duration))
        iperf_output = src.cmd("iperf3 -c %s -p %d -t %d -f m" %
                               (dst.IP(), port, iperf_duration))
        lines.append(iperf_output.strip())
        try:
            server_output, _ = server.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            server.terminate()
            server_output, _ = server.communicate(timeout=3)
        lines.append("")
        lines.append("$ %s iperf3 server output" % dst_name)
        lines.append((server_output or "").strip())
        lines.append("")

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")
    os.chmod(report_file, 0o644)
    info("*** Performance report saved to %s\n" % report_file)


def save_manual_flow_report(net, report_file):
    """Save ovs-ofctl manual-flow evidence and directed connectivity result."""
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    lines = [
        "Manual ovs-ofctl flow report",
        "Expected policy:",
        "  h1 <-> h3 reachable",
        "  h2 <-> h4 reachable",
        "  all other host pairs blocked",
        "",
        "=== Directed connectivity ===",
    ]

    pairs = [
        ("h1", "h3", True),
        ("h3", "h1", True),
        ("h2", "h4", True),
        ("h4", "h2", True),
        ("h1", "h2", False),
        ("h1", "h4", False),
        ("h2", "h3", False),
        ("h3", "h4", False),
    ]
    for src_name, dst_name, expected in pairs:
        src = net.get(src_name)
        dst = net.get(dst_name)
        loss = _directed_ping_loss(src, dst, count=3)
        ok = loss < 100.0 if expected else loss == 100.0
        lines.append(
            "%s -> %s: %.1f%% loss expected=%s result=%s" %
            (src_name, dst_name, loss, "reachable" if expected else "blocked",
             "PASS" if ok else "FAIL")
        )

    for sw in ["s1", "s2"]:
        lines.extend([
            "",
            "=== ovs-ofctl -O OpenFlow13 dump-flows %s ===" % sw,
            _run_ovs_ofctl(["dump-flows", sw]),
        ])

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")
    os.chmod(report_file, 0o644)
    info("*** Manual flow report saved to %s\n" % report_file)


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
    parser = argparse.ArgumentParser(description="Start the simple SDN topology.")
    parser.add_argument("--controller-ip", default="127.0.0.1", help="Remote controller IP.")
    parser.add_argument("--controller-port", type=int, default=6653, help="Remote controller port.")
    parser.add_argument("--no-cli", action="store_true", help="Exit after automated actions instead of opening CLI.")
    parser.add_argument("--no-manual-flows", action="store_true", help="Do not install ovs-ofctl manual flows.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip built-in connectivity checks.")
    parser.add_argument("--traffic", action="store_true", help="Generate dynamic iperf3 traffic inside Mininet.")
    parser.add_argument("--traffic-src", default="h1", help="Source host for generated traffic.")
    parser.add_argument("--traffic-dst", default="h3", help="Destination host for generated traffic.")
    parser.add_argument("--traffic-duration", type=float, default=30.0, help="Traffic generation duration in seconds.")
    parser.add_argument("--traffic-pattern", default="sine", choices=["sine", "peak_hours"],
                        help="Traffic generation pattern.")
    parser.add_argument("--traffic-base-rate", type=float, default=5.0, help="Base traffic rate in Mbps.")
    parser.add_argument("--traffic-amplitude", type=float, default=4.0, help="Traffic rate amplitude in Mbps.")
    parser.add_argument("--traffic-period", type=float, default=30.0, help="Traffic pattern period in seconds.")
    parser.add_argument("--startup-wait", type=float, default=2.0,
                        help="Seconds to wait after switches connect before tests/traffic.")
    parser.add_argument("--vlan-capture", action="store_true",
                        help="Capture VLAN-tagged trunk traffic while auto-pinging h1-h3 and h2-h4.")
    parser.add_argument("--capture-file", default=os.path.join(PROJECT_DIR, "captures", "vlan_trunk.pcapng"),
                        help="Output pcapng file for --vlan-capture.")
    parser.add_argument("--capture-summary", default=os.path.join(PROJECT_DIR, "captures", "vlan_trunk.txt"),
                        help="Text summary file for --vlan-capture.")
    parser.add_argument("--capture-ping-count", type=int, default=3,
                        help="Ping count per VLAN pair during --vlan-capture.")
    parser.add_argument("--capture-duration", type=int, default=8,
                        help="Capture duration in seconds for --vlan-capture.")
    parser.add_argument("--dynamic-demo", action="store_true",
                        help="Periodically ping h1-h3 to demonstrate hard_timeout block/recovery.")
    parser.add_argument("--dynamic-demo-duration", type=float, default=40.0,
                        help="Total duration for --dynamic-demo.")
    parser.add_argument("--dynamic-demo-interval", type=float, default=5.0,
                        help="Probe interval for --dynamic-demo.")
    parser.add_argument("--perf-test", action="store_true",
                        help="Run ping/iperf3 tests and save performance evidence.")
    parser.add_argument("--perf-duration", type=int, default=5,
                        help="iperf3 client duration for --perf-test.")
    parser.add_argument("--perf-report", default=os.path.join(PROJECT_DIR, "data", "performance_report.txt"),
                        help="Output report path for --perf-test.")
    parser.add_argument("--manual-flow-report", action="store_true",
                        help="Save directed connectivity and dump-flows evidence for manual ovs-ofctl rules.")
    parser.add_argument("--manual-report-file", default=os.path.join(PROJECT_DIR, "data", "manual_flow_report.txt"),
                        help="Output path for --manual-flow-report.")
    args = parser.parse_args()

    setLogLevel("info")

    topo = SimpleTopo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip=args.controller_ip, port=args.controller_port),
        switch=OVSSwitch,
        link=TCLink,
    )

    traffic_gen = None
    try:
        net.start()
        if not net.waitConnected(timeout=10):
            info("\n*** Warning: not all switches connected to the controller within 10s\n")
        time.sleep(args.startup_wait)

        info("\n*** Dumping switch connections\n")
        for sw in net.switches:
            info(f"  {sw.name}:\n")
            for intf in sw.intfList():
                if intf.name != "lo":
                    info(f"    {intf.name} <-> {intf.link}\n")

        if not args.no_manual_flows:
            manual_flow_rules(net)

        if not args.skip_tests:
            test_connectivity(net)

        if args.traffic:
            from traffic.traffic_generator import generate_background_traffic

            info("\n*** Starting dynamic traffic: %s -> %s for %.1fs\n" %
                 (args.traffic_src, args.traffic_dst, args.traffic_duration))
            traffic_gen = generate_background_traffic(
                net,
                args.traffic_src,
                args.traffic_dst,
                pattern=args.traffic_pattern,
                base_rate=args.traffic_base_rate,
                amplitude=args.traffic_amplitude,
                period=args.traffic_period,
            )

        if args.vlan_capture:
            capture_vlan_tags(
                net,
                args.capture_file,
                args.capture_summary,
                ping_count=args.capture_ping_count,
                capture_duration=args.capture_duration,
            )

        if args.dynamic_demo:
            run_dynamic_control_demo(
                net,
                total_duration=args.dynamic_demo_duration,
                interval=args.dynamic_demo_interval,
            )

        if args.perf_test:
            run_performance_test(
                net,
                args.perf_report,
                iperf_duration=args.perf_duration,
            )

        if args.manual_flow_report:
            save_manual_flow_report(net, args.manual_report_file)

        if args.no_cli:
            if args.traffic:
                time.sleep(args.traffic_duration)
            else:
                time.sleep(2)
        else:
            info("\n*** Starting CLI (type 'exit' or Ctrl-D to quit)\n")
            CLI(net)

        info("\n*** Dumping flow tables\n")
        for sw in net.switches:
            info(f"\n=== {sw.name} flows ===\n")
            os.system(f"ovs-ofctl -O OpenFlow13 dump-flows {sw.name}")
    finally:
        if traffic_gen:
            traffic_gen.stop()
        net.stop()


if __name__ == "__main__":
    main()
