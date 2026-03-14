# Copilot Instructions — fiesta-can-bridge

## Project overview

Python tools for sniffing and decoding the **Ford Fiesta MK5 (>2006) MS-CAN bus** (125 kbps) via a GVRET-compatible interface (e.g. WiCAN / ESP32RET) over TCP. Decoded data is published to an MQTT broker. The target deployment is a Raspberry Pi ("carpi") running as a systemd service.

## Architecture

Two Python scripts form a launcher → worker chain:

1. **`can-bridge-starter.py`** — Discovery/launcher. Reads the dnsmasq lease file to find the WiCAN device by hostname or port scan, then `os.execv`s into `can-poller.py` with the discovered IP.
2. **`can-poller.py`** — Main worker. Connects to the GVRET device, parses the binary stream, decodes CAN frames (currently 0x201 for RPM/Speed/Gas), and publishes JSON to MQTT topic `fiesta/can/201`. Has two display modes: interactive TTY dashboard vs. non-TTY periodic log summary.

The `install.sh` script deploys both into `/usr/local/lib/fiesta-can-bridge/` with a Python venv, creates a `can-dashboard` wrapper on PATH, and enables the `can-bridge` systemd service.

## Key protocols

- **GVRET binary protocol**: Magic `0xF1`, command `0x00` for CAN frames. Send `0xE7` on connect to enable binary mode. Full spec in `AGENT.md`.
- **MS-CAN message catalogue**: Complete decode tables for ~20 CAN IDs in `AGENT.md`. When adding new decoders, follow the existing `decode_201()` pattern (struct.unpack big-endian, return a dict).
- **MQTT**: Publishes to `broker:1883`, topic pattern `fiesta/can/<id>`. Uses paho-mqtt with async connect and a dedicated publisher thread with a `queue.SimpleQueue`.

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
