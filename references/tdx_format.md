# TDX (通达信) File Format Reference

## Overview

通达信 (TDX) stores market data in compact binary files, one file per security,
organized by market (`sh/` and `sz/` directories).

| Extension | Content | Notes |
|-----------|---------|-------|
| `.day` | Daily K-line (OHLCV) | Most common; daily bars |
| `.lc1` | 1-minute K-line | Minute-level bars |
| `.lc5` | 5-minute K-line | 5-minute aggregated bars |
| `.lc*` | Other minute intervals | 15, 30, 60 min variants |

File naming convention: `<code>.day`, e.g. `600000.day`, `000001.day`.

---

## Binary Structure

Each record is **32 bytes**, little-endian, no header.

```
Offset  Size  Type     Field     Description
------  ----  -------  --------  ------------------------------------------
0       4     uint32   date      Packed date: YYYYYMMDD as integer
4       4     float    open      Opening price
8       4     float    high      Highest price
12      4     float    low       Lowest price
16      4     float    close     Closing price
20      4     float    amount    Turnover amount (in currency units)
24      4     float    volume    Trading volume (in lots / 手)
28      4     float    reserve   Reserved / unused padding
------  ----           --------  ------------------------------------------
Total: 32 bytes per record
```

### Packed Date Format

The `date` field stores `YYYYMMDD` as a packed integer. For example:

| Date | Integer value |
|------|--------------|
| 2024-01-15 | 20240115 |
| 1990-12-19 | 19901219 |

Decompose in Python:

```python
year   = date // 10000
month  = (date // 100) % 100
day    = date % 100
```

### Price and Amount Scaling

- Prices are stored as-is (no scaling factor). For A-shares, they are in
  **CNY (yuan)** with 3 decimal places typically.
- `amount` = `close price * volume` (currency units, e.g. RMB).
- `volume` is stored as a float but represents whole lots (1 lot = 100 shares).

---

## File Ordering

TDX files may be written in **newest-first** order (append newest records to
the front or overwrite older records with newer data). Always sort by `date`
after reading to get chronological order.

```python
# Correct: sort ascending
records.sort(key=lambda r: r.date)
```

---

## How mootdx Works

[mootdx](https://github.com/mootdx/mootdx) is a Python library that wraps TDX
file reading and supports both local files and remote (HTTP) access.

### Local file reading

```python
from mootdx import daily

df = daily(symbol="600000", path="/path/to/vipdoc")
```

- It reads `.day` files from the `vipdoc` directory hierarchy.
- Automatically converts the binary records to a `pandas.DataFrame`.
- Handles file不存在 gracefully.

### Remote reading

```python
from mootdx.server import ApiBar

api = ApiBar()
df = api.bars(symbol="600000", market="sh")
```

- `mootdx` can fetch data from remote TDX servers over HTTP.
- Falls back to local files when remote is unavailable.

### Default data path

```
~/.mootdx/               # Linux/macOS
%APPDATA%\.mootdx\       # Windows
```

The standard TDX `vipdoc` layout:

```
vipdoc/
├── sh/    # Shanghai exchange files
│   ├── 600000.day
│   └── ...
└── sz/    # Shenzhen exchange files
    ├── 000001.day
    └── ...
```

---

## How pytdx Works

[pytdx](https://github.com/rainx/pytdx) connects directly to TDX quote servers
using the TDX binary protocol (port 7709).

### Real-time quotes

```python
from pytdx.hq import TdxHq_API

api = TdxHq_API()
api.connect(host="119.97.132.15", port=7709)
bars = api.get_security_bars(category=9, market=1, code="600000", start=0, count=10)
api.disconnect()
```

### pytdx market codes

| Market | Code |
|--------|------|
| Shanghai (sh) | 1 |
| Shenzhen (sz) | 0 |

### pytdx category codes

| Category | Description |
|----------|-------------|
| 0 | Index (指数) |
| 1 | Shanghai A |
| 2 | Shanghai B |
| 3 | Shenzhen A |
| 4 | Shenzhen B |
| 5 | Combined (涓? |
| 6 | ETF |
| 9 | Realtime (当日分时) |
| 14 | 1-minute K-line |
| 15 | 5-minute K-line |

### Historical daily bars

```python
from pytdx.hq import TdxHq_API

api = TdxHq_API()
api.connect()
# Get last 500 daily bars for 600000 on Shanghai
bars = api.get_security_bars(
    category=4,   # daily K-line
    market=1,     # Shanghai
    code="600000",
    start=0,
    count=500,
)
api.disconnect()
```

---

## Comparison: mootdx vs pytdx

| Feature | mootdx | pytdx |
|---------|--------|-------|
| Local file parsing | Yes | No (network only) |
| Remote quotes | Yes (HTTP) | Yes (binary protocol) |
| Dependencies | lightweight | lightweight |
| Historical data | Local files + remote | Remote only |
| Real-time | Via remote | Yes (binary) |

For best results, use **mootdx for historical file parsing** (when you have
local `.day` files) and **pytdx for real-time quotes**.

---

## Example: Manual Parser

```python
import struct

RECORD = struct.Struct("<I6fI4x")  # 32-byte little-endian record

def read_day(path: str) -> list[dict]:
    records = []
    with open(path, "rb") as f:
        while chunk := f.read(32):
            values = RECORD.unpack(chunk)
            date = str(values[0])
            records.append({
                "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
                "open": values[1],
                "high": values[2],
                "low": values[3],
                "close": values[4],
                "amount": values[5],
                "volume": int(values[6]),
            })
    return sorted(records, key=lambda r: r["date"])
```

---

## Common Issues

1. **File not found**: Ensure `vipdoc/sh/` and `vipdoc/sz/` directories match
   what your data provider uses. Different data sources use different root paths.
2. **Wrong byte order**: TDX files are always **little-endian**. Big-endian
   reads produce garbage values.
3. **Corrupted records**: If `len(file) % 32 != 0`, the file may be truncated
   or from a non-standard source.
4. **Negative prices**: Usually indicates wrong struct format string (float vs int
   swapped, or little vs big endian).
