#!/usr/bin/env python3
"""
tdxdata.py -- TDX (通达信) market data CLI

Multi-command tool for parsing, exporting, batch-processing, querying,
importing, analyzing, and screening TDX market data.

Usage:
    python tdxdata.py parse      <file> [--data-path PATH]
    python tdxdata.py export     <file> [--format csv|parquet|json] --output <path>
    python tdxdata.py batch      <dir>  [--market sh|sz] --output <dir> --format <fmt>
    python tdxdata.py quote      <code> <market>
    python tdxdata.py import     <file> --db <url> --table <name> [--auto-create]
    python tdxdata.py formula    <file>                          # 解析指标公式
    python tdxdata.py finance    <file>                          # 解析财务数据
    python tdxdata.py block      <dir>                           # 解析板块数据
    python tdxdata.py indicator  <code> [--market sh|sz]         # 计算技术指标
    python tdxdata.py screen     [--conditions ...]              # 条件选股
    python tdxdata.py compare    <codes...> [--market sh|sz]     # 多股对比
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Optional dependencies
try:
    from pytdx.hq import TdxHq_API
    PYTDX_AVAILABLE = True
except ImportError:
    PYTDX_AVAILABLE = False

try:
    from sqlalchemy import create_engine, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


# ============================================================================
# Constants
# ============================================================================

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

TDX_DATA_ROOT = Path(os.environ.get("TDX_DATA_ROOT", "C:/new_tdx64"))

# ============================================================================
# Data model
# ============================================================================

@dataclass
class TdxRecord:
    """Single row from a TDX binary file."""
    date: int          # YYYYMMDD
    open: float        # raw (x100)
    high: float
    low: float
    close: float
    amount: float      # 成交额
    volume: int        # 成交量

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


# ============================================================================
# Core parsing
# ============================================================================

def unpack_record(data: bytes) -> TdxRecord:
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
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    raw = path.read_bytes()
    if len(raw) == 0:
        return []
    if len(raw) % RECORD_SIZE != 0:
        raise ValueError(
            f"File size ({len(raw)} bytes) is not a multiple of {RECORD_SIZE}."
        )
    records = [unpack_record(raw[i:i+RECORD_SIZE]) for i in range(0, len(raw), RECORD_SIZE)]
    records.sort(key=lambda r: r.date)
    return records


def records_to_dataframe(records: list[TdxRecord]) -> pd.DataFrame:
    return pd.DataFrame([r.to_dict() for r in records])


# ============================================================================
# Subcommand: parse
# ============================================================================

def cmd_parse(args: argparse.Namespace) -> int:
    records = parse_tdx_file(Path(args.file))
    if not records:
        print("No records found.")
        return 0
    print(f"{'Date':>10}  {'Open':>10}  {'High':>10}  {'Low':>10}  "
          f"{'Close':>10}  {'Amount':>14}  {'Volume':>12}")
    print("-" * 80)
    for r in records:
        print(f"{r.date_str():>10}  {r.open/100:>10.2f}  {r.high/100:>10.2f}  "
              f"{r.low/100:>10.2f}  {r.close/100:>10.2f}  {r.amount:>14.0f}  "
              f"{r.volume:>12,d}")
    print(f"\nTotal: {len(records)} records")
    return 0


# ============================================================================
# Subcommand: export
# ============================================================================

SUPPORTED_FORMATS = {"csv", "parquet", "json"}


def cmd_export(args: argparse.Namespace) -> int:
    records = parse_tdx_file(Path(args.file))
    df = records_to_dataframe(records)
    output = Path(args.output)
    fmt = args.format.lower()
    if fmt not in SUPPORTED_FORMATS:
        print(f"Unsupported format: {fmt}")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        df.to_csv(output, index=False)
    elif fmt == "parquet":
        df.to_parquet(output, index=False)
    elif fmt == "json":
        df.to_json(output, orient="records", indent=2, date_format="iso")
    print(f"Exported {len(df)} rows to {output}")
    return 0


# ============================================================================
# Subcommand: batch (支持 .day .lc1 .lc5)
# ============================================================================

TDX_EXTENSIONS = {"*.day", "*.lc1", "*.lc5"}


def _collect_files(data_dir: Path, market: str | None) -> list[Path]:
    base = data_dir / market if market else data_dir
    files = []
    for ext in TDX_EXTENSIONS:
        files.extend(base.rglob(ext))
    if market:
        for ext in TDX_EXTENSIONS:
            files.extend(data_dir.glob(f"{market}/{ext}"))
    return sorted(set(files))


def cmd_batch(args: argparse.Namespace) -> int:
    if args.format.lower() not in SUPPORTED_FORMATS:
        print(f"Unsupported format: {args.format}")
        return 1

    data_dir = Path(args.dir)
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        return 1

    files = _collect_files(data_dir, args.market)
    if not files:
        print(f"No TDX files found in {data_dir}")
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
            suffix = fpath.suffix.lstrip(".")
            out_path = out_dir / f"{stem}_{suffix}.{fmt}"
            if fmt == "csv":
                df.to_csv(out_path, index=False)
            elif fmt == "parquet":
                df.to_parquet(out_path, index=False)
            elif fmt == "json":
                df.to_json(out_path, orient="records", indent=2, date_format="iso")
            success += 1
            print(f"  [OK]  {fpath.name} -> {out_path}")
        except Exception as exc:
            failed += 1
            print(f"  [FAIL] {fpath.name}: {exc}")

    print(f"\nBatch: {success} OK, {failed} failed")
    return 0


# ============================================================================
# Subcommand: quote
# ============================================================================

def cmd_quote(args: argparse.Namespace) -> int:
    if not PYTDX_AVAILABLE:
        print("pytdx not installed. Run: pip install pytdx")
        return 1

    market_id = 1 if args.market.lower() == "sh" else 0
    code = args.code.zfill(6)

    api = TdxHq_API(heartbeat=True, auto_retry=True)
    try:
        with api.connect():
            data = api.get_security_bars(category=9, market=market_id, code=code, start=0, count=10)
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


# ============================================================================
# Subcommand: import
# ============================================================================

def cmd_import(args: argparse.Namespace) -> int:
    if not SQLALCHEMY_AVAILABLE:
        print("sqlalchemy not installed.")
        return 1

    records = parse_tdx_file(Path(args.file))
    df = records_to_dataframe(records)
    fpath = Path(args.file)
    code = fpath.stem.zfill(6)
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
                UNIQUE(code, market, date)
            )
        """)
        with engine.begin() as conn:
            conn.execute(schema)
        print(f"Table '{table}' ready.")

    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text(f"""
                    INSERT INTO {table} (code, market, date, open, high, low, close, amount, volume)
                    VALUES (:code, :market, :date, :open, :high, :low, :close, :amount, :volume)
                    ON CONFLICT (code, market, date) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                        close=EXCLUDED.close, amount=EXCLUDED.amount, volume=EXCLUDED.volume
                """),
                row.to_dict(),
            )
    print(f"Imported {len(df)} rows into '{table}'.")
    return 0


