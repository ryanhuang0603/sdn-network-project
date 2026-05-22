#!/usr/bin/env python3
"""Test runner: starts Ryu controller + Mininet topology, verifies connectivity."""

import subprocess
import time
import os
import signal
import sys


def run_test():
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    ryu = subprocess.Popen(
        ["ryu-manager", "--ofp-tcp-listen-port", "6653",
         os.path.join(project_dir, "controller", "vlan_controller.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    time.sleep(3)

    if ryu.poll() is not None:
        print("[ERROR] Ryu controller failed to start")
        out, err = ryu.communicate()
        print(err.decode())
        return 1

    print("[OK] Ryu controller started (PID: {})".format(ryu.pid))

    try:
        mn = subprocess.Popen(
            ["sudo", "-E", "python3", os.path.join(project_dir, "topology", "simple_topo.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        time.sleep(15)

        for line in iter(mn.stdout.readline, b""):
            print(line.decode().rstrip())

        mn.wait()
    finally:
        ryu.terminate()
        ryu.wait()
        print("[INFO] Controller stopped")

    return mn.returncode


if __name__ == "__main__":
    sys.exit(run_test())
