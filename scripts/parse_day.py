#!/usr/bin/env python3
"""
parse_day.py -- Standalone TDX binary file parser.

Lightweight utility to dump a single .day / .lc1 / .lc5 file to stdout.
Use as:  python parse_day.py <file> [--csv]

Python 3.10+ required (structural pattern matching, PosixPath).
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
TDX_STRUCT = struct.Struct("<I6fI4x")  # date, 6 floats, reserve (4 bytes padding)


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
    volume: float

    @property
    def date_iso(self) -> str:
        d = str(self.date)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    def dict(self) -> dict:
        return {
            "date": self.date,
            "date_iso": self.date_iso,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "amount": self.amount,
            "volume": int(self.volume),
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
            volume=float(values[6]),
        )


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_table(records: list[DayBar]) -> None:
    header = (f"{'Date':>10}  {'Open':>10}  {'High':>10}  "
              f"{'Low':>10}  {'Close':>10}  {'Amount':>14}  {'Volume':>12}")
    sep = "-" * len(header)
    print(header)
    print(sep)
    for r in records:
        print(
            f"{r.date_iso:>10}  {r.open:>10.3f}  {r.high:>10.3f}  "
            f"{r.low:>10.3f}  {r.close:>10.3f}  {r.amount:>14.3f}  "
            f"{int(r.volume):>12,}"
        )
    print(sep)
    print(f"{len(records)} records")


def write_csv(records: list[DayBar], out: Path) -> None:
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["date", "date_iso", "open", "high", "low", "close", "amount", "volume"],
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
    p.add_argument("--csv", type=Path, metavar="PATH",
                   help="Write records to CSV file instead of printing table")
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
