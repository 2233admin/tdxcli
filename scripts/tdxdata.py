#!/usr/bin/env python3
"""
tdxdata.py -- TDX (通达信) market data CLI

Multi-command tool for parsing, exporting, batch-processing, querying,
and importing TDX binary files.

Usage:
    python tdxdata.py parse   <file> [--data-path PATH]
    python tdxdata.py export  <file> [--format csv|parquet|json] --output <path>
    python tdxdata.py batch   <dir>   [--market sh|sz] --output <dir> --format <fmt>
    python tdxdata.py quote   <code> <market>
    python tdxdata.py import  <file>  --db <url> --table <name> [--auto-create]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd

# Optional dependencies -- fail gracefully if not installed
try:
    import pytdx
    from pytdx.hq import TdxHq_API
    PYTDX_AVAILABLE = True
except ImportError:
    PYTDX_AVAILABLE = False

try:
    import mootdx
    MOOTDX_AVAILABLE = True
except ImportError:
    MOOTDX_AVAILABLE = False

try:
    from sqlalchemy import create_engine, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

RECORD_SIZE = 32  # bytes per record in .day files
# TDX .day format (32 bytes per record, little-endian):
# 0-3:   date (uint32, YYYYMMDD)
# 4-7:   open (uint32, price x 100)
# 8-11:  high (uint32, price x 100)
# 12-15: low (uint32, price x 100)
# 16-19: close (uint32, price x 100)
# 20-27: amount (double)
# 28-31: volume (uint32)
TDX_STRUCT = struct.Struct("<I I I I I d I")


@dataclass
class TdxRecord:
    """Single row from a TDX binary file."""
    date: int          # YYYYMMDD as integer
    open: float
    high: float
    low: float
    close: float
    amount: float     # 成交额 (double)
    volume: int       # 成交量 (uint32)

    def date_str(self) -> str:
        d = str(self.date)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "date_str": self.date_str(),
            "open": self.open / 100.0,
            "high": self.high / 100.0,
            "low": self.low / 100.0,
            "close": self.close / 100.0,
            "amount": self.amount,
            "volume": self.volume,
        }


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def unpack_record(data: bytes) -> TdxRecord:
    """Unpack a single 32-byte TDX record from bytes."""
    values = TDX_STRUCT.unpack(data)
    return TdxRecord(
        date=int(values[0]),
        open=values[1],
        high=values[2],
        low=values[3],
        close=values[4],
        amount=values[5],
        volume=int(values[6]),
    )


def parse_tdx_file(path: Path) -> list[TdxRecord]:
    """
    Parse a TDX binary file (.day, .lc1, .lc5) and return a list of records.

    Args:
        path: Path to the TDX binary file.

    Returns:
        List of TdxRecord objects sorted by date ascending.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    raw = path.read_bytes()
    if len(raw) == 0:
        return []

    if len(raw) % RECORD_SIZE != 0:
        raise ValueError(
            f"File size ({len(raw)} bytes) is not a multiple of {RECORD_SIZE}. "
            "Possibly corrupted or unsupported file format."
        )

    records: list[TdxRecord] = []
    for offset in range(0, len(raw), RECORD_SIZE):
        chunk = raw[offset : offset + RECORD_SIZE]
        records.append(unpack_record(chunk))

    # Most TDX files are newest-first; stable-sort by date ascending
    records.sort(key=lambda r: r.date)
    return records


def records_to_dataframe(records: list[TdxRecord]) -> pd.DataFrame:
    """Convert a list of TdxRecord to a pandas DataFrame."""
    return pd.DataFrame([r.to_dict() for r in records])


