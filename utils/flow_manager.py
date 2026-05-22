#!/usr/bin/env python3
"""Flow manager utility: provides functions for managing OpenFlow flow entries
via ovs-ofctl and programmatically."""

import subprocess
import json
import os


def dump_flows(switch_name):
    """Dump all flows from a switch using ovs-ofctl."""
    cmd = ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", switch_name]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


def add_flow(switch_name, flow_str):
    """Add a flow entry to a switch."""
    cmd = ["ovs-ofctl", "-O", "OpenFlow13", "add-flow", switch_name, flow_str]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def del_flows(switch_name):
    """Delete all flows from a switch."""
    cmd = ["ovs-ofctl", "-O", "OpenFlow13", "del-flows", switch_name]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def add_flow_with_timeout(switch_name, flow_str, hard_timeout=20):
    """Add a flow entry with hard timeout (auto-expires after timeout seconds)."""
    full_flow = f"hard_timeout={hard_timeout},{flow_str}"
    return add_flow(switch_name, full_flow)


def block_host_pair(switch_a, switch_b, host_a_mac, host_b_mac, duration=20):
    """Temporarily block communication between two hosts using hard_timeout."""
    rules = []
    for sw, src_port, dst_port in [
        (switch_a, None, None),
        (switch_b, None, None),
    ]:
        pass

    flow_s1 = f"priority=500,dl_src={host_a_mac},dl_dst={host_b_mac},actions=drop"
    flow_s2 = f"priority=500,dl_src={host_b_mac},dl_dst={host_a_mac},actions=drop"

    add_flow_with_timeout(switch_a, flow_s1, hard_timeout=duration)
    add_flow_with_timeout(switch_b, flow_s2, hard_timeout=duration)

    return True


def save_flow_snapshot(switch_names, output_dir="data"):
    """Save current flow tables of all switches to JSON."""
    os.makedirs(output_dir, exist_ok=True)
    snapshot = {}
    for sw_name in switch_names:
        snapshot[sw_name] = dump_flows(sw_name)
    path = os.path.join(output_dir, "flow_snapshot.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return path
