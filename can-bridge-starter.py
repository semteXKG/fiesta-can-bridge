#!/usr/bin/env python3
"""
can-bridge-starter.py — discovers the WiCAN device and launches can-poller.py.

Discovery tries two methods on each attempt, then waits 30 s and retries:
  1. Parse dnsmasq lease file for a WiCAN hostname → verify port open
  2. Try PORT on every leased IP → first responder wins
"""

import os
import socket
import sys
import time
import pathlib

PORT = 23
LEASE_FILE = "/var/lib/misc/dnsmasq.leases"
CONNECT_TIMEOUT = 2   # seconds per probe
RETRY_INTERVAL  = 30  # seconds between discovery rounds


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def read_leases(path: str) -> list[tuple[str, str]]:
    """Return list of (ip, hostname) from a dnsmasq lease file."""
    leases = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.split()
                # format: <expiry> <mac> <ip> <hostname> <client-id>
                if len(parts) >= 4:
                    leases.append((parts[2], parts[3]))
    except FileNotFoundError:
        pass
    return leases


def discover(port: int) -> str:
    """Block until a WiCAN device is found; return its IP."""
    while True:
        leases = read_leases(LEASE_FILE)

        # Step 1: hostname match
        for ip, hostname in leases:
            if hostname.lower().startswith("wican"):
                print(f"[discovery] WiCAN hostname '{hostname}' → {ip}, checking port {port}…")
                if port_open(ip, port):
                    print(f"[discovery] Found via hostname: {ip}")
                    return ip

        # Step 2: port scan all leased IPs
        ips = [ip for ip, _ in leases]
        if ips:
            print(f"[discovery] No WiCAN hostname found, scanning {len(ips)} leased IP(s) for port {port}…")
            for ip in ips:
                if port_open(ip, port):
                    print(f"[discovery] Found via port scan: {ip}")
                    return ip

        if not leases:
            print(f"[discovery] Lease file empty or missing, retrying in {RETRY_INTERVAL}s…")
        else:
            print(f"[discovery] No device found on {len(ips)} leased IP(s), retrying in {RETRY_INTERVAL}s…")

        time.sleep(RETRY_INTERVAL)


host = discover(PORT)
script = pathlib.Path(__file__).parent / "can-poller.py"
# Use the same interpreter that's running this script (venv python)
os.execv(sys.executable, [sys.executable, str(script), host, str(PORT)])