# ---------------------------------------------------------------------------
# Subcommand: parse
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> int:
    """Print a human-readable dump of a TDX file."""
    records = parse_tdx_file(Path(args.file))
    if not records:
        print("No records found.")
        return 0

    # Resolve code/market from filename when possible
    print(f"{'Date':>10}  {'Open':>10}  {'High':>10}  {'Low':>10}  "
          f"{'Close':>10}  {'Amount':>14}  {'Volume':>12}")
    print("-" * 80)

    for r in records:
        print(
            f"{r.date_str():>10}  {r.open/100:>10.2f}  {r.high/100:>10.2f}  "
            f"{r.low/100:>10.2f}  {r.close/100:>10.2f}  {r.amount:>14.0f}  "
            f"{r.volume:>12,d}"
        )

    print(f"\nTotal records: {len(records)}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: export
# ---------------------------------------------------------------------------

SUPPORTED_FORMATS: set[str] = {"csv", "parquet", "json"}


def cmd_export(args: argparse.Namespace) -> int:
    """Export a TDX file to CSV, Parquet, or JSON."""
    records = parse_tdx_file(Path(args.file))
    df = records_to_dataframe(records)

    output = Path(args.output)
    fmt = args.format.lower()
    if fmt not in SUPPORTED_FORMATS:
        print(f"Unsupported format: {fmt}. Choose from: {', '.join(SUPPORTED_FORMATS)}")
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        df.to_csv(output, index=False)
        print(f"Exported {len(df)} rows to {output}")
    elif fmt == "parquet":
        df.to_parquet(output, index=False)
        print(f"Exported {len(df)} rows to {output}")
    elif fmt == "json":
        df.to_json(output, orient="records", indent=2, date_format="iso")
        print(f"Exported {len(df)} rows to {output}")

    return 0


# ---------------------------------------------------------------------------
# Subcommand: batch
# ---------------------------------------------------------------------------

MARKET_MAP: dict[str, Path] = {"sh": Path("sh"), "sz": Path("sz")}


def _collect_files(data_dir: Path, market: str | None) -> list[Path]:
    """Collect all .day files under data_dir[/market/]."""
    base = data_dir / MARKET_MAP.get(market, Path("")) if market else data_dir
    files = list(base.rglob("*.day"))
    # Also scan flat market roots
    if market:
        flat = list(data_dir.glob(f"{market}/*.day"))
        files.extend(flat)
    return sorted(set(files))


def cmd_batch(args: argparse.Namespace) -> int:
    """Process all TDX files in a directory."""
    if args.format.lower() not in SUPPORTED_FORMATS:
        print(f"Unsupported format: {args.format}")
        return 1

    data_dir = Path(args.data_path) if args.data_path else Path(args.dir)
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        return 1

    files = _collect_files(data_dir, args.market)
    if not files:
        print(f"No .day files found in {data_dir}")
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt = args.format.lower()
    success, failed = 0, 0

    for fpath in files:
        try:
            records = parse_tdx_file(fpath)
            df = records_to_dataframe(records)
            stem = fpath.stem
            out_path = out_dir / f"{stem}.{fmt}"

            if fmt == "csv":
                df.to_csv(out_path, index=False)
            elif fmt == "parquet":
                df.to_parquet(out_path, index=False)
            elif fmt == "json":
                df.to_json(out_path, orient="records", indent=2, date_format="iso")

            success += 1
            print(f"  [OK]  {fpath.name} -> {out_path}")
        except Exception as exc:  # pragma: no cover
            failed += 1
            print(f"  [FAIL] {fpath.name}: {exc}")

    print(f"\nBatch complete: {success} succeeded, {failed} failed")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: quote
# ---------------------------------------------------------------------------

def cmd_quote(args: argparse.Namespace) -> int:
    """Fetch real-time quote via pytdx."""
    if not PYTDX_AVAILABLE:
        print("pytdx is not installed. Run: pip install pytdx")
        return 1

    market_id = 1 if args.market.lower() == "sh" else 0
    code = args.code.zfill(6)

    api = TdxHq_API(heartbeat=True, auto_retry=True)
    try:
        with api.connect():
            data = api.get_security_bars(
                category=9,  # realtime
                market=market_id,
                code=code,
                start=0,
                count=10,
            )
        if not data:
            print("No quote data returned.")
            return 1

        df = pd.DataFrame(data=data)
        print(df.to_string(index=False))
        return 0
    except Exception as exc:
        print(f"Quote failed: {exc}")
        return 1
    finally:
        try:
            api.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Subcommand: import
# ---------------------------------------------------------------------------

def cmd_import(args: argparse.Namespace) -> int:
    """Import a TDX file into a PostgreSQL table."""
    if not SQLALCHEMY_AVAILABLE:
        print("sqlalchemy is not installed. Run: pip install sqlalchemy psycopg2-binary")
        return 1

    records = parse_tdx_file(Path(args.file))
    df = records_to_dataframe(records)

    # Inject code/market from filename convention: e.g. 600000.day or sh/600000.day
    fpath = Path(args.file)
    code = fpath.stem.zfill(6)
    # Infer market from parent dir if present
    parent_name = fpath.parent.name
    market = parent_name if parent_name in ("sh", "sz") else (args.market or "unknown")

    df.insert(0, "code", code)
    df.insert(1, "market", market)

    engine = create_engine(args.db)
    table = args.table

    if args.auto_create:
        schema = text(f"""
            CREATE TABLE IF NOT EXISTS {table} (
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
                reserve NUMERIC(10,3),
                UNIQUE(code, market, date)
            )
        """)
        with engine.begin() as conn:
            conn.execute(schema)
        print(f"Table '{table}' created (or already exists).")

    # Upsert rows
    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text(f"""
                    INSERT INTO {table}
                        (code, market, date, open, high, low, close, amount, volume, reserve)
                    VALUES
                        (:code, :market, :date, :open, :high, :low, :close, :amount, :volume, :reserve)
                    ON CONFLICT (code, market, date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        amount = EXCLUDED.amount,
                        volume = EXCLUDED.volume
                """),
                row.to_dict(),
            )

    print(f"Imported {len(df)} rows into '{table}'.")
    return 0


