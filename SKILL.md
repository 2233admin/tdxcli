# tdxcli

Use when the user needs to read TDX (通达信) market data, parse `.day`/`.lc1`/`.lc5` files, export to CSV/Parquet/JSON, or query real-time quotes via pytdx.

## Prerequisites

- Python 3.10 or higher
- `pip install mootdx pytdx pandas pyarrow sqlalchemy psycopg2-binary`

## Bundled Scripts

| Script | Purpose |
|--------|---------|
| `scripts/tdxdata.py` | Multi-command CLI: parse, export, batch, quote, import |
| `scripts/parse_day.py` | Standalone TDX file parser utility |

## Usage

```bash
# Parse a single TDX file
python scripts/tdxdata.py parse data/sh/600000.day

# Export to CSV
python scripts/tdxdata.py export data/sh/600000.day --format csv --output 600000.csv

# Export to Parquet (recommended for large datasets)
python scripts/tdxdata.py export data/sh/600000.day --format parquet --output 600000.parquet

# Batch process an entire market directory
python scripts/tdxdata.py batch data/sh/ --output sh_export/ --format parquet

# Real-time quote
python scripts/tdxdata.py quote 600000 sh

# Import to PostgreSQL
python scripts/tdxdata.py import data/sh/600000.day --table stock_daily --db postgresql://user:pass@localhost:5432/tdx

# Custom data path
python scripts/tdxdata.py parse 600000.day --data-path /mnt/tdx/data
```

## Data Format

TDX files are binary with 32-byte records:

| Field | Type | Offset | Description |
|-------|------|--------|-------------|
| date | uint32 | 0 | Packed date (YYYYMMDD) |
| open | float | 4 | Opening price |
| high | float | 8 | Highest price |
| low | float | 12 | Lowest price |
| close | float | 16 | Closing price |
| amount | float | 20 | Turnover amount |
| volume | float | 24 | Trading volume |
| reserve | float | 28 | Reserved field |

## Troubleshooting

**mootdx reads no data**: Check your `vipdoc` path. Default: `~/.mootdx/`

**pytdx connection fails**: Verify your firewall allows outbound TCP on the quote port (7709 for standard, 443 for HTTPS).

**Import fails**: Ensure PostgreSQL tables exist. Run the schema below or let `--auto-create` handle it.

```sql
CREATE TABLE IF NOT EXISTS stock_daily (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    market TEXT NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(10,3),
    high NUMERIC(10,3),
    low NUMERIC(10,3),
    close NUMERIC(10,3),
    amount NUMERIC(20,3),
    volume BIGINT,
    UNIQUE(code, market, date)
);
CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(code);
```
