#!/usr/bin/env python3
"""Background traffic generator: produces dynamic traffic patterns (sine wave, peak hours)
between specified hosts using iperf3."""

import subprocess
import time
import math
import threading
import csv
import os
from datetime import datetime


class TrafficGenerator:
    """Generates dynamic background traffic using iperf3 between hosts."""

    def __init__(self, client_host=None, server_host=None, target_host=None,
                 server_port=5201, client_duration=5,
                 base_rate=5, amplitude=4, period=30, pattern="sine",
                 log_file=None):
        """
        Args:
            client_host: source Mininet host object that runs iperf3 client
            server_host: destination Mininet host object that runs iperf3 server
            target_host: deprecated alias for server_host
            server_port: iperf3 server port
            client_duration: seconds per iperf3 client sample
            base_rate: base bandwidth in Mbps
            amplitude: amplitude of variation in Mbps
            period: period of wave in seconds
            pattern: "sine" or "peak_hours"
            log_file: CSV file path for logging
        """
        if server_host is None:
            server_host = target_host
        if client_host is None:
            raise ValueError("client_host is required")
        if server_host is None:
            raise ValueError("server_host is required")

        self.client_host = client_host
        self.server_host = server_host
        self.server_port = server_port
        self.client_duration = client_duration
        self.base_rate = base_rate
        self.amplitude = amplitude
        self.period = period
        self.pattern = pattern
        self.log_file = log_file or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "traffic_log.csv"
        )
        self._running = False
        self._stop_event = threading.Event()
        self._thread = None
        self._server_proc = None
        self._client_proc = None

    def start(self):
        """Start the iperf3 server and begin traffic generation."""
        self._running = True
        self._stop_event.clear()

        self._server_proc = self.server_host.popen(
            ["iperf3", "-s", "-p", str(self.server_port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        time.sleep(0.5)

        self._thread = threading.Thread(target=self._traffic_loop, daemon=True)
        self._thread.start()
        print(f"[TrafficGen] Started pattern={self.pattern} "
              f"base={self.base_rate}Mbps amp={self.amplitude}Mbps period={self.period}s")

    def stop(self):
        """Stop traffic generation."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._client_proc:
            try:
                self._client_proc.terminate()
            except Exception:
                pass
        if self._server_proc:
            try:
                self._server_proc.terminate()
            except Exception:
                pass
        print("[TrafficGen] Stopped")

    def _get_rate(self, t):
        """Calculate target rate at time t based on traffic pattern."""
        if self.pattern == "sine":
            rate = self.base_rate + self.amplitude * math.sin(2 * math.pi * t / self.period)
            return max(0.1, rate)

        elif self.pattern == "peak_hours":
            minute_of_day = (t % 3600) / 60.0
            if 0 <= minute_of_day < 30:
                rate = self.base_rate + self.amplitude * (minute_of_day / 30.0)
            elif 480 <= minute_of_day < 540:
                progress = (minute_of_day - 480) / 60.0
                rate = self.base_rate + self.amplitude * (1.0 - abs(2 * progress - 1))
            elif 1020 <= minute_of_day < 1080:
                progress = (minute_of_day - 1020) / 60.0
                rate = self.base_rate + self.amplitude * (1.0 - abs(2 * progress - 1))
            else:
                rate = self.base_rate
            return max(0.1, rate)

        return self.base_rate

    def _traffic_loop(self):
        """Main loop: periodically updates iperf3 client rate."""
        start_time = time.time()

        while self._running:
            try:
                t = time.time() - start_time
                rate_mbps = self._get_rate(t)

                if self._client_proc:
                    try:
                        self._client_proc.terminate()
                    except Exception:
                        pass

                cmd = [
                    "iperf3", "-c", self.server_host.IP(),
                    "-p", str(self.server_port),
                    "-b", f"{rate_mbps:.1f}M",
                    "-t", str(self.client_duration),
                    "-i", "0",
                    "-P", "1",
                ]
                self._client_proc = self.client_host.popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_entry = [
                    timestamp, self.pattern, f"{t:.1f}",
                    f"{rate_mbps:.2f}",
                    self.client_host.IP(), self.server_host.IP(), str(self.server_port),
                ]
                self._save_log(log_entry)

                self._stop_event.wait(self.client_duration)
            except Exception as e:
                print(f"[TrafficGen] Error: {e}")
                self._stop_event.wait(5)

    def _save_log(self, entry):
        """Append a log entry to CSV file."""
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        try:
            file_exists = os.path.isfile(self.log_file)
            with open(self.log_file, "a", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow([
                        "timestamp", "pattern", "elapsed_s",
                        "rate_mbps", "source_ip", "target_ip", "target_port",
                    ])
                writer.writerow(entry)
        except Exception as e:
            print(f"[TrafficGen] Log error: {e}")


def generate_background_traffic(net, src_host, dst_host, **kwargs):
    """Convenience function to start traffic generation between two hosts in a Mininet net.

    Args:
        net: Mininet net object
        src_host: source host name (runs iperf3 client)
        dst_host: destination host name (runs iperf3 server)
    """
    src = net.get(src_host)
    dst = net.get(dst_host)
    gen = TrafficGenerator(client_host=src, server_host=dst, **kwargs)
    gen.start()
    return gen


if __name__ == "__main__":
    import sys
    print("TrafficGenerator module loaded.")
    print("Usage:")
    print("  from traffic.traffic_generator import TrafficGenerator")
    print("  gen = TrafficGenerator(client_host=h1, server_host=h3, pattern='sine')")
    print("  gen.start()")
    print("  time.sleep(60)")
    print("  gen.stop()")