# ---------------------------------------------------------------------------
# CLI bootstrap
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tdxdata",
        description="TDX (通达信) market data CLI -- parse, export, batch, quote, import.",
    )
    parser.add_argument(
        "--data-path",
        metavar="PATH",
        help="Base path for TDX data files (default: current directory)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # parse
    p_parse = sub.add_parser("parse", help="Parse and display a TDX file")
    p_parse.add_argument("file", help="Path to .day / .lc1 / .lc5 file")

    # export
    p_exp = sub.add_parser("export", help="Export a TDX file to CSV / Parquet / JSON")
    p_exp.add_argument("file", help="Path to TDX file")
    p_exp.add_argument("--format", "-f", default="csv",
                       choices=["csv", "parquet", "json"],
                       help="Output format (default: csv)")
    p_exp.add_argument("--output", "-o", required=True, help="Output file path")

    # batch
    p_batch = sub.add_parser("batch", help="Batch process all TDX files in a directory")
    p_batch.add_argument("dir", help="Directory containing TDX files")
    p_batch.add_argument("--market", "-m", choices=["sh", "sz"],
                         help="Filter by market (sh / sz)")
    p_batch.add_argument("--output", "-o", required=True,
                         help="Output directory")
    p_batch.add_argument("--format", "-f", default="parquet",
                         choices=["csv", "parquet", "json"],
                         help="Output format (default: parquet)")

    # quote
    p_quote = sub.add_parser("quote", help="Fetch real-time quote via pytdx")
    p_quote.add_argument("code", help="Stock code, e.g. 600000")
    p_quote.add_argument("market", choices=["sh", "sz"], help="Market (sh / sz)")

    # import
    p_imp = sub.add_parser("import", help="Import TDX file into PostgreSQL")
    p_imp.add_argument("file", help="Path to TDX file")
    p_imp.add_argument("--db", required=True,
                       help="SQLAlchemy database URL, e.g. postgresql://user:pass@host:5432/db")
    p_imp.add_argument("--table", required=True, help="Target table name")
    p_imp.add_argument("--auto-create", action="store_true",
                       help="Auto-create the target table if it does not exist")
    p_imp.add_argument("--market", "-m", choices=["sh", "sz"],
                       help="Override market inference from path")

    return parser


def resolve_data_path(args: argparse.Namespace) -> argparse.Namespace:
    """Prepend --data-path to positional args that represent file/dir paths."""
    base = Path(args.data_path).resolve() if args.data_path else Path.cwd()
    if args.command in ("parse", "export", "import"):
        args.file = str(base / args.file)
    elif args.command == "batch":
        args.dir = str(base / args.dir)
    return args


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.data_path and args.command in ("parse", "export", "import", "batch"):
        args = resolve_data_path(args)

    match args.command:
        case "parse":
            return cmd_parse(args)
        case "export":
            return cmd_export(args)
        case "batch":
            return cmd_batch(args)
        case "quote":
            return cmd_quote(args)
        case "import":
            return cmd_import(args)
        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
