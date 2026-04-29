# tdxcli

Command-line tools for reading, parsing, and exporting TDX (通达信) market data files.

## Installation

```bash
# Clone or extract to ~/tdxcli
cd ~/tdxcli

# Install Python dependencies
pip install pandas pyarrow mootdx pytdx sqlalchemy psycopg2-binary
```

Or install as a package (when published):

```bash
pip install tdxcli
```

## Quick Start

```bash
# Parse and display a single file
python scripts/tdxdata.py parse data/sh/600000.day

# Export to CSV
python scripts/tdxdata.py export data/sh/600000.day --format csv -o 600000.csv

# Export to Parquet (fast, compressed)
python scripts/tdxdata.py export data/sh/600000.day --format parquet -o 600000.parquet

# Batch process an entire market directory
python scripts/tdxdata.py batch data/sh/ --output sh_parquet/ --format parquet

# Real-time quote (requires pytdx)
python scripts/tdxdata.py quote 600000 sh

# Import into PostgreSQL
python scripts/tdxdata.py import data/sh/600000.day \
  --db postgresql://user:pass@localhost:5432/market \
  --table stock_daily \
  --auto-create
```

## Command Reference

### `parse`

Parse and display a TDX binary file as a human-readable table.

```bash
python scripts/tdxdata.py parse <file>
```

### `export`

Convert a TDX file to CSV, Parquet, or JSON.

```bash
python scripts/tdxdata.py export <file> -f csv|parquet|json -o <output>
```

| Format | Best for | Notes |
|--------|----------|-------|
| `csv` | Human inspection, small datasets | Plain text, portable |
| `parquet` | Large datasets, analytics | Columnar, compressed, ~10x smaller than CSV |
| `json` | Interop with web tools | Larger than CSV, human-readable |

### `batch`

Process all `.day` files in a directory recursively.

```bash
python scripts/tdxdata.py batch <dir> -o <output_dir> -f csv|parquet|json [-m sh|sz]
```

### `quote`

Fetch real-time quotes via pytdx.

```bash
python scripts/tdxdata.py quote <code> <market>
# Example
python scripts/tdxdata.py quote 600000 sh
```

### `import`

Upsert TDX records into a PostgreSQL table (creates table with `--auto-create`).

```bash
python scripts/tdxdata.py import <file> \
  --db postgresql://user:pass@localhost:5432/db \
  --table stock_daily \
  --auto-create
```

## Standalone Script: parse_day.py

A lightweight alternative for quick inspection:

```bash
python scripts/parse_day.py data/sh/600000.day
python scripts/parse_day.py data/sh/600000.day --csv 600000.csv
```

## Data Directory

By default, file paths are relative to the current working directory.
Use `--data-path` to specify a custom root:

```bash
python scripts/tdxdata.py parse 600000.day --data-path /mnt/tdx/vipdoc
# Resolves to /mnt/tdx/vipdoc/600000.day
```

## TDX File Format

Each `.day` file is a sequence of **32-byte records**:

```
Offset  Field     Type    Description
------  --------- ------  -------------
0       date      uint32  Packed date (YYYYMMDD)
4       open      float   Opening price
8       high     float   Highest price
12      low      float   Lowest price
16      close    float   Closing price
20      amount   float   Turnover amount
24      volume   float   Volume in lots
28      reserve  float   Padding
```

See `references/tdx_format.md` for the full specification.

## Data Sources

- **mootdx**: Read local `.day` files and remote HTTP sources.
  Default path: `~/.mootdx/`
- **pytdx**: Real-time quotes from TDX quote servers (port 7709).

## Requirements

- Python 3.10+
- pandas
- pyarrow (for Parquet export)
- mootdx (for file parsing)
- pytdx (for real-time quotes)
- sqlalchemy + psycopg2-binary (for PostgreSQL import)
