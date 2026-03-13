#!/usr/bin/env python3
"""
gvret_201.py - Ford Fiesta MS-CAN live decoder

Connects to a GVRET-compatible device (e.g. ESP32RET) over TCP,
shows all received CAN IDs with counts and last raw bytes,
and decodes 0x201 (RPM / Speed / Gas) when present.

Usage:  python gvret_201.py [host] [port]
        python gvret_201.py                   # defaults: 10.0.0.50:23
"""

import socket
import struct
import sys
import time

# ── Configuration ────────────────────────────────────────────────────────────
HOST = "10.0.0.50"
PORT = 23

# GVRET binary frame layout (device → host):
#   0xF1  0x00  ts[4 LE]  id[4 LE]  len_bus[1]  data[DLC]  checksum[1]
MAGIC   = 0xF1
CMD_CAN = 0x00


# ── Decoder for 0x201 ────────────────────────────────────────────────────────
def decode_201(data: bytes) -> str:
    if len(data) < 8:
        return "(too short)"
    rpm       = struct.unpack_from(">H", data, 0)[0] // 4  # 0.25 RPM/bit
    speed_kmh = struct.unpack_from(">H", data, 4)[0] / 100.0 - 100.0
    # Raw gas field is (0x80 + gas_signal); subtract offset before scaling
    gas_raw   = struct.unpack_from(">H", data, 6)[0]
    gas_pct   = max(0.0, (gas_raw - 0x80) * 100.0 / 50944.0)
    return f"RPM={rpm}  Speed={speed_kmh:.1f}km/h  Gas={gas_pct:.1f}%"


# ── GVRET stream parser ───────────────────────────────────────────────────────
class GVRETParser:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes):
        self._buf.extend(chunk)
        while True:
            idx = self._buf.find(MAGIC)
            if idx == -1:
                self._buf.clear()
                break
            if idx > 0:
                del self._buf[:idx]

            if len(self._buf) < 11:
                break

            if self._buf[1] != CMD_CAN:
                del self._buf[0]
                continue

            len_bus = self._buf[10]
            dlc     = len_bus & 0x0F
            bus     = (len_bus >> 4) & 0x0F
            pkt_len = 11 + dlc + 1

            if len(self._buf) < pkt_len:
                break

            raw_id = struct.unpack_from("<I", self._buf, 6)[0]
            can_id = raw_id & 0x7FFFFFFF
            data   = bytes(self._buf[11 : 11 + dlc])
            del self._buf[:pkt_len]

            yield can_id, bus, data


# ── Display ───────────────────────────────────────────────────────────────────
def redraw(seen: dict, total: int, elapsed: float):
    """Clear screen and print live dashboard."""
    sys.stdout.write("\033[2J\033[H")   # clear screen, cursor home
    print(f"  GVRET live  —  {total} frames  ({elapsed:.0f}s)  Ctrl-C to stop\n")
    print(f"  {'ID':>6}  {'count':>7}  {'last bytes':<32}  decoded")
    print(f"  {'-'*6}  {'-'*7}  {'-'*32}  {'-'*40}")
    for can_id in sorted(seen):
        count, data = seen[can_id]
        hex_str = data.hex(" ").upper()
        extra = decode_201(data) if can_id == 0x201 else ""
        print(f"  0x{can_id:03X}  {count:>7}  {hex_str:<32}  {extra}")
    sys.stdout.flush()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Connecting to {host}:{port} …", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    sock.settimeout(0.1)   # non-blocking with short timeout for display refresh
    print("Connected. Enabling binary mode …", flush=True)
    sock.sendall(bytes([0xE7]))

    parser    = GVRETParser()
    seen      = {}   # can_id → (count, last_data)
    total     = 0
    start     = time.monotonic()
    last_draw = 0.0

    print("Receiving…", flush=True)
    try:
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    print("\nConnection closed by device.")
                    break
                for can_id, bus, data in parser.feed(chunk):
                    total += 1
                    prev_count = seen[can_id][0] if can_id in seen else 0
                    seen[can_id] = (prev_count + 1, data)
            except socket.timeout:
                pass   # just redraw

            now = time.monotonic()
            if now - last_draw >= 0.1:
                redraw(seen, total, now - start)
                last_draw = now

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    # Final summary
    redraw(seen, total, time.monotonic() - start)
    print("\nStopped.")


if __name__ == "__main__":
    main()
