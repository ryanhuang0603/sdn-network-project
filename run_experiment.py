#!/usr/bin/env python3
"""Main integration script: starts Ryu controller, Mininet topology,
generates traffic, runs monitoring and tests."""

import subprocess
import time
import os
import sys
import signal
import threading


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


class ExperimentRunner:
    def __init__(self):
        self.ryu_proc = None
        self.mn_proc = None
        self.controller_apps = []

    def start_controller(self, apps=None, extra_env=None):
        if apps is None:
            apps = ["vlan_controller.py"]

        cmd = ["ryu-manager", "--ofp-tcp-listen-port", "6653", "--verbose"]
        for app in apps:
            app_path = os.path.join(PROJECT_DIR, "controller", app)
            cmd.append(app_path)

        print(f"[Runner] Starting controller: {' '.join(cmd)}")
        self.ryu_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, **(extra_env or {})},
        )

        def read_output():
            for line in self.ryu_proc.stdout:
                print(f"[Ryu] {line.rstrip()}")

        t = threading.Thread(target=read_output, daemon=True)
        t.start()

        time.sleep(5)
        if self.ryu_proc.poll() is not None:
            print("[Runner] ERROR: Ryu controller failed to start")
            return False
        print("[Runner] Controller started (PID: {})".format(self.ryu_proc.pid))
        return True

    def start_topology(self, topo_script="simple_topo.py", topo_args=None):
        topo_path = os.path.join(PROJECT_DIR, "topology", topo_script)
        cmd = ["sudo", "-E", "python3", topo_path]
        if topo_args:
            cmd.extend(topo_args)

        print(f"[Runner] Starting topology: {topo_script}")
        print(f"[Runner] Command: {' '.join(cmd)}")

        self.mn_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        time.sleep(10)

        if self.mn_proc.poll() is not None:
            print("[Runner] ERROR: Mininet failed to start")
            out = self.mn_proc.stdout.read()
            print(out)
            return False

        print("[Runner] Topology started")

        def read_mn_output():
            for line in self.mn_proc.stdout:
                print(f"[Mininet] {line.rstrip()}")

        t = threading.Thread(target=read_mn_output, daemon=True)
        t.start()
        return True

    def run_pingall(self):
        if self.mn_proc and self.mn_proc.poll() is None:
            self.mn_proc.stdin.write("pingall\n")
            self.mn_proc.stdin.flush()
            time.sleep(5)

    def cleanup(self):
        print("[Runner] Cleaning up...")
        if self.mn_proc and self.mn_proc.poll() is None:
            self.mn_proc.terminate()
            self.mn_proc.wait(timeout=5)
        if self.ryu_proc and self.ryu_proc.poll() is None:
            self.ryu_proc.terminate()
            self.ryu_proc.wait(timeout=5)
        print("[Runner] Cleanup complete")


def run_basic_experiment():
    """Run basic experiment: VLAN controller + simple topology + connectivity test."""
    runner = ExperimentRunner()

    try:
        if not runner.start_controller(["vlan_controller.py"]):
            return 1

        if not runner.start_topology("simple_topo.py", topo_args=["--no-manual-flows"]):
            return 1

        print("\n" + "=" * 60)
        print("VLAN topology started.")
        print("The topology script already ran directed VLAN connectivity checks.")
        print("Do not use plain pingall as the VLAN success criterion: cross-VLAN pairs should fail.")
        print("=" * 60)

        print("\n" + "=" * 60)
        print("Experiment running. Press Ctrl+C to stop.")
        print("=" * 60)

        while runner.mn_proc and runner.mn_proc.poll() is None:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Runner] Interrupted by user")
    finally:
        runner.cleanup()

    return 0


def run_monitoring_experiment(duration=30, src_host="h1", dst_host="h3",
                              pattern="sine", base_rate=5.0, amplitude=4.0):
    """Run monitoring experiment: monitor controller + simple topology + traffic generation."""
    runner = ExperimentRunner()

    try:
        if not runner.start_controller(["monitor_controller.py"]):
            return 1

        topo_args = [
            "--no-cli",
            "--traffic",
            "--traffic-src", src_host,
            "--traffic-dst", dst_host,
            "--traffic-duration", str(duration),
            "--traffic-pattern", pattern,
            "--traffic-base-rate", str(base_rate),
            "--traffic-amplitude", str(amplitude),
        ]
        if not runner.start_topology("simple_topo.py", topo_args=topo_args):
            return 1

        print("\n" + "=" * 60)
        print("Monitoring experiment running.")
        print("Monitor log: data/port_stats_log.csv")
        print("Traffic log: data/traffic_log.csv")
        print("=" * 60)

        while runner.mn_proc and runner.mn_proc.poll() is None:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Runner] Interrupted by user")
    finally:
        runner.cleanup()

    return 0


