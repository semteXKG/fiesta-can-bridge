# Copilot Instructions — fiesta-can-bridge

## Project overview

Python tools for sniffing and decoding the **Ford Fiesta MK5 (>2006) MS-CAN bus** (125 kbps) via a GVRET-compatible interface (e.g. WiCAN / ESP32RET) over TCP. Decoded data is published to an MQTT broker. The target deployment is a Raspberry Pi ("carpi") running as a systemd service.

## Architecture

Two Python scripts form a launcher → worker chain:

1. **`can-bridge-starter.py`** — Discovery/launcher. Reads the dnsmasq lease file to find the WiCAN device by hostname or port scan, then `os.execv`s into `can-poller.py` with the discovered IP.
2. **`can-poller.py`** — Main worker. Connects to the GVRET device, parses the binary stream, decodes CAN frames (currently 0x201 for RPM/Speed/Gas), and publishes JSON to MQTT topic `fiesta/can/201`. Has two display modes: interactive TTY dashboard vs. non-TTY periodic log summary.

The `install.sh` script deploys both into `/usr/local/lib/fiesta-can-bridge/` with a Python venv, creates a `can-dashboard` wrapper on PATH, and enables the `can-bridge` systemd service.

## Key protocols

- **GVRET binary protocol**: Magic `0xF1`, command `0x00` for CAN frames. Send `0xE7` on connect to enable binary mode.
- **MQTT**: Publishes to `broker:1883`, topic pattern `fiesta/can/<id>`. Uses paho-mqtt with async connect and a dedicated publisher thread with a `queue.SimpleQueue`.

### GVRET incoming frame layout (device → host)

```
Byte 0    : 0xF1  (magic)
Byte 1    : 0x00  (command = CAN frame)
Bytes 2-5 : timestamp, uint32 little-endian, microseconds
Bytes 6-9 : CAN ID, uint32 little-endian; bit 31 set = extended frame
Byte 10   : len_bus — low 4 bits = DLC, high 4 bits = bus index
Bytes 11+ : data bytes (DLC bytes)
Last byte : checksum (XOR of bytes 1..end-1; currently always 0x00)
Total packet size = 12 + DLC
```

### MS-CAN message catalogue

`AGENT.md` contains the complete decode tables for ~20 CAN IDs (0x080 clock, 0x201 RPM/speed/gas, 0x420 coolant/brake, 0x428 battery, 0x433 doors/lock, etc.) plus observed-but-undecoded IDs and message frequencies. **Always consult `AGENT.md` before implementing new decoders.**

## Install & deploy

```bash
# On the Pi (or via SSH):
sudo bash install.sh

# Service management:
systemctl status can-bridge
journalctl -u can-bridge -f
```

## Dependencies

Python 3.x with a single external package: `paho-mqtt>=2.0` (installed via venv in `install.sh`). All CAN/network handling uses stdlib (`socket`, `struct`, `selectors`).

## Conventions

- No frameworks or abstraction layers — direct socket + struct for GVRET parsing, raw `selectors` for I/O multiplexing.
- CAN decode functions follow the pattern: `decode_<hex_id>(data: bytes) -> dict | None`. Return `None` if the frame is too short.
- Big-endian (`>H`) for CAN signal fields, little-endian (`<I`) for GVRET protocol fields (CAN ID, timestamp).
- MQTT payloads are JSON dicts keyed by signal name (e.g. `{"rpm": 850, "speed_kmh": 0.0, "throttle_pct": 0.0}`).
- The `AGENT.md` file is the authoritative reference for GVRET protocol details and the MS-CAN message catalogue — consult it before implementing new decoders.
