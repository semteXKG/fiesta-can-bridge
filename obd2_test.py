#!/usr/bin/env python3
"""
obd2_test.py - OBD-II poll test over GVRET

Sends a single OBD-II Mode 01 PID 0x0C (Engine RPM) request to 0x7DF
and waits for a response on 0x7E8.

If you get a response: OBD-II works over this bus.
If you get nothing after the timeout: ECU isn't reachable on MS-CAN.

Usage:  python obd2_test.py [host] [port]
"""

import socket
import struct
import sys
import time

HOST = "10.0.0.50"
PORT = 23

MAGIC   = 0xF1
CMD_CAN = 0x00

OBD_REQUEST_ID  = 0x7DF
OBD_RESPONSE_ID = 0x7E8
TIMEOUT_S       = 2.0   # wait up to 2 seconds for a response


def build_gvret_frame(can_id: int, data: bytes, bus: int = 0) -> bytes:
    """Pack a CAN frame into GVRET binary send format."""
    dlc = len(data)
    # bit 31 = extended flag; 0x7DF is standard (11-bit), so no flag needed
    id_bytes = struct.pack("<I", can_id)
    bus_dlc  = bytes([bus, dlc])
    payload  = bytes([MAGIC, CMD_CAN]) + id_bytes + bus_dlc + data
    checksum = 0
    for b in payload[1:]:   # XOR from byte 1 onwards
        checksum ^= b
    return payload + bytes([checksum])


def parse_frames(buf: bytearray):
    """Yield (can_id, data) and consume processed bytes from buf in-place."""
    while True:
        idx = buf.find(MAGIC)
        if idx == -1:
            buf.clear()
            break
        if idx > 0:
            del buf[:idx]
        if len(buf) < 11:
            break
        if buf[1] != CMD_CAN:
            del buf[0]
            continue
        dlc     = buf[10] & 0x0F
        pkt_len = 11 + dlc + 1
        if len(buf) < pkt_len:
            break
        can_id = struct.unpack_from("<I", buf, 6)[0] & 0x7FFFFFFF
        data   = bytes(buf[11 : 11 + dlc])
        del buf[:pkt_len]
        yield can_id, data


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Connecting to {host}:{port} …", flush=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    print("Connected. Enabling binary mode …", flush=True)
    sock.sendall(bytes([0xE7]))
    time.sleep(0.1)   # let device switch modes

    # OBD-II request: Mode 01, PID 0x0C (Engine RPM), padded to 8 bytes
    obd_request = bytes([0x02, 0x01, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x00])
    frame = build_gvret_frame(OBD_REQUEST_ID, obd_request)
    print(f"Sending OBD-II request → 0x{OBD_REQUEST_ID:03X}  data: {obd_request.hex(' ').upper()}")
    sock.sendall(frame)

    print(f"Waiting up to {TIMEOUT_S}s for response on 0x{OBD_RESPONSE_ID:03X} …\n")

    buf      = bytearray()
    deadline = time.monotonic() + TIMEOUT_S
    sock.settimeout(0.1)

    try:
        while time.monotonic() < deadline:
            try:
                buf.extend(sock.recv(4096))
            except socket.timeout:
                pass

            for can_id, data in parse_frames(buf):
                print(f"  RX  0x{can_id:03X}  [{data.hex(' ').upper()}]", end="")

                if can_id == OBD_RESPONSE_ID and len(data) >= 4 and data[1] == 0x41 and data[2] == 0x0C:
                    rpm = ((data[3] << 8) | data[4]) / 4.0
                    print(f"  ← OBD-II RPM = {rpm:.0f}")
                    return   # success
                else:
                    print()  # other frame, just log it

    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    print(f"\nNo OBD-II response received — ECU may not be reachable on this bus.")


if __name__ == "__main__":
    main()
