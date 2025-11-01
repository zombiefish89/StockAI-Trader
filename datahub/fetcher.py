"""
Market data fetchers with local caching and freshness validation.

The module wraps yfinance download calls inside asyncio-friendly helpers so
that API handlers can await results without blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pandas as pd
from pandas import Series
import yfinance as yf

from .cache import DataCache

logger = logging.getLogger(__name__)

INTERVAL_TTL = {
    "1m": 60 * 3,
    "5m": 60 * 10,
    "15m": 60 * 20,
    "1h": 60 * 60,
    "1d": 60 * 60 * 6,
}


def _select_cache(interval: str) -> DataCache:
    ttl = INTERVAL_TTL.get(interval, 60 * 60 * 24)
    return DataCache(base_dir="cache", ttl_seconds=ttl)


def _ensure_datetime(value: Optional[str | datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _needs_refresh(
    df: Optional[pd.DataFrame],
    interval: str,
    end: Optional[datetime],
) -> bool:
    if df is None or df.empty:
        return True
    last_idx = df.index[-1]
    if not isinstance(last_idx, datetime):
        logger.debug("Cached dataframe index is not datetime; refreshing.")
        return True
    now = datetime.now(timezone.utc)
    expected_delta = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
    }.get(interval, timedelta(days=1))

    tolerance = expected_delta * 2

    if end is not None and last_idx >= end - expected_delta:
        return False
    if now - last_idx > tolerance:
        return True
    return False


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    normalized = df.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = [str(col[0]).title() for col in normalized.columns]
    else:
        normalized.columns = [str(col).title() for col in normalized.columns]
    tz = getattr(normalized.index, "tz", None)
    if tz is None:
        normalized.index = normalized.index.tz_localize(
            timezone.utc, nonexistent="shift_forward", ambiguous="NaT"
        )
    else:
        normalized.index = normalized.index.tz_convert(timezone.utc)
    normalized.sort_index(inplace=True)
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    return normalized


async def get_latest_candles(
    ticker: str,
    start: Optional[datetime | str] = None,
    end: Optional[datetime | str] = None,
    interval: str = "1d",
    use_cache: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch OHLCV candles for a ticker, merging cache with remote data."""

    interval = interval or "1d"
    cache = _select_cache(interval)
    start_ts = _ensure_datetime(start)
    end_ts = _ensure_datetime(end)

    cached_df: Optional[pd.DataFrame] = None
    if use_cache and not force_refresh:
        cached_df = cache.load(ticker, interval)
        if cached_df is not None:
            cached_df = _normalize_dataframe(cached_df)

    should_refresh = force_refresh or _needs_refresh(cached_df, interval, end_ts)

    if should_refresh:
        fresh_df = await asyncio.to_thread(
            _download_candles,
            ticker,
            start_ts,
            end_ts,
            interval,
        )
        fresh_df = _normalize_dataframe(fresh_df)
        if cached_df is not None and not cached_df.empty:
            combined = pd.concat([cached_df, fresh_df])
            unique_df = combined[~combined.index.duplicated(keep="last")]
            cache.store(ticker, interval, unique_df)
            df = unique_df
        else:
            cache.store(ticker, interval, fresh_df)
            df = fresh_df
    else:
        df = cached_df if cached_df is not None else pd.DataFrame()

    if df.empty:
        return df

    if start_ts:
        df = df[df.index >= start_ts]
    if end_ts:
        df = df[df.index <= end_ts]
    return df


def _download_candles(
    ticker: str,
    start: Optional[datetime],
    end: Optional[datetime],
    interval: str,
) -> pd.DataFrame:
    logger.info("Downloading %s candles for %s", interval, ticker)
    kwargs: Dict[str, Any] = {
        "interval": interval,
        "auto_adjust": False,
        "progress": False,
        "threads": False,
    }
    if start:
        kwargs["start"] = start
    if end:
        kwargs["end"] = end
    df = yf.download(ticker, **kwargs)
    if df is None:
        return pd.DataFrame()
    return df


async def get_quote_summary(ticker: str) -> Dict[str, Any]:
    """Fetch basic quote/fundamental data with simple caching."""
    now = datetime.now(timezone.utc)
    cached = _QUOTE_CACHE.get(ticker)
    if cached and now - cached["timestamp"] < timedelta(minutes=15):
        return cached["payload"]
    info = await asyncio.to_thread(_download_quote_summary, ticker)
    _QUOTE_CACHE[ticker] = {"timestamp": now, "payload": info}
    return info


def _download_quote_summary(ticker: str) -> Dict[str, Any]:
    ticker_obj = yf.Ticker(ticker)
    info = _sanitize_payload(ticker_obj.info or {})
    fast_info = getattr(ticker_obj, "fast_info", None)
    if fast_info is not None:
        price = _sanitize_payload(getattr(fast_info, "__dict__", {}))
    else:
        price = {}
    return {
        "info": info,
        "fast": price,
    }


_QUOTE_CACHE: Dict[str, Dict[str, Any]] = {}


def _sanitize_payload(value: Any) -> Any:
    """Convert nested structures into JSON-serializable payloads."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            sanitized[str(key)] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, Series):
        return _sanitize_payload(value.to_dict())
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)
