#!/usr/bin/env python3
"""
can-poller.py - Ford Fiesta MS-CAN live decoder + MQTT publisher

Connects to a GVRET-compatible device (e.g. WiCAN) over TCP,
shows all received CAN IDs with counts and last raw bytes,
decodes 0x201 (RPM / Speed / Gas) and publishes to MQTT.

Usage:  python can-poller.py [host] [port]
        python can-poller.py                   # defaults: 10.0.0.50:23
"""

import json
import socket
import struct
import sys
import time

import paho.mqtt.client as mqtt_lib

# ── Configuration ────────────────────────────────────────────────────────────
HOST      = "10.0.0.50"
PORT      = 23
MQTT_HOST = "broker"
MQTT_PORT = 1883

# GVRET binary frame layout (device → host):
#   0xF1  0x00  ts[4 LE]  id[4 LE]  len_bus[1]  data[DLC]  checksum[1]
MAGIC   = 0xF1
CMD_CAN = 0x00


# ── Decoder for 0x201 ────────────────────────────────────────────────────────
def decode_201(data: bytes) -> dict | None:
    if len(data) < 8:
        return None
    rpm       = struct.unpack_from(">H", data, 0)[0] // 4
    speed_kmh = round(struct.unpack_from(">H", data, 4)[0] / 100.0 - 100.0, 1)
    gas_raw   = struct.unpack_from(">H", data, 6)[0]
    throttle  = round(max(0.0, (gas_raw - 0x80) * 100.0 / 50944.0), 1)
    return {"rpm": rpm, "speed_kmh": speed_kmh, "throttle_pct": throttle}


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
            pkt_len = 11 + dlc + 1

            if len(self._buf) < pkt_len:
                break

            raw_id = struct.unpack_from("<I", self._buf, 6)[0]
            can_id = raw_id & 0x7FFFFFFF
            data   = bytes(self._buf[11 : 11 + dlc])
            del self._buf[:pkt_len]

            yield can_id, data


# ── Display ───────────────────────────────────────────────────────────────────
def redraw(seen: dict, total: int, elapsed: float):
    sys.stdout.write("\033[2J\033[H")
    print(f"  GVRET live  —  {total} frames  ({elapsed:.0f}s)  Ctrl-C to stop\n")
    print(f"  {'ID':>6}  {'count':>7}  {'last bytes':<32}  decoded")
    print(f"  {'-'*6}  {'-'*7}  {'-'*32}  {'-'*40}")
    for can_id in sorted(seen):
        count, data = seen[can_id]
        hex_str = data.hex(" ").upper()
        if can_id == 0x201:
            d = decode_201(data)
            extra = f"RPM={d['rpm']}  Speed={d['speed_kmh']}km/h  Gas={d['throttle_pct']}%" if d else "(too short)"
        else:
            extra = ""
        print(f"  0x{can_id:03X}  {count:>7}  {hex_str:<32}  {extra}")
    sys.stdout.flush()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Connecting to MQTT {MQTT_HOST}:{MQTT_PORT} …", flush=True)
    mqtt = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2, client_id="can-poller")
    mqtt.connect_async(MQTT_HOST, MQTT_PORT)
    mqtt.loop_start()

    print(f"Connecting to GVRET {host}:{port} …", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    sock.settimeout(0.1)
    print("Connected. Enabling binary mode …", flush=True)
    sock.sendall(bytes([0xE7]))

    parser    = GVRETParser()
    seen      = {}
    total     = 0
    start     = time.monotonic()
    last_draw = 0.0

    try:
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    print("\nConnection closed by device.")
                    break
                for can_id, data in parser.feed(chunk):
                    total += 1
                    prev_count = seen[can_id][0] if can_id in seen else 0
                    seen[can_id] = (prev_count + 1, data)
                    if can_id == 0x201:
                        d = decode_201(data)
                        if d:
                            mqtt.publish("fiesta/can/201", json.dumps(d))
            except socket.timeout:
                pass

            now = time.monotonic()
            if now - last_draw >= 0.1:
                redraw(seen, total, now - start)
                last_draw = now

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        mqtt.loop_stop()
        mqtt.disconnect()

    redraw(seen, total, time.monotonic() - start)
    print("\nStopped.")


if __name__ == "__main__":
    main()