def run_full_experiment():
    """Run full experiment: VLAN + monitor + traffic generation."""
    runner = ExperimentRunner()

    try:
        if not runner.start_controller(["vlan_controller.py", "monitor_controller.py", "load_balancer.py"]):
            return 1

        if not runner.start_topology("simple_topo.py"):
            return 1

        print("\n" + "=" * 60)
        print("Full experiment running with all controllers:")
        print("  - VLAN Controller (h1-h3 VLAN10, h2-h4 VLAN20)")
        print("  - Monitor Controller (port stats polling)")
        print("  - Load Balancer (congestion detection)")
        print("=" * 60)

        while runner.mn_proc and runner.mn_proc.poll() is None:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Runner] Interrupted by user")
    finally:
        runner.cleanup()

    return 0


def run_dynamic_experiment(block_delay=8, block_duration=20, total_duration=40,
                           interval=5):
    """Run dynamic hard_timeout demo: h1-h3 reachable, blocked, then restored."""
    runner = ExperimentRunner()

    try:
        controller_env = {
            "DYNAMIC_DEMO": "1",
            "DYNAMIC_DEMO_DELAY": str(block_delay),
            "DYNAMIC_DEMO_DURATION": str(block_duration),
        }
        if not runner.start_controller(
            ["vlan_controller.py", "dynamic_control.py"],
            extra_env=controller_env,
        ):
            return 1

        topo_args = [
            "--no-manual-flows",
            "--no-cli",
            "--skip-tests",
            "--dynamic-demo",
            "--dynamic-demo-duration", str(total_duration),
            "--dynamic-demo-interval", str(interval),
        ]
        if not runner.start_topology("simple_topo.py", topo_args=topo_args):
            return 1

        print("\n" + "=" * 60)
        print("Dynamic hard_timeout demo running.")
        print("Expected: h1->h3 reachable, then blocked, then restored.")
        print("=" * 60)

        while runner.mn_proc and runner.mn_proc.poll() is None:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Runner] Interrupted by user")
    finally:
        runner.cleanup()

    return runner.mn_proc.returncode if runner.mn_proc else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SDN Experiment Runner")
    parser.add_argument("mode", nargs="?", default="basic",
                        choices=["basic", "monitor", "dynamic", "full"],
                        help="Experiment mode: basic, monitor, dynamic, or full")
    parser.add_argument("--controller", default=None,
                        help="Extra controller app(s) comma-separated")
    parser.add_argument("--duration", type=float, default=30.0,
                        help="Monitoring traffic duration in seconds")
    parser.add_argument("--traffic-src", default="h1",
                        help="Monitoring traffic source host")
    parser.add_argument("--traffic-dst", default="h3",
                        help="Monitoring traffic destination host")
    parser.add_argument("--traffic-pattern", default="sine", choices=["sine", "peak_hours"],
                        help="Monitoring traffic pattern")
    parser.add_argument("--traffic-base-rate", type=float, default=5.0,
                        help="Monitoring traffic base rate in Mbps")
    parser.add_argument("--traffic-amplitude", type=float, default=4.0,
                        help="Monitoring traffic amplitude in Mbps")
    parser.add_argument("--block-delay", type=float, default=8.0,
                        help="Dynamic demo delay before installing block flow")
    parser.add_argument("--block-duration", type=int, default=20,
                        help="Dynamic demo hard_timeout duration")
    parser.add_argument("--dynamic-interval", type=float, default=5.0,
                        help="Dynamic demo probe interval")
    args = parser.parse_args()

    modes = {
        "basic": run_basic_experiment,
        "full": run_full_experiment,
    }

    if args.mode == "monitor":
        sys.exit(run_monitoring_experiment(
            duration=args.duration,
            src_host=args.traffic_src,
            dst_host=args.traffic_dst,
            pattern=args.traffic_pattern,
            base_rate=args.traffic_base_rate,
            amplitude=args.traffic_amplitude,
        ))

    if args.mode == "dynamic":
        total_duration = max(args.duration, args.block_delay + args.block_duration + 10)
        sys.exit(run_dynamic_experiment(
            block_delay=args.block_delay,
            block_duration=args.block_duration,
            total_duration=total_duration,
            interval=args.dynamic_interval,
        ))

    sys.exit(modes[args.mode]())
