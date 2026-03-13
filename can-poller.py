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
import queue
import selectors
import socket
import struct
import sys
import threading
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
        self._pos = 0

    def feed(self, chunk: bytes):
        self._buf.extend(chunk)
        while True:
            idx = self._buf.find(MAGIC, self._pos)
            if idx == -1:
                # Skip past everything except the last 10 bytes (potential partial frame)
                self._pos = max(0, len(self._buf) - 10)
                break
            if len(self._buf) < idx + 2:
                break
            if self._buf[idx + 1] != CMD_CAN:
                self._pos = idx + 1
                continue
            if len(self._buf) < idx + 11:
                break
            len_bus = self._buf[idx + 10]
            dlc     = len_bus & 0x0F
            pkt_len = 11 + dlc + 1
            if len(self._buf) < idx + pkt_len:
                break
            raw_id = struct.unpack_from("<I", self._buf, idx + 6)[0]
            can_id = raw_id & 0x7FFFFFFF
            data   = bytes(self._buf[idx + 11 : idx + 11 + dlc])
            self._pos = idx + pkt_len
            yield can_id, data

        # Compact once the consumed prefix exceeds 4 KB
        if self._pos > 4096:
            del self._buf[:self._pos]
            self._pos = 0


# ── Display ───────────────────────────────────────────────────────────────────
def redraw(seen: dict, total: int, elapsed: float):
    lines = [
        "\033[2J\033[H",
        f"  GVRET live  —  {total} frames  ({elapsed:.0f}s)  Ctrl-C to stop\n\n",
        f"  {'ID':>6}  {'count':>7}  {'last bytes':<32}  decoded\n",
        f"  {'-'*6}  {'-'*7}  {'-'*32}  {'-'*40}\n",
    ]
    for can_id in sorted(seen):
        count, data, decoded = seen[can_id]
        hex_str = data.hex(" ").upper()
        if can_id == 0x201:
            extra = (f"RPM={decoded['rpm']}  Speed={decoded['speed_kmh']}km/h  Gas={decoded['throttle_pct']}%"
                     if decoded else "(too short)")
        else:
            extra = ""
        lines.append(f"  0x{can_id:03X}  {count:>7}  {hex_str:<32}  {extra}\n")
    sys.stdout.write("".join(lines))
    sys.stdout.flush()


# ── Service summary (non-TTY) ─────────────────────────────────────────────────
def log_summary(seen: dict, total: int, elapsed: float):
    ids = ", ".join(f"0x{cid:03X}:{seen[cid][0]}" for cid in sorted(seen))
    decoded = seen[0x201][2] if 0x201 in seen else None
    if decoded:
        dec = f"  0x201: RPM={decoded['rpm']} Speed={decoded['speed_kmh']}km/h Gas={decoded['throttle_pct']}%"
    else:
        dec = ""
    print(f"[summary] {total} frames in {elapsed:.0f}s | {ids}{dec}", flush=True)


# ── MQTT worker ───────────────────────────────────────────────────────────────
def _mqtt_worker(mqtt_client: mqtt_lib.Client, q: queue.SimpleQueue):
    while True:
        topic, payload = q.get()
        mqtt_client.publish(topic, payload)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Connecting to MQTT {MQTT_HOST}:{MQTT_PORT} …", flush=True)
    mqtt = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2, client_id="can-poller")
    mqtt.connect_async(MQTT_HOST, MQTT_PORT)
    mqtt.loop_start()

    publish_queue: queue.SimpleQueue = queue.SimpleQueue()
    threading.Thread(target=_mqtt_worker, args=(mqtt, publish_queue), daemon=True).start()

    print(f"Connecting to GVRET {host}:{port} …", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    print("Connected. Enabling binary mode …", flush=True)
    sock.sendall(bytes([0xE7]))
    sock.setblocking(False)

    sel = selectors.DefaultSelector()
    sel.register(sock, selectors.EVENT_READ)

    parser       = GVRETParser()
    seen         = {}
    total        = 0
    start        = time.monotonic()
    last_draw    = 0.0
    is_tty       = sys.stdout.isatty()
    interval     = 0.1 if is_tty else 10.0

    try:
        while True:
            events = sel.select(timeout=interval)
            if events:
                while True:
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            print("\nConnection closed by device.", flush=True)
                            raise StopIteration
                        for can_id, data in parser.feed(chunk):
                            total += 1
                            entry   = seen.get(can_id)
                            decoded = None
                            if can_id == 0x201:
                                decoded = decode_201(data)
                                if decoded:
                                    publish_queue.put(("fiesta/can/201", json.dumps(decoded)))
                            seen[can_id] = ((entry[0] + 1 if entry else 1), data, decoded)
                    except BlockingIOError:
                        break

            now = time.monotonic()
            if now - last_draw >= interval:
                if is_tty:
                    redraw(seen, total, now - start)
                else:
                    log_summary(seen, total, now - start)
                last_draw = now

    except (KeyboardInterrupt, StopIteration):
        pass
    finally:
        sel.close()
        sock.close()
        mqtt.loop_stop()
        mqtt.disconnect()

    if is_tty:
        redraw(seen, total, time.monotonic() - start)
    print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()
