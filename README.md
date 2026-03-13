# fiesta-can-bridge

Python tools for sniffing and decoding the **Ford Fiesta MK5 (>2006) MS-CAN bus** via a GVRET-compatible interface (e.g. ESP32RET).

## Hardware

- Tap CANH/CANL from the radio QuadLock connector
- Connect to an ESP32RET or similar GVRET device
- Bus speed: **125 kbps**
- Default connection: `10.0.0.50:23` (TCP)

## Scripts

### `gvret_201.py` — Live CAN dashboard
Connects to the GVRET device, shows all received CAN IDs with frame counts and last bytes, and decodes **0x201** (RPM / Speed / Gas pedal) in real time.

```
python gvret_201.py [host] [port]
python gvret_201.py               # defaults: 10.0.0.50:23
```

### `obd2_test.py` — OBD-II poll test
Sends a single OBD-II Mode 01 PID 0x0C (Engine RPM) request to `0x7DF` and waits for a response on `0x7E8`. Confirms whether the ECU is reachable via the MS-CAN gateway.

```
python obd2_test.py [host] [port]
```

## 0x201 Decode Reference

| Signal | Bytes | Formula |
|--------|-------|---------|
| RPM | D1,D2 big-endian | `uint16 / 4` |
| Speed | D5,D6 big-endian | `uint16 / 100 - 100` km/h |
| Gas pedal | D7,D8 big-endian | `max(0, (uint16 - 128) * 100 / 50944)` % |

## Full Protocol Reference

See [`AGENT.md`](AGENT.md) for the complete MS-CAN message catalogue, GVRET binary protocol details, OBD-II notes, and observed message frequencies.

## Requirements

- Python 3.x (stdlib only, no extra packages)
- GVRET-compatible CAN interface reachable over TCP
