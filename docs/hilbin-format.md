# `.hilbin` File Format

Binary format for saving and replaying HIL Monitor run data (telemetry + PWM events).

Version: 1

---

## Overview

A `.hilbin` file contains one complete capture session: all telemetry samples and PWM transition events recorded between a `Run` and `Stop`. The format is designed for:

- Reloading into HIL Monitor (browser, TypeScript/DataView)
- Direct analysis in Python via `numpy.frombuffer` (no custom parser needed)
- Long-term archival (compact, self-describing via JSON header)

All multi-byte integers and floats are **little-endian**.

---

## Layout

```
┌────────────────────────────────────────────────────────────────┐
│ HEADER BLOCK                                                    │
│   Offset 0    8 bytes   magic = "HILDATA\x01"                  │
│   Offset 8    4 bytes   uint32  json_size                      │
│   Offset 12   N bytes   UTF-8 JSON metadata                    │
│   Offset 12+N P bytes   zero-padding (align to 8-byte boundary)│
├────────────────────────────────────────────────────────────────┤
│ TELEMETRY SECTION                                              │
│   4 bytes   uint32  telem_count                                │
│   telem_count × 28 bytes   telemetry records                   │
├────────────────────────────────────────────────────────────────┤
│ PWM SECTION                                                    │
│   4 bytes   uint32  pwm_count                                  │
│   pwm_count × 8 bytes    PWM records                           │
└────────────────────────────────────────────────────────────────┘
```

---

## Header block

### Magic (8 bytes)

```
48 49 4C 44 41 54 41 01   →  "HILDATA\x01"
```

The last byte is the format version (currently `0x01`). Readers should reject files where bytes 0–6 differ from `HILDATA` or byte 7 > supported version.

### JSON metadata (variable)

UTF-8 encoded JSON object immediately following the 4-byte `json_size` field.

Required fields:

| Field | Type | Description |
|-------|------|-------------|
| `version` | number | Format version (1) |
| `date` | string | ISO-8601 UTC timestamp of capture start |
| `name` | string | Scenario / run name |
| `sample_count` | number | Number of telemetry records |
| `pwm_count` | number | Number of PWM records |

Optional fields (preserved for analysis):

| Field | Type | Description |
|-------|------|-------------|
| `npp` | number | Motor pole pairs |
| `motor` | object | `{rs, rr, ls, lr, lm, j}` at capture time |
| `freq_hz` | number | Commanded frequency |
| `vdc_v` | number | DC link voltage |
| `duration_s` | number | Approximate run duration |

### Alignment padding

After the JSON string, zero bytes are inserted until the file offset reaches the next multiple of 8. This keeps the binary data sections 8-byte aligned, which is required by numpy's `frombuffer` without a copy.

---

## Telemetry section

### Record layout (28 bytes each)

| Offset | Size | Type    | Field   | Description                        |
|--------|------|---------|---------|------------------------------------|
| 0      | 4    | float32 | `t_sec` | Hardware-counter time in seconds   |
| 4      | 4    | float32 | `Ia`    | Stator current α (A)               |
| 8      | 4    | float32 | `Ib`    | Stator current β (A)               |
| 12     | 4    | float32 | `FluxA` | Rotor flux α (Wb)                  |
| 16     | 4    | float32 | `FluxB` | Rotor flux β (Wb)                  |
| 20     | 4    | float32 | `Speed` | Rotor mechanical speed (rad/s)     |
| 24     | 4    | float32 | `TL`    | Commanded load torque (N·m)        |

Records are stored in chronological order. `t_sec` starts at or near 0 at the beginning of a `Run`.

### Python example

