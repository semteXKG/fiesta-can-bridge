# fiesta-can-bridge

Python tools for sniffing and decoding the **Ford Fiesta MK5 (>2006) MS-CAN bus** via a GVRET-compatible interface (e.g. ESP32RET).

## Hardware

- Tap CANH/CANL from the radio QuadLock connector
- Connect to an ESP32RET or similar GVRET device
- Bus speed: **125 kbps**
- Default connection: `10.0.0.50:23` (TCP)

## Scripts

### `can-poller.py` — Live CAN dashboard
Connects to the GVRET device, shows all received CAN IDs with frame counts and last bytes, and decodes **0x201** (RPM / Speed / Gas pedal) in real time.

```
python can-poller.py [host] [port]
python can-poller.py               # defaults: 10.0.0.50:23
```

## 0x201 Decode Reference

| Signal | Bytes | Formula |
|--------|-------|---------|
| RPM | D1,D2 big-endian | `uint16 / 4` |
| Speed | D5,D6 big-endian | `uint16 / 100 - 100` km/h |
| Gas pedal | D7,D8 big-endian | `max(0, (uint16 - 128) * 100 / 50944)` % |

## Full Protocol Reference

See [`AGENT.md`](AGENT.md) for the complete MS-CAN message catalogue, GVRET binary protocol details, OBD-II notes, and observed message frequencies.

## Raspberry Pi Install

Run on the Pi (carpi) as root to install the tools system-wide:

```bash
sudo bash install.sh
```

Or deploy directly from a dev machine:

```bash
ssh semtex@10.0.0.211 'sudo bash -s' < install.sh
```

This installs the script to `/usr/local/lib/fiesta-can-bridge/`, creates a
wrapper command on `PATH`, and enables a systemd service that starts automatically at boot.

| Command | Description |
|---------|-------------|
| `can-dashboard [host] [port]` | Live CAN frame monitor |

### Service management

```bash
systemctl status can-bridge
journalctl -u can-bridge -f
```

## Requirements

- Python 3.x (stdlib only, no extra packages)
- GVRET-compatible CAN interface reachable over TCP
