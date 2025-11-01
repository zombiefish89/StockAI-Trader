"""
File-based caching utilities for market data.

The MVP caches pandas DataFrames as Parquet when pyarrow is available,
falling back to CSV when it is not. Each cache entry is scoped by ticker
and timeframe and validated against a configurable TTL window.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class DataCache:
    """Simple filesystem cache for tabular market data."""

    def __init__(self, base_dir: Path | str = "cache", ttl_seconds: int = 60 * 60 * 24):
        self.base_dir = Path(base_dir)
        self.ttl_seconds = ttl_seconds
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _base_path(self, ticker: str, timeframe: str) -> Path:
        safe_ticker = ticker.replace("/", "_").upper()
        return self.base_dir / timeframe / safe_ticker

    def _primary_path(self, ticker: str, timeframe: str) -> Path:
        return self._base_path(ticker, timeframe).with_suffix(".parquet")

    def _fallback_path(self, ticker: str, timeframe: str) -> Path:
        return self._base_path(ticker, timeframe).with_suffix(".csv")

    def _metadata_path(self, ticker: str, timeframe: str) -> Path:
        return self._base_path(ticker, timeframe).with_suffix(".meta")

    def load(self, ticker: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Load cached data if present and fresh."""
        path = self._primary_path(ticker, timeframe)
        csv_path = self._fallback_path(ticker, timeframe)
        if not path.exists() and not csv_path.exists():
            return None
        if self.is_stale(ticker, timeframe):
            return None

        if path.exists():
            return self._read_dataframe(path)
        return self._read_dataframe(csv_path)

    def store(self, ticker: str, timeframe: str, df: pd.DataFrame) -> None:
        """Persist DataFrame to disk and write metadata timestamp."""
        if df.empty:
            logger.debug("Skip caching empty dataframe for %s %s", ticker, timeframe)
            return

        parquet_path = self._primary_path(ticker, timeframe)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        wrote = self._write_dataframe(parquet_path, df)
        if not wrote:
            csv_path = self._fallback_path(ticker, timeframe)
            df.to_csv(csv_path)

        metadata_path = self._metadata_path(ticker, timeframe)
        metadata_path.write_text(str(int(time.time())), encoding="utf-8")

    def is_stale(self, ticker: str, timeframe: str) -> bool:
        """Return True when the cached entry is missing or past TTL."""
        metadata_path = self._metadata_path(ticker, timeframe)
        if not metadata_path.exists():
            return True
        try:
            cached_at = int(metadata_path.read_text(encoding="utf-8"))
        except ValueError:
            logger.warning("Invalid cache metadata for %s %s", ticker, timeframe)
            return True
        age = time.time() - cached_at
        return age >= self.ttl_seconds

    def clear(self, ticker: str, timeframe: str) -> None:
        """Remove cached data and metadata for the given key."""
        metadata_path = self._metadata_path(ticker, timeframe)
        path = self._primary_path(ticker, timeframe)
        for target in (path, metadata_path):
            if target.exists():
                target.unlink()
        csv_path = self._fallback_path(ticker, timeframe)
        if csv_path.exists():
            csv_path.unlink()

    @staticmethod
    def _read_dataframe(path: Path) -> pd.DataFrame:
        if path.suffix == ".parquet":
            try:
                return pd.read_parquet(path)
            except Exception as exc:  # pragma: no cover - rare path
                logger.warning("Failed to read parquet cache %s: %s", path, exc)
        if path.suffix == ".csv" and path.exists():
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise FileNotFoundError(path)

    @staticmethod
    def _write_dataframe(path: Path, df: pd.DataFrame) -> bool:
        try:
            df.to_parquet(path)
            return True
        except Exception as exc:  # pragma: no cover - pyarrow missing
            logger.debug("Parquet write failed for %s: %s; falling back to CSV", path, exc)
            return False

