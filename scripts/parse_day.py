#!/usr/bin/env python3
"""
parse_day.py -- Standalone TDX binary file parser.

Lightweight utility to dump a single .day / .lc1 / .lc5 file to stdout.
Use as:  python parse_day.py <file> [--csv]

Python 3.10+ required.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Binary format constants
# ---------------------------------------------------------------------------

RECORD_SIZE = 32
# TDX .day format (32 bytes per record, little-endian):
# 0-3:   date (uint32, YYYYMMDD)
# 4-7:   open (uint32, price x 100)
# 8-11:  high (uint32, price x 100)
# 12-15: low (uint32, price x 100)
# 16-19: close (uint32, price x 100)
# 20-23: amount (float32, 成交额)
# 24-27: volume (uint32, 成交量)
# 28-31: reserved (4 bytes padding)
TDX_STRUCT = struct.Struct("<I I I I I f I 4x")


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class DayBar:
    date: int
    open: float
    high: float
    low: float
    close: float
    amount: float
    volume: int

    @property
    def date_iso(self) -> str:
        d = str(self.date)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    def dict(self) -> dict:
        return {
            "date": self.date,
            "date_iso": self.date_iso,
            "open": self.open / 100.0,
            "high": self.high / 100.0,
            "low": self.low / 100.0,
            "close": self.close / 100.0,
            "amount": self.amount,
            "volume": self.volume,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def iter_records(path: Path) -> Iterator[DayBar]:
    """Yield DayBar records from a TDX binary file, oldest first."""
    raw = path.read_bytes()
    if len(raw) % RECORD_SIZE != 0:
        raise ValueError(f"File size {len(raw)} is not divisible by {RECORD_SIZE}")

    for offset in range(0, len(raw), RECORD_SIZE):
        chunk = raw[offset : offset + RECORD_SIZE]
        values = TDX_STRUCT.unpack(chunk)
        yield DayBar(
            date=int(values[0]),
            open=float(values[1]),
            high=float(values[2]),
            low=float(values[3]),
            close=float(values[4]),
            amount=float(values[5]),
            volume=int(values[6]),
        )


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def print_table(records: list[DayBar]) -> None:
    header = (
        f"{'Date':>10}  {'Open':>10}  {'High':>10}  "
        f"{'Low':>10}  {'Close':>10}  {'Amount':>14}  {'Volume':>12}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)
    for r in records:
        d = r.dict()
        print(
            f"{r.date_iso:>10}  {d['open']:>10.2f}  {d['high']:>10.2f}  "
            f"{d['low']:>10.2f}  {d['close']:>10.2f}  {d['amount']:>14.0f}  "
            f"{d['volume']:>12,}"
        )
    print(sep)
    print(f"{len(records)} records")


def write_csv(records: list[DayBar], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "date",
                "date_iso",
                "open",
                "high",
                "low",
                "close",
                "amount",
                "volume",
            ],
        )
        writer.writeheader()
        writer.writerows(r.dict() for r in records)
    print(f"Wrote {len(records)} rows to {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Parse a TDX binary file and print its contents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("file", type=Path, help="Path to .day / .lc1 / .lc5 file")
    p.add_argument(
        "--csv",
        type=Path,
        metavar="PATH",
        help="Write records to CSV file instead of printing table",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        records = list(iter_records(args.file))
    except FileNotFoundError:
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No records found.", file=sys.stderr)
        return 1

    if args.csv:
        write_csv(records, args.csv)
    else:
        print_table(records)

    return 0


if __name__ == "__main__":
    sys.exit(main())
