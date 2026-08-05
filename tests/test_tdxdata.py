"""Tests for tdxcli core functions.

Run: pytest tests/ -v
"""
from __future__ import annotations

import sys
import struct
import tempfile
from pathlib import Path

import pandas as pd
import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tdxdata import (
    TDX_STRUCT,
    TdxRecord,
    calc_boll,
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    parse_tdx_file,
    records_to_dataframe,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_records() -> list[TdxRecord]:
    """5 days of synthetic OHLCV data."""
    return [
        TdxRecord(date=20240101, open=10000, high=10500, low=9800, close=10200, amount=1_000_000.0, volume=10000),
        TdxRecord(date=20240102, open=10200, high=10800, low=10100, close=10700, amount=1_200_000.0, volume=12000),
        TdxRecord(date=20240103, open=10700, high=11000, low=10600, close=10900, amount=1_100_000.0, volume=11000),
        TdxRecord(date=20240104, open=10900, high=11200, low=10800, close=11100, amount=1_300_000.0, volume=13000),
        TdxRecord(date=20240105, open=11100, high=11500, low=11000, close=11400, amount=1_500_000.0, volume=15000),
    ]


@pytest.fixture
def tmp_day_file(tmp_path: Path, sample_records: list[TdxRecord]) -> Path:
    """Write a synthetic .day file and return its path."""
    f = tmp_path / "sh600000.day"
    with open(f, "wb") as fh:
        for rec in sample_records:
            fh.write(
                struct.pack(
                    "<I I I I I f I 4x",
                    rec.date, rec.open, rec.high, rec.low, rec.close, rec.amount, rec.volume
                )
            )
    # Work around Windows pytest temp dir permission issue on cleanup
    yield f
    try:
        f.unlink(missing_ok=True)
    except PermissionError:
        pass


# ============================================================================
# TdxRecord
# ============================================================================


class TestTdxRecord:
    def test_date_str(self) -> None:
        r = TdxRecord(date=20240115, open=10000, high=10500, low=9800, close=10200, amount=500_000.0, volume=5000)
        assert r.date_str() == "2024-01-15"

    def test_to_dict_scales_prices(self) -> None:
        r = TdxRecord(date=20240101, open=10000, high=10500, low=9800, close=10200, amount=100.0, volume=10)
        d = r.to_dict()
        assert d["open"] == 100.0
        assert d["high"] == 105.0
        assert d["low"] == 98.0
        assert d["close"] == 102.0
        assert d["amount"] == 100.0
        assert d["volume"] == 10


# ============================================================================
# Binary parsing
# ============================================================================


class TestParseTdxFile:
    def test_parse_returns_records(self, tmp_day_file: Path) -> None:
        records = parse_tdx_file(tmp_day_file)
        assert len(records) == 5

    def test_parse_correct_values(self, tmp_day_file: Path) -> None:
        records = parse_tdx_file(tmp_day_file)
        r = records[0]
        assert r.date == 20240101
        assert r.open == 10000
        assert r.close == 10200
        assert r.volume == 10000
        assert r.amount == 1_000_000.0

    def test_parse_bad_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_tdx_file(Path("/nonexistent/sh600000.day"))

    def test_record_size_is_32_bytes(self) -> None:
        assert TDX_STRUCT.size == 32


# ============================================================================
# DataFrame conversion
# ============================================================================


class TestRecordsToDataFrame:
    def test_returns_dataframe(self, sample_records: list[TdxRecord]) -> None:
        df = records_to_dataframe(sample_records)
        assert isinstance(df, pd.DataFrame)

    def test_has_required_columns(self, sample_records: list[TdxRecord]) -> None:
        df = records_to_dataframe(sample_records)
        for col in ["date", "open", "high", "low", "close", "amount", "volume"]:
            assert col in df.columns

    def test_scaled_prices(self, sample_records: list[TdxRecord]) -> None:
        df = records_to_dataframe(sample_records)
        assert df["close"].iloc[0] == 102.0

    def test_empty_input(self) -> None:
        df = records_to_dataframe([])
        assert len(df) == 0


# ============================================================================
# Technical indicators
# ============================================================================


class TestCalcMa:
    def test_ma_period_1(self) -> None:
        s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        ma = calc_ma(s, 1)
        assert list(ma) == [10.0, 20.0, 30.0, 40.0, 50.0]

    def test_ma_period_3(self) -> None:
        s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
        ma = calc_ma(s, 3)
        # min_periods=1: first value = self, then expanding window
        assert abs(ma.iloc[0] - 10.0) < 0.01
        assert abs(ma.iloc[1] - 15.0) < 0.01
        assert abs(ma.iloc[2] - 20.0) < 0.01  # (10+20+30)/3

    def test_returns_series(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        ma = calc_ma(s, 2)
        assert isinstance(ma, pd.Series)


class TestCalcMacd:
    def test_returns_three_series(self) -> None:
        s = pd.Series([float(i) for i in range(1, 51)])
        dif, dea, macd = calc_macd(s)
        assert len(dif) == len(s)
        assert len(dea) == len(s)
        assert len(macd) == len(s)

    def test_macd_formula(self) -> None:
        """MACD = 2 * (DIF - DEA)"""
        s = pd.Series([float(i) for i in range(10, 60)])
        dif, dea, macd = calc_macd(s)
        for i in range(len(s)):
            expected = 2 * (dif.iloc[i] - dea.iloc[i])
            assert abs(macd.iloc[i] - expected) < 0.01


class TestCalcRsi:
    def test_returns_series(self) -> None:
        s = pd.Series([float(i) for i in range(1, 51)])
        rsi = calc_rsi(s, 14)
        assert isinstance(rsi, pd.Series)
        assert len(rsi) == len(s)

    def test_rsi_range(self) -> None:
        """RSI values should be between 0 and 100 (ignoring NaN)."""
        prices = pd.Series([10 + i * 0.5 + (i % 5) * 0.3 for i in range(50)])
        rsi = calc_rsi(prices, 14)
        valid = rsi.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()


class TestCalcKdj:
    def test_returns_three_series(self) -> None:
        close = pd.Series([float(i) for i in range(10, 60)])
        high = close + 2.0
        low = close - 2.0
        k, d, j = calc_kdj(high, low, close)
        assert len(k) == len(close)

    def test_kdj_formula(self) -> None:
        """J = 3*K - 2*D"""
        close = pd.Series([float(i) for i in range(10, 60)])
        high = close + 2.0
        low = close - 2.0
        k, d, j = calc_kdj(high, low, close)
        valid = k.dropna().index.intersection(d.dropna().index)
        for i in valid:
            assert abs(j.iloc[i] - (3 * k.iloc[i] - 2 * d.iloc[i])) < 0.01


class TestCalcBoll:
    def test_returns_three_series(self) -> None:
        close = pd.Series([float(i) for i in range(10, 60)])
        upper, mid, lower = calc_boll(close, period=5)
        assert len(upper) == len(close)

    def test_upper_above_mid(self) -> None:
        """Bollinger upper band should be >= middle band."""
        close = pd.Series([float(i) for i in range(10, 60)])
        upper, mid, lower = calc_boll(close, period=5)
        valid = upper.dropna().index.intersection(mid.dropna().index)
        for i in valid:
            assert upper.iloc[i] >= mid.iloc[i]

    def test_lower_below_mid(self) -> None:
        """Bollinger lower band should be <= middle band."""
        close = pd.Series([float(i) for i in range(10, 60)])
        upper, mid, lower = calc_boll(close, period=5)
        valid = lower.dropna().index.intersection(mid.dropna().index)
        for i in valid:
            assert lower.iloc[i] <= mid.iloc[i]


# ============================================================================
# File collection
# ============================================================================


class TestCollectFiles:
    def test_empty_dir(self, tmp_path: Path) -> None:
        from tdxdata import _collect_files

        result = _collect_files(tmp_path, None)
        assert result == []

    def test_finds_day_files(self, tmp_path: Path) -> None:
        from tdxdata import _collect_files

        (tmp_path / "sh600000.day").touch()
        (tmp_path / "sz000001.day").touch()
        (tmp_path / "readme.txt").touch()

        result = _collect_files(tmp_path, None)
        assert len(result) == 2

    def test_market_filter(self, tmp_path: Path) -> None:
        from tdxdata import _collect_files

        sh_dir = tmp_path / "sh"
        sz_dir = tmp_path / "sz"
        sh_dir.mkdir()
        sz_dir.mkdir()
        (sh_dir / "600000.day").touch()
        (sz_dir / "000001.day").touch()

        result = _collect_files(tmp_path, "sh")
        assert len(result) == 1
        assert result[0].name == "600000.day"