# ============================================================================
# Subcommand: formula (解析 .sp 指标公式)
# ============================================================================

def cmd_formula(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    # .sp 文件是文本格式，直接读取
    try:
        content = path.read_text(encoding="gbk", errors="replace")
    except Exception:
        content = path.read_text(encoding="utf-8", errors="replace")

    print(f"File: {path.name}")
    print(f"Size: {path.stat().st_size} bytes")
    print("-" * 60)
    print(content)
    print("-" * 60)

    # 提取公式名称
    lines = content.strip().split("\n")
    for line in lines[:5]:
        if line.startswith("{") or line.startswith("//"):
            continue
        if "=" in line:
            name = line.split("=")[0].strip()
            print(f"\nFormula name: {name}")
            break

    return 0


# ============================================================================
# Subcommand: finance (解析财务数据)
# ============================================================================

FINANCIAL_FIELDS = {
    "gjbqy": "股本结构",
    "lrb": "利润表",
    "zcfzb": "资产负债表",
    "xjllb": "现金流量表",
    "jbmgsy": "基本每股收益",
    "mgjzc": "每股净资产",
    "yyzsr": "营业总收入",
    "jlr": "净利润",
    "zjc": "净资产",
}


def parse_financial_dat(path: Path) -> dict:
    """解析通达信财务数据文件."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    raw = path.read_bytes()
    result = {
        "file": path.name,
        "size": len(raw),
        "fields": {},
    }

    # 通达信财务文件格式较复杂，这里做基本解析
    # 实际格式需要根据具体文件类型分析
    if len(raw) >= 4:
        # 尝试读取头部信息
        header = struct.unpack_from("<I", raw, 0)[0]
        result["header"] = header

    return result


def cmd_finance(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    try:
        data = parse_financial_dat(path)
        print(f"File: {data['file']}")
        print(f"Size: {data['size']} bytes")
        print(f"Header: {data.get('header', 'N/A')}")
        print("-" * 60)

        # 尝试以不同编码读取
        raw = path.read_bytes()
        for enc in ["gbk", "utf-8", "gb2312"]:
            try:
                text = raw.decode(enc)
                print(text[:2000])
                break
            except Exception:
                continue
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    return 0


# ============================================================================
# Subcommand: block (解析板块数据)
# ============================================================================

def parse_block_file(path: Path) -> list[str]:
    """解析板块成分股文件."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    # 板块文件是文本格式，每行一个股票代码
    for enc in ["gbk", "utf-8", "gb2312"]:
        try:
            text = raw.decode(enc)
            return [line.strip() for line in text.splitlines() if line.strip()]
        except Exception:
            continue
    return []


def cmd_block(args: argparse.Namespace) -> int:
    block_dir = Path(args.dir)
    if not block_dir.exists():
        print(f"Directory not found: {block_dir}")
        return 1

    # 查找板块配置文件
    cfg_files = list(block_dir.glob("*.cfg"))
    blk_files = list(block_dir.glob("*.blk"))

    print(f"Block directory: {block_dir}")
    print(f"Config files: {len(cfg_files)}")
    print(f"Block files: {len(blk_files)}")
    print("-" * 60)

    for blk in sorted(blk_files):
        codes = parse_block_file(blk)
        print(f"\n{blk.name} ({len(codes)} stocks):")
        if codes:
            print(f"  {', '.join(codes[:20])}")
            if len(codes) > 20:
                print(f"  ... and {len(codes) - 20} more")

    return 0


# ============================================================================
# Subcommand: indicator (计算技术指标)
# ============================================================================

def calc_ma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=1).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd = (dif - dea) * 2
    return dif, dea, macd


