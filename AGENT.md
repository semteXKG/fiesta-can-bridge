# Ford Fiesta MK5 MS-CAN — Agent Knowledge File

## Environment

| Item | Value |
|------|-------|
| GVRET device | 10.0.0.50:23 (TCP) |
| Bus | MS-CAN (infotainment), 125 kbps |
| Python | `C:\Users\Klaus\AppData\Local\Programs\Python\Python313\python.exe` |
| Sniffer script | `C:\Users\Klaus\gvret_201.py` |
| OBD-II test script | `C:\Users\Klaus\obd2_test.py` |

---

## GVRET Protocol

### Activate binary mode
Send `0xE7` immediately after TCP connect.

### Incoming frame (device → host)
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

### Outgoing frame (host → device, send CAN frame)
```
Byte 0    : 0xF1
Byte 1    : 0x00  (PROTO_BUILD_CAN_FRAME)
Bytes 2-5 : CAN ID, uint32 little-endian; set bit 31 for extended
Byte 6    : bus index
Byte 7    : DLC
Bytes 8+  : data bytes
Last byte : checksum (XOR of bytes 1..end-1)
```

---

## MS-CAN Message Catalogue (Ford Fiesta MK5 >2006)

### 0x080 — Clock (RTC)
| Byte | Content |
|------|---------|
| 1 | Year (two digits, + 2000) |
| 2 | Month |
| 3 | Day |
| 4 | Hours |
| 5 | Minutes |
| 6 | Seconds |

### 0x1E9 — Radio station name
Bytes 1–8: ASCII text

### 0x201 — RPM / Speed / Gas pedal (50 Hz)
| Bytes | Signal | Formula |
|-------|--------|---------|
| D1,D2 | RPM | `uint16_BE / 4` |
| D5,D6 | Speed | `uint16_BE / 100 - 100` km/h (offset -100 km/h; 0x2710 = 0 km/h stationary) |
| D7,D8 | Gas pedal | `max(0, (uint16_BE - 0x80) * 100 / 50944)` % |

> **Notes:**
> - RPM encoding: 0.25 RPM/bit
> - Speed encoding: 0.01 km/h/bit with a fixed offset of 10000 (100 km/h). Stationary = 0x2710 → 0.0 km/h after offset.
> - Gas encoding: raw field = 0x80 + signal; subtract before scaling.

### 0x265 — Turn arrows (bitmask byte 1)
| Bit | Meaning |
|-----|---------|
| 0x20 | Left indicator ON |
| 0x40 | Right indicator ON |

### 0x285 — Key position (byte 1)
`key_position = (byte1 & 0x30) >> 4`  →  1, 2, or 3

### 0x286 — Lights / handbrake (bitmask byte 1, base 0x10)
| Bit | Meaning |
|-----|---------|
| 0x10 | Handbrake |
| 0x80 | Parking lights / low beams |
| 0x40 | High beams |

### 0x2D5 — Steering column buttons (byte 2 bitmask)
| Bit | Meaning |
|-----|---------|
| 0x10 | Mode button |
| 0x40 | Seek up |
| 0x80 | Seek down |

### 0x2D8 — Radio volume
`volume = byte2 / 8`

### 0x2DA — CD status
| Byte | Signal |
|------|--------|
| 2 | cd_mode: 0x2A=no CD, 0x4A=playing, 0x6A=inserted/no play |
| 4 | cd_drive: 0x23=empty, 0x21=loading, 0x22=inserted, 0x26=playing |

### 0x2DB — CD track info
- Not in CD mode: `FF FF FF FF 00 00 00 00`
- In CD mode: bytes 3–4 = track_time (`track_seconds = track_time - 64`), byte 6 = track_id

### 0x360 — Brake (secondary)
Byte 6: `0x60`=not pressed, `0x68`=foot on pedal, `0x78`=pressed

### 0x420 — Coolant temperature / Brake
| Byte | Signal | Formula |
|------|--------|---------|
| 1 | Coolant | `byte1 - 40` °C |
| 6 | Brake | `0x00`=not pressed, `0x10`=foot on pedal, `0x30`=pressed |

