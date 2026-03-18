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


# ── CAN frame decoders ────────────────────────────────────────────────────────
def decode_201(data: bytes) -> dict | None:
    """RPM / Speed / Gas pedal (50 Hz)"""
    if len(data) < 8:
        return None
    rpm       = struct.unpack_from(">H", data, 0)[0] // 4
    speed_kmh = round(struct.unpack_from(">H", data, 4)[0] / 100.0 - 100.0, 1)
    gas_raw   = struct.unpack_from(">H", data, 6)[0]
    throttle  = round(max(0.0, (gas_raw - 0x80) * 100.0 / 50944.0), 1)
    return {"rpm": rpm, "speed_kmh": speed_kmh, "throttle_pct": throttle}


_BRAKE_360 = {0x60: "off", 0x68: "touch", 0x78: "pressed"}

def decode_360(data: bytes) -> dict | None:
    """Brake pedal 3-level (100 Hz)"""
    if len(data) < 7:
        return None
    return {"brake_pedal": _BRAKE_360.get(data[5], f"0x{data[5]:02X}")}


_BRAKE_420 = {0x00: "off", 0x10: "touch", 0x30: "pressed"}

def decode_420(data: bytes) -> dict | None:
    """Coolant temperature + Brake (10 Hz)"""
    if len(data) < 7:
        return None
    coolant_c = data[0] - 40
    brake     = _BRAKE_420.get(data[5], f"0x{data[5]:02X}")
    return {"coolant_c": coolant_c, "brake_pedal": brake}


def decode_428(data: bytes) -> dict | None:
    """Battery voltage (10 Hz)"""
    if len(data) < 2:
        return None
    return {"battery_v": round(data[1] / 10.0, 1)}


DECODERS: dict[int, tuple] = {
    0x201: (decode_201, "fiesta/can/201"),
    0x360: (decode_360, "fiesta/can/360"),
    0x420: (decode_420, "fiesta/can/420"),
    0x428: (decode_428, "fiesta/can/428"),
}


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
        extra = "  ".join(f"{k}={v}" for k, v in decoded.items()) if decoded else ""
        lines.append(f"  0x{can_id:03X}  {count:>7}  {hex_str:<32}  {extra}\n")
    sys.stdout.write("".join(lines))
    sys.stdout.flush()


# ── Service summary (non-TTY) ─────────────────────────────────────────────────
def log_summary(seen: dict, total: int, elapsed: float):
    ids = ", ".join(f"0x{cid:03X}:{seen[cid][0]}" for cid in sorted(seen))
    dec_parts = []
    for cid in sorted(seen):
        decoded = seen[cid][2]
        if decoded:
            fields = " ".join(f"{k}={v}" for k, v in decoded.items())
            dec_parts.append(f"0x{cid:03X}: {fields}")
    dec = ("  " + "  |  ".join(dec_parts)) if dec_parts else ""
    print(f"[summary] {total} frames in {elapsed:.0f}s | {ids}{dec}", flush=True)


# ── MQTT worker ───────────────────────────────────────────────────────────────
def _mqtt_worker(mqtt_client: mqtt_lib.Client, q: queue.SimpleQueue):
    while True:
        topic, payload = q.get()
        try:
            mqtt_client.publish(topic, payload)
        except Exception as exc:
            print(f"[mqtt] publish error: {exc}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Connecting to MQTT {MQTT_HOST}:{MQTT_PORT} …", flush=True)
    mqtt = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2, client_id="can-poller")
    mqtt.reconnect_delay_set(min_delay=1, max_delay=30)
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
                            decoder = DECODERS.get(can_id)
                            if decoder:
                                func, topic = decoder
                                decoded = func(data)
                                if decoded:
                                    publish_queue.put((topic, json.dumps(decoded)))
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