def calc_rsi(close: pd.Series, period=14) -> pd.Series:
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n=9, m1=3, m2=3) -> tuple:
    lowest_low = low.rolling(window=n, min_periods=1).min()
    highest_high = high.rolling(window=n, min_periods=1).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    k = rsv.ewm(com=m1-1, adjust=False).mean()
    d = k.ewm(com=m2-1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def calc_boll(close: pd.Series, period=20, std_dev=2) -> tuple:
    mid = calc_ma(close, period)
    std = close.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def cmd_indicator(args: argparse.Namespace) -> int:
    # 确定数据文件路径
    market = args.market or "sh"
    code = args.code.zfill(6)
    tdx_root = Path(args.data_path) if args.data_path else TDX_DATA_ROOT

    # 尝试多种文件名格式
    patterns = [
        f"{market}{code}.day",  # sh600036.day
        f"{code}.day",          # 600036.day
    ]
    data_file = None
    for pat in patterns:
        p = tdx_root / "vipdoc" / market / "lday" / pat
        if p.exists():
            data_file = p
            break

    if not data_file:
        # 尝试另一个市场
        alt_market = "sz" if market == "sh" else "sh"
        for pat in patterns:
            p = tdx_root / "vipdoc" / alt_market / "lday" / pat
            if p.exists():
                data_file = p
                market = alt_market
                break

    if not data_file:
        print(f"Data file not found for {code} in {market}/sz")
        return 1

    records = parse_tdx_file(data_file)
    df = records_to_dataframe(records)

    # 计算技术指标
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # 均线
    for p in [5, 10, 20, 60]:
        df[f"MA{p}"] = calc_ma(close, p)

    # MACD
    dif, dea, macd = calc_macd(close)
    df["DIF"] = dif
    df["DEA"] = dea
    df["MACD"] = macd

    # RSI
    df["RSI6"] = calc_rsi(close, 6)
    df["RSI14"] = calc_rsi(close, 14)

    # KDJ
    k, d, j = calc_kdj(high, low, close)
    df["K"] = k
    df["D"] = d
    df["J"] = j

    # 布林带
    upper, mid, lower = calc_boll(close)
    df["BOLL_UP"] = upper
    df["BOLL_MID"] = mid
    df["BOLL_LOW"] = lower

    # 显示最近N条
    n = args.tail or 20
    cols = ["date_str", "close", "MA5", "MA10", "MA20", "MA60",
            "DIF", "DEA", "MACD", "RSI6", "RSI14", "K", "D", "J"]
    print(f"\n{market.upper()} {code} 技术指标 (最近{n}条):")
    print(df[cols].tail(n).to_string(index=False))
    return 0


# ============================================================================
# Subcommand: screen (条件选股)
# ============================================================================

def screen_stock(records: list[TdxRecord], conditions: dict) -> dict | None:
    """检查单只股票是否满足条件."""
    if len(records) < 60:
        return None

    df = records_to_dataframe(records)
    close = df["close"]
    volume = df["volume"]

    latest = df.iloc[-1]
    result = {
        "date": latest["date_str"],
        "close": latest["close"],
        "volume": latest["volume"],
        "conditions": [],
    }

    matched = True

    # MA金叉: MA5 > MA10 且 MA5前一天 <= MA10
    if conditions.get("ma_cross"):
        ma5 = calc_ma(close, 5)
        ma10 = calc_ma(close, 10)
        if len(ma5) >= 2:
            if ma5.iloc[-1] > ma10.iloc[-1] and ma5.iloc[-2] <= ma10.iloc[-2]:
                result["conditions"].append("MA金叉")
            else:
                matched = False

    # MACD金叉: DIF > DEA 且 DIF前一天 <= DEA
    if conditions.get("macd_cross"):
        dif, dea, _ = calc_macd(close)
        if len(dif) >= 2:
            if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
                result["conditions"].append("MACD金叉")
            else:
                matched = False

    # RSI超卖: RSI < 30
    if conditions.get("rsi_oversold"):
        rsi = calc_rsi(close, 14)
        if rsi.iloc[-1] < 30:
            result["conditions"].append(f"RSI超卖({rsi.iloc[-1]:.1f})")
        else:
            matched = False

    # RSI超买: RSI > 70
    if conditions.get("rsi_overbought"):
        rsi = calc_rsi(close, 14)
        if rsi.iloc[-1] > 70:
            result["conditions"].append(f"RSI超买({rsi.iloc[-1]:.1f})")
        else:
            matched = False

    # 放量: 今日成交量 > 5日均量 * 2
    if conditions.get("volume_surge"):
        vol_ma5 = calc_ma(volume.astype(float), 5)
        if vol_ma5.iloc[-1] > 0 and volume.iloc[-1] > vol_ma5.iloc[-1] * 2:
            result["conditions"].append("放量")
        else:
            matched = False

    # 涨幅 > N%
    if conditions.get("min_change"):
        if len(close) >= 2:
            change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
            if change >= conditions["min_change"]:
                result["conditions"].append(f"涨幅{change:.2f}%")
            else:
                matched = False

    # 跌幅 > N%
    if conditions.get("max_change"):
        if len(close) >= 2:
            change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
            if change <= -conditions["max_change"]:
                result["conditions"].append(f"跌幅{change:.2f}%")
            else:
                matched = False

    # 价格区间
    if conditions.get("min_price") is not None:
        if latest["close"] < conditions["min_price"]:
            matched = False
    if conditions.get("max_price") is not None:
        if latest["close"] > conditions["max_price"]:
            matched = False

    return result if matched else None


def cmd_screen(args: argparse.Namespace) -> int:
    tdx_root = Path(args.data_path) if args.data_path else TDX_DATA_ROOT
    conditions = {}

    if args.ma_cross:
        conditions["ma_cross"] = True
    if args.macd_cross:
        conditions["macd_cross"] = True
    if args.rsi_oversold:
        conditions["rsi_oversold"] = True
    if args.rsi_overbought:
        conditions["rsi_overbought"] = True
    if args.volume_surge:
        conditions["volume_surge"] = True
    if args.min_change is not None:
        conditions["min_change"] = args.min_change
    if args.max_change is not None:
        conditions["max_change"] = args.max_change
    if args.min_price is not None:
        conditions["min_price"] = args.min_price
    if args.max_price is not None:
        conditions["max_price"] = args.max_price

    if not conditions:
        print("No conditions specified. Use --ma-cross, --macd-cross, --rsi-oversold, etc.")
        return 1

    print("Screening conditions:", ", ".join(conditions.keys()))
    print("-" * 60)

    results = []
    for market in ["sh", "sz"]:
        lday_dir = tdx_root / "vipdoc" / market / "lday"
        if not lday_dir.exists():
            continue
        scanned = 0
        for fpath in lday_dir.glob("*.day"):
            scanned += 1
            # 处理 sh600036.day 和 600036.day 两种格式
            stem = fpath.stem
            code = stem.replace(market, "") if stem.startswith(market) else stem
            try:
                records = parse_tdx_file(fpath)
                result = screen_stock(records, conditions)
                if result:
                    result["code"] = code
                    result["market"] = market
                    results.append(result)
            except Exception:
                continue
            if scanned % 100 == 0:
                print(f"  Scanned {market}/{code}... found {len(results)} matches", end="\r")

    print(f"\n\nFound {len(results)} stocks matching conditions:")
    print(f"{'Code':>8}  {'Market':>4}  {'Close':>10}  {'Conditions'}")
    print("-" * 60)
    for r in sorted(results, key=lambda x: x["code"]):
        print(f"{r['code']:>8}  {r['market']:>4}  {r['close']:>10.2f}  {', '.join(r['conditions'])}")

    return 0


# ============================================================================
# Subcommand: compare (多股对比)
# ============================================================================

def cmd_compare(args: argparse.Namespace) -> int:
    tdx_root = Path(args.data_path) if args.data_path else TDX_DATA_ROOT
    market = args.market or "sh"
    codes = [c.zfill(6) for c in args.codes]
    period = args.period or 20

    print(f"Comparing {len(codes)} stocks (last {period} days):")
    print("=" * 80)

    all_data = {}
    for code in codes:
        # 尝试多种文件名格式
        patterns = [
            f"{market}{code}.day",
            f"{code}.day",
        ]
        data_file = None
        for pat in patterns:
            p = tdx_root / "vipdoc" / market / "lday" / pat
            if p.exists():
                data_file = p
                break
        if not data_file:
            alt = "sz" if market == "sh" else "sh"
            for pat in patterns:
                p = tdx_root / "vipdoc" / alt / "lday" / pat
                if p.exists():
                    data_file = p
                    break
        if not data_file:
            print(f"  [SKIP] {code}: not found")
            continue

        records = parse_tdx_file(data_file)
        df = records_to_dataframe(records)
        df = df.tail(period).copy()

        # 计算涨跌幅
        base_price = df["close"].iloc[0]
        df["change_pct"] = (df["close"] / base_price - 1) * 100

        latest = df.iloc[-1]
        ma5 = calc_ma(df["close"], 5).iloc[-1]
        rsi = calc_rsi(df["close"], 14).iloc[-1]

        all_data[code] = {
            "close": latest["close"],
            "change": latest["change_pct"],
            "volume": latest["volume"],
            "ma5": ma5,
            "rsi": rsi,
        }

    if not all_data:
        print("No data found.")
        return 1

    # 输出对比表
    print(f"\n{'Code':>8}  {'Close':>10}  {'Change%':>10}  {'Volume':>12}  {'MA5':>10}  {'RSI':>8}")
    print("-" * 70)
    for code, d in sorted(all_data.items()):
        print(f"{code:>8}  {d['close']:>10.2f}  {d['change']:>+10.2f}%  {d['volume']:>12,.0f}  "
              f"{d['ma5']:>10.2f}  {d['rsi']:>8.1f}")

    # 排名
    print("\n涨幅排名:")
    ranked = sorted(all_data.items(), key=lambda x: x[1]["change"], reverse=True)
    for i, (code, d) in enumerate(ranked, 1):
        bar = "█" * max(0, int(d["change"]))
        print(f"  {i}. {code}: {d['change']:>+.2f}% {bar}")

    return 0


# ============================================================================
# CLI bootstrap
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tdxdata",
        description="TDX (通达信) market data CLI",
    )
    parser.add_argument("--data-path", metavar="PATH",
                        help="Base path for TDX data files")
    sub = parser.add_subparsers(dest="command", required=True)

    # parse
    p = sub.add_parser("parse", help="Parse and display a TDX file")
    p.add_argument("file", help="Path to .day / .lc1 / .lc5 file")

    # export
    p = sub.add_parser("export", help="Export to CSV/Parquet/JSON")
    p.add_argument("file")
    p.add_argument("--format", "-f", default="csv", choices=["csv", "parquet", "json"])
    p.add_argument("--output", "-o", required=True)

    # batch
    p = sub.add_parser("batch", help="Batch process directory")
    p.add_argument("dir")
    p.add_argument("--market", "-m", choices=["sh", "sz"])
    p.add_argument("--output", "-o", required=True)
    p.add_argument("--format", "-f", default="parquet", choices=["csv", "parquet", "json"])

    # quote
    p = sub.add_parser("quote", help="Real-time quote via pytdx")
    p.add_argument("code")
    p.add_argument("market", choices=["sh", "sz"])

    # import
    p = sub.add_parser("import", help="Import to PostgreSQL")
    p.add_argument("file")
    p.add_argument("--db", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--auto-create", action="store_true")
    p.add_argument("--market", "-m", choices=["sh", "sz"])

    # formula
    p = sub.add_parser("formula", help="Parse indicator formula (.sp)")
    p.add_argument("file")

    # finance
    p = sub.add_parser("finance", help="Parse financial data")
    p.add_argument("file")

    # block
    p = sub.add_parser("block", help="Parse block/sector data")
    p.add_argument("dir")

    # indicator
    p = sub.add_parser("indicator", help="Calculate technical indicators")
    p.add_argument("code")
    p.add_argument("--market", "-m", choices=["sh", "sz"])
    p.add_argument("--tail", "-n", type=int, default=20)

    # screen
    p = sub.add_parser("screen", help="Stock screening")
    p.add_argument("--ma-cross", action="store_true")
    p.add_argument("--macd-cross", action="store_true")
    p.add_argument("--rsi-oversold", action="store_true")
    p.add_argument("--rsi-overbought", action="store_true")
    p.add_argument("--volume-surge", action="store_true")
    p.add_argument("--min-change", type=float, help="Min daily change %")
    p.add_argument("--max-change", type=float, help="Max daily drop %")
    p.add_argument("--min-price", type=float)
    p.add_argument("--max-price", type=float)

    # compare
    p = sub.add_parser("compare", help="Compare multiple stocks")
    p.add_argument("codes", nargs="+")
    p.add_argument("--market", "-m", choices=["sh", "sz"])
    p.add_argument("--period", "-n", type=int, default=20)

    return parser


def resolve_data_path(args: argparse.Namespace) -> argparse.Namespace:
    base = Path(args.data_path).resolve() if args.data_path else Path.cwd()
    if args.command in ("parse", "export", "import", "formula", "finance"):
        args.file = str(base / args.file)
    elif args.command in ("batch", "block"):
        args.dir = str(base / args.dir)
    return args


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.data_path and args.command in ("parse", "export", "import", "batch", "formula", "finance", "block"):
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
        case "formula":
            return cmd_formula(args)
        case "finance":
            return cmd_finance(args)
        case "block":
            return cmd_block(args)
        case "indicator":
            return cmd_indicator(args)
        case "screen":
            return cmd_screen(args)
        case "compare":
            return cmd_compare(args)
        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