### 0x428 — Battery voltage
`battery_v = byte2 / 10` V

### 0x433 — Doors / Lock / Reverse gear
| Byte | Signal |
|------|--------|
| 1 | door_status bitmask: 0x80=front-left open, 0x40=front-right open, 0x08=trunk open |
| 4 | reverse_gear: 0x02=reverse, 0x00=not |
| 6 | lock: 0x10=locked, 0x20=unlocked |

### 0x460 — Airbag warning light
Byte 5: `0xC0`=ON, `0x00`=OFF

### 0x4C0 — Text to LCD (ISO-TP)
- Short (AUX mode): `07 34 <6 ASCII bytes>`
- Extended header: `10 <len+2> 34 <5 ASCII bytes>` followed by `0x21 <7 ASCII bytes>`
- Radio OFF: `02 34 00 00 00 00 00 00`

### 0x4C8 — ISO-TP flow control ACK
`30 00 00 00 00 00 00 00`

### 0x4F3 — Vehicle ID (lower VIN / serial)
Bytes 1–8: vehicle ID

---

## Observed IDs on this vehicle (not yet decoded)

| ID | Observed bytes (stationary) | Rate | Likely source | Notes |
|----|---------------------------|------|---------------|-------|
| 0x040 | `07 D9 93 F4 A3 00 00 00` | — | BCM | Static status/config from Body Control Module |
| 0x046 | `08 DD 69 AD 92 00 00 00` | — | BCM | Static status/config, similar pattern to 0x040 |
| 0x090 | varies | ~75 Hz | Unknown | High-rate dynamic signal; could be seatbelt/environment sensor |
| 0x200 | `03 8F 02 89 02 89 00` | ~100 Hz | IPC gateway | Adjacent to 0x201, high-rate — likely additional powertrain data (throttle position or torque?) |
| 0x210 | `FF FE 3C A4 40 00 xx` | ~75 Hz | EATC or IPC | Last byte increments (counter/sequence); on Mondeo MS-CAN this ID is EATC-sourced |
| 0x230 | `00 01 66 00 64 xx xx 80` | ~100 Hz | IPC gateway | Bytes 5-6 vary; HS-CAN 0x230 on other Fords carries gear + trans fluid temp |
| 0x430 | `3D 00 Cxx 00 00 00 20` | ~50 Hz | IPC/BCM | Adjacent to 0x420/0x428 engine cluster; likely another engine diagnostic |
| 0x4B0 | `27 10 27 10 27 10 27 10` | ~75 Hz | ABS/ESP | **Probable 4× wheel speeds** — 4 uint16_BE pairs, all 0x2710 when stationary (same encoding as 0x201 speed: val/100-100 = 0 km/h). Needs driving data to confirm byte order (FL/FR/RL/RR) |
| 0x620 | `00 24 12 30 00 00 00 04` | ~10 Hz | Network mgmt | Low-rate, static-ish; possibly network management or diagnostic broadcast |
| 0x630 | `88 01 7F 00 00 64 51 51` | ~1 Hz | EATC/HVAC | Very low rate; on other Fords 0x620/0x630 range carries HVAC/climate data |

---

## OBD-II over MS-CAN

**Works via gateway bridge (MS-CAN ↔ HS-CAN).**

- Request: send to `0x7DF`, DLC 8, `02 01 <PID> 00 00 00 00 00`
- Response: comes on `0x7E8`, `04 41 <PID> <data...>`
- Timeout: ~1–2 seconds observed in practice

### Example: PID 0x0C (Engine RPM)
```
TX  0x7DF  02 01 0C 00 00 00 00 00
RX  0x7E8  04 41 0C HH LL 00 00 00
rpm = ((HH << 8) | LL) / 4
```

---

## Message Frequencies (observed)

| Rate | IDs |
|------|-----|
| ~100 Hz | 0x200, 0x230, 0x360 |
| ~75 Hz | 0x080, 0x090, 0x210, 0x4B0 |
| ~50 Hz | 0x201, 0x430 |
| ~10 Hz | 0x420, 0x428, 0x620 |
| ~1 Hz | 0x630 |