```python
import numpy as np

TELEM_DTYPE = np.dtype([
    ('t_sec',  '<f4'),
    ('Ia',     '<f4'),
    ('Ib',     '<f4'),
    ('FluxA',  '<f4'),
    ('FluxB',  '<f4'),
    ('Speed',  '<f4'),
    ('TL',     '<f4'),
])

def load_hilbin(path):
    with open(path, 'rb') as f:
        data = f.read()

    assert data[:7] == b'HILDATA', "not a .hilbin file"
    version = data[7]
    assert version == 1

    json_size = int.from_bytes(data[8:12], 'little')
    import json
    meta = json.loads(data[12:12 + json_size])

    # Skip to 8-byte aligned boundary
    base = 12 + json_size
    base = (base + 7) & ~7

    telem_count = int.from_bytes(data[base:base+4], 'little')
    telem_bytes = telem_count * 28
    telem = np.frombuffer(data[base+4 : base+4+telem_bytes], dtype=TELEM_DTYPE)

    pwm_base = base + 4 + telem_bytes
    pwm_count = int.from_bytes(data[pwm_base:pwm_base+4], 'little')
    pwm = np.frombuffer(data[pwm_base+4:], dtype=PWM_DTYPE)

    return meta, telem, pwm
```

---

## PWM section

### Record layout (8 bytes each)

| Offset | Size | Type    | Field   | Description                          |
|--------|------|---------|---------|--------------------------------------|
| 0      | 4    | float32 | `t_sec` | Hardware-counter time in seconds     |
| 4      | 1    | int8    | `a`     | NPC gate state phase A (-1, 0, or 1) |
| 5      | 1    | int8    | `b`     | NPC gate state phase B               |
| 6      | 1    | int8    | `c`     | NPC gate state phase C               |
| 7      | 1    | uint8   | `_pad`  | Reserved (write 0, ignore on read)   |

Gate state values follow the NPC encoding: `-1` = −Vdc/2, `0` = 0, `1` = +Vdc/2. Only transition events are stored (not a sampled waveform), so consecutive records may share the same `t_sec` if multiple phases switch simultaneously.

### Python dtype

```python
PWM_DTYPE = np.dtype([
    ('t_sec', '<f4'),
    ('a',     'i1'),
    ('b',     'i1'),
    ('c',     'i1'),
    ('_pad',  'u1'),
])
```

---

## TypeScript writer sketch

```typescript
function serializeHilbin(name: string): ArrayBuffer {
  const meta = JSON.stringify({
    version: 1,
    date: new Date().toISOString(),
    name,
    sample_count: tBuf.length,
    pwm_count: pwmEvents.length,
    npp: motorNpp,
  });
  const metaBytes = new TextEncoder().encode(meta);
  const jsonSize = metaBytes.length;
  const alignedBase = (12 + jsonSize + 7) & ~7;

  const telemBytes = tBuf.length * 28;
  const pwmBytes   = pwmEvents.length * 8;
  const total = alignedBase + 4 + telemBytes + 4 + pwmBytes;

  const buf = new ArrayBuffer(total);
  const view = new DataView(buf);
  const u8 = new Uint8Array(buf);

  // Magic
  "HILDATA".split('').forEach((c, i) => u8[i] = c.charCodeAt(0));
  u8[7] = 1; // version

  // JSON header
  view.setUint32(8, jsonSize, true);
  u8.set(metaBytes, 12);

  // Telem
  let off = alignedBase;
  view.setUint32(off, tBuf.length, true); off += 4;
  for (let i = 0; i < tBuf.length; i++) {
    const s = samplesBuf[i];
    view.setFloat32(off,      tBuf[i],  true);
    view.setFloat32(off + 4,  s.Ia,     true);
    view.setFloat32(off + 8,  s.Ib,     true);
    view.setFloat32(off + 12, s.FluxA,  true);
    view.setFloat32(off + 16, s.FluxB,  true);
    view.setFloat32(off + 20, s.Speed,  true);
    view.setFloat32(off + 24, s.TL ?? 0, true);
    off += 28;
  }

  // PWM
  view.setUint32(off, pwmEvents.length, true); off += 4;
  for (const ev of pwmEvents) {
    view.setFloat32(off, ev.t_sec, true);
    view.setInt8(off + 4, ev.a);
    view.setInt8(off + 5, ev.b);
    view.setInt8(off + 6, ev.c);
    view.setUint8(off + 7, 0);
    off += 8;
  }

  return buf;
}
```

---

## File naming convention

Auto-saved files from the batch runner use:

```
<recipe_name>_<YYYYMMDD_HHMMSS>.hilbin
```

Example: `speed_load_steps_20260530_143022.hilbin`

Manual saves prompt the user for a name; the `.hilbin` extension is appended automatically if absent.
