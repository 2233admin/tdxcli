# tdxcli

Command-line tools for reading, parsing, exporting, analyzing, and screening TDX (通达信) market data.

## Installation

```bash
pip install pandas pyarrow mootdx pytdx sqlalchemy psycopg2-binary numpy
```

## Quick Start

```bash
# Parse and display a single file
python scripts/tdxdata.py parse data/sh/600000.day

# Export to CSV
python scripts/tdxdata.py export data/sh/600000.day --format csv -o 600000.csv

# Export to Parquet (compressed)
python scripts/tdxdata.py export data/sh/600000.day --format parquet -o 600000.parquet

# Batch process all .day/.lc1/.lc5 files
python scripts/tdxdata.py batch data/sh/ --output sh_parquet/ --format parquet

# Real-time quote (requires pytdx)
python scripts/tdxdata.py quote 600000 sh

# Import into PostgreSQL
python scripts/tdxdata.py import data/sh/600000.day \
  --db postgresql://user:pass@localhost:5432/market \
  --table stock_daily --auto-create

# Parse indicator formula (.sp file)
python scripts/tdxdata.py formula C:/new_tdx64/funcs/AI_BIGDATA.sp

# Parse financial data
python scripts/tdxdata.py finance C:/new_tdx64/vipdoc/cw/gpbj920000.dat

# Parse block/sector data
python scripts/tdxdata.py block C:/new_tdx64/T0002/blocknew

# Calculate technical indicators (MA/MACD/RSI/KDJ/BOLL)
python scripts/tdxdata.py indicator 600036 --market sh --tail 20

# Stock screening
python scripts/tdxdata.py screen --ma-cross --rsi-oversold
python scripts/tdxdata.py screen --macd-cross --volume-surge --min-price 10

# Compare multiple stocks
python scripts/tdxdata.py compare 600036 601318 600519 --market sh --period 20
```

## Command Reference

| Command | Description |
|---------|-------------|
| `parse` | Parse and display a TDX binary file |
| `export` | Convert to CSV, Parquet, or JSON |
| `batch` | Process all TDX files in a directory (supports .day/.lc1/.lc5) |
| `quote` | Fetch real-time quotes via pytdx |
| `import` | Upsert records into PostgreSQL |
| `formula` | Parse indicator formula (.sp files) |
| `finance` | Parse financial data files |
| `block` | Parse block/sector data |
| `indicator` | Calculate technical indicators |
| `screen` | Condition-based stock screening |
| `compare` | Compare multiple stocks |

## Technical Indicators

The `indicator` command calculates:

| Indicator | Description |
|-----------|-------------|
| MA5/10/20/60 | Moving averages |
| MACD (DIF/DEA/MACD) | Moving Average Convergence Divergence |
| RSI6/RSI14 | Relative Strength Index |
| KDJ (K/D/J) | Stochastic oscillator |
| BOLL (UP/MID/LOW) | Bollinger Bands |

## Stock Screening Conditions

| Flag | Description |
|------|-------------|
| `--ma-cross` | MA5 crosses above MA10 (golden cross) |
| `--macd-cross` | MACD golden cross |
| `--rsi-oversold` | RSI14 < 30 |
| `--rsi-overbought` | RSI14 > 70 |
| `--volume-surge` | Volume > 2x 5-day average |
| `--min-change N` | Daily gain >= N% |
| `--max-change N` | Daily drop >= N% |
| `--min-price N` | Price >= N |
| `--max-price N` | Price <= N |

## TDX File Format

Each `.day` file is a sequence of **32-byte records** (little-endian):

| Offset | Type | Field | Description |
|--------|------|-------|-------------|
| 0 | uint32 | date | Packed YYYYMMDD |
| 4 | uint32 | open | Price x 100 |
| 8 | uint32 | high | Price x 100 |
| 12 | uint32 | low | Price x 100 |
| 16 | uint32 | close | Price x 100 |
| 20 | double | amount | Turnover (RMB) |
| 28 | uint32 | volume | Volume (lots) |

## Data Sources

- **Local files**: `vipdoc/{sh,sz}/lday/*.day`, `vipdoc/{sh,sz}/minline/*.lc1`, `vipdoc/{sh,sz}/fzline/*.lc5`
- **mootdx**: Read local files + remote HTTP
- **pytdx**: Real-time quotes from TDX servers (port 7709)

## Requirements

- Python 3.10+
- pandas, numpy
- pyarrow (Parquet)
- mootdx (local file reading)
- pytdx (real-time quotes)
- sqlalchemy + psycopg2-binary (PostgreSQL import)
