#!/usr/bin/env python3
"""Unit tests for Mininet traffic generator command construction."""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from traffic.traffic_generator import TrafficGenerator  # noqa: E402


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


class FakeHost:
    def __init__(self, ip_addr):
        self.ip_addr = ip_addr
        self.commands = []
        self.processes = []

    def IP(self):
        return self.ip_addr

    def popen(self, cmd, stdout=None, stderr=None):
        proc = FakeProcess()
        self.commands.append(cmd)
        self.processes.append(proc)
        return proc


class TrafficGeneratorTest(unittest.TestCase):
    def test_constructor_requires_client_and_server_hosts(self):
        server = FakeHost("10.0.0.2")

        with self.assertRaises(ValueError):
            TrafficGenerator(server_host=server)

        with self.assertRaises(ValueError):
            TrafficGenerator(client_host=FakeHost("10.0.0.1"))

    def test_deprecated_target_host_alias_still_works(self):
        client = FakeHost("10.0.0.1")
        server = FakeHost("10.0.0.2")

        gen = TrafficGenerator(client_host=client, target_host=server)

        self.assertIs(gen.server_host, server)

    def test_server_runs_on_server_host_without_single_shot_flag(self):
        client = FakeHost("10.0.0.1")
        server = FakeHost("10.0.0.2")

        gen = TrafficGenerator(client_host=client, server_host=server, server_port=5301)
        gen.start()
        gen._running = False
        gen.stop()

        self.assertEqual(server.commands[0], ["iperf3", "-s", "-p", "5301"])

    def test_one_client_sample_runs_on_client_host_and_logs_source_target(self):
        client = FakeHost("10.0.0.1")
        server = FakeHost("10.0.0.2")

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "traffic.csv")
            gen = TrafficGenerator(
                client_host=client,
                server_host=server,
                server_port=5301,
                client_duration=7,
                base_rate=3,
                amplitude=0,
                log_file=log_path,
            )
            gen._running = True
            with patch.object(gen._stop_event, "wait",
                              side_effect=lambda _seconds: setattr(gen, "_running", False)):
                gen._traffic_loop()

            self.assertEqual(
                client.commands[0],
                [
                    "iperf3", "-c", "10.0.0.2",
                    "-p", "5301",
                    "-b", "3.0M",
                    "-t", "7",
                    "-i", "0",
                    "-P", "1",
                ],
            )

            with open(log_path, "r", encoding="utf-8") as f:
                log_text = f.read()
            self.assertIn("source_ip,target_ip,target_port", log_text)
            self.assertIn("10.0.0.1,10.0.0.2,5301", log_text)


if __name__ == "__main__":
    unittest.main()
