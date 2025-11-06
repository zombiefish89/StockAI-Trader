"""
行情数据抓取模块，封装本地缓存与新鲜度校验。

通过将 yfinance 调用包裹为兼容 asyncio 的结构，
使得 API 处理流程在等待网络时不会阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Sequence

import pandas as pd
from pandas import Series
import yfinance as yf

from .cache import DataCache
from .providers import (
    CandleProvider,
    ProviderError,
    YFinanceProvider,
    default_providers,
)
from infra.cache_store import cache_manager
from infra.rate_limit import rate_limiter
from .tushare_api import (
    TushareUnavailable,
    get_pro,
    get_latest_trade_date,
    to_ts_code,
)

logger = logging.getLogger(__name__)

INTERVAL_TTL = {
    "1m": 60,
    "5m": 60 * 3,
    "15m": 60 * 10,
    "1h": 60 * 45,
    "1d": 60 * 60 * 6,
}

PROVIDER_TTL_OVERRIDES: Dict[str, Dict[str, int]] = {
    "akshare": {
        "1m": 45,
        "5m": 60 * 2,
        "15m": 60 * 10,
        "30m": 60 * 15,
        "1h": 60 * 30,
    },
    "akshare_us": {
        "1d": 60 * 60 * 6,
    },
}


def _select_cache(interval: str, provider: str) -> DataCache:
    base_ttl = INTERVAL_TTL.get(interval, 60 * 60 * 24)
    provider_ttl = PROVIDER_TTL_OVERRIDES.get(provider, {}).get(interval, base_ttl)
    return DataCache(base_dir="cache", ttl_seconds=provider_ttl)


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
    providers: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """获取股票的 OHLCV 数据，并合并本地缓存及多提供方数据。"""

    interval = interval or "1d"
    start_ts = _ensure_datetime(start)
    end_ts = _ensure_datetime(end)

    provider_sequence = _resolve_providers(ticker, interval, providers)
    last_error: Optional[Exception] = None

    for provider in provider_sequence:
        cache = _select_cache(interval, provider.name)
        cached_df: Optional[pd.DataFrame] = None

        if use_cache:
            if not force_refresh:
                hot_df = cache_manager.load_dataframe(provider.name, ticker, interval)
                if hot_df is not None:
                    hot_df = _normalize_dataframe(hot_df)
                    if not _needs_refresh(hot_df, interval, end_ts):
                        clipped = _clip_dataframe(hot_df, start_ts, end_ts)
                        clipped.attrs["source"] = provider.name
                        return clipped
                    cached_df = hot_df

            disk_df = cache.load(ticker, interval, provider=provider.name)
            if disk_df is not None:
                disk_df = _normalize_dataframe(disk_df)
                cached_df = disk_df
                ttl_seconds = cache_manager.ttl_for_interval(interval)
                cache_manager.store_dataframe(
                    provider.name,
                    ticker,
                    interval,
                    disk_df,
                    ttl=ttl_seconds,
                )
                if not force_refresh and not _needs_refresh(disk_df, interval, end_ts):
                    clipped = _clip_dataframe(disk_df, start_ts, end_ts)
                    clipped.attrs["source"] = provider.name
                    return clipped

        try:
            async with rate_limiter.limit(provider.name, symbol=ticker):
                fresh_df = await asyncio.to_thread(
                    provider.fetch_candles,
                    ticker,
                    start_ts,
                    end_ts,
                    interval,
                )
            fresh_df = _normalize_dataframe(fresh_df)
        except ProviderError as exc:
            logger.warning("数据源 %s 返回错误：%s", provider.name, exc)
            last_error = exc
            if cached_df is not None and not cached_df.empty:
                logger.info("使用 %s 的缓存数据作为降级。", provider.name)
                clipped = _clip_dataframe(cached_df, start_ts, end_ts)
                clipped.attrs["source"] = provider.name
                return clipped
            continue
        except Exception as exc:  # pragma: no cover - 网络错误等
            logger.exception("数据源 %s 异常：%s", provider.name, exc)
            last_error = exc
            if cached_df is not None and not cached_df.empty:
                clipped = _clip_dataframe(cached_df, start_ts, end_ts)
                clipped.attrs["source"] = provider.name
                return clipped
            continue

        df = fresh_df.copy()
        df = df.loc[:, ~df.columns.duplicated()]
        df = df.sort_index()
        df = df.loc[~df.index.duplicated(keep="last")]
        if cached_df is not None and not cached_df.empty:
            cached_df = cached_df.loc[~cached_df.index.duplicated(keep="last")]
            try:
                combined = pd.concat([cached_df, df], axis=0, join="outer", sort=True)
            except ValueError:
                cached_df = cached_df.loc[:, ~cached_df.columns.duplicated()]
                combined = pd.concat([cached_df, df], axis=0, join="outer", sort=True)
            combined = combined.loc[:, ~combined.columns.duplicated()]
            combined.sort_index(inplace=True)
            df = combined.groupby(level=0).last()

        if df.empty:
            continue

        cache.store(ticker, interval, df, provider=provider.name)
        cache_manager.store_dataframe(
            provider.name,
            ticker,
            interval,
            df,
            ttl=cache_manager.ttl_for_interval(interval),
        )
        clipped = _clip_dataframe(df, start_ts, end_ts)
        clipped.attrs["source"] = provider.name
        return clipped

    if last_error:
        logger.error("所有数据源均不可用：%s", last_error)
    return pd.DataFrame()


async def get_candles_batch(
    tickers: Sequence[str],
    start: Optional[datetime | str] = None,
    end: Optional[datetime | str] = None,
    interval: str = "1d",
    use_cache: bool = True,
    force_refresh: bool = False,
    providers: Optional[Sequence[str]] = None,
    concurrency: int = 4,
) -> Dict[str, pd.DataFrame]:
    """批量获取多只股票的行情数据。"""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    tasks = []
    results: Dict[str, pd.DataFrame] = {}

    async def _worker(symbol: str) -> None:
        async with semaphore:
            df = await get_latest_candles(
                ticker=symbol,
                start=start,
                end=end,
                interval=interval,
                use_cache=use_cache,
                force_refresh=force_refresh,
                providers=providers,
            )
            results[symbol] = df

    for ticker in tickers:
        tasks.append(asyncio.create_task(_worker(ticker)))

    if tasks:
        await asyncio.gather(*tasks)
    return results


async def get_quote_summary(ticker: str) -> Dict[str, Any]:
    """拉取基础报价 / 财报信息，并做轻量缓存。"""
    now = datetime.now(timezone.utc)
    cached = _QUOTE_CACHE.get(ticker)
    if cached and now - cached["timestamp"] < timedelta(minutes=15):
        return cached["payload"]
    info = await asyncio.to_thread(_download_quote_summary, ticker)
    _QUOTE_CACHE[ticker] = {"timestamp": now, "payload": info}
    return info


def _download_quote_summary(ticker: str) -> Dict[str, Any]:
    if _is_china_equity(ticker):
        cn_payload = _download_quote_summary_cn(ticker)
        if cn_payload:
            return cn_payload

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


def _download_quote_summary_cn(ticker: str) -> Dict[str, Any]:
    try:
        pro = get_pro()
    except TushareUnavailable as exc:
        logger.debug("Tushare 不可用，使用 yfinance 作为 Quote 数据源：%s", exc)
        return {}

    ts_code = to_ts_code(ticker)
    info: Dict[str, Any] = {}
    fast: Dict[str, Any] = {}

    try:
        basic_df = pro.stock_basic(ts_code=ts_code, fields="ts_code,name,industry,list_date,market,exchange")
        if basic_df is not None and not basic_df.empty:
            row = basic_df.iloc[0]
            info.update(
                {
                    "ts_code": row.get("ts_code"),
                    "name": row.get("name"),
                    "industry": row.get("industry"),
                    "list_date": row.get("list_date"),
                    "market": row.get("market"),
                    "exchange": row.get("exchange"),
                }
            )
    except Exception as exc:  # pragma: no cover
        logger.debug("Tushare stock_basic 查询失败：%s", exc)

    trade_date = get_latest_trade_date()

    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    try:
        fields = "ts_code,trade_date,close,turnover_rate,turnover_rate_f,pe_ttm,pb,ps_ttm,total_mv,circ_mv"
        daily_basic = None
        if trade_date:
            daily_basic = pro.daily_basic(ts_code=ts_code, trade_date=trade_date, fields=fields)
        if daily_basic is None or daily_basic.empty:
            daily_basic = pro.daily_basic(ts_code=ts_code, limit=1, fields=fields)
        if daily_basic is not None and not daily_basic.empty:
            row = daily_basic.iloc[0]
            info.update(
                {
                    "pe_ttm": _to_float(row.get("pe_ttm")),
                    "pb": _to_float(row.get("pb")),
                    "ps_ttm": _to_float(row.get("ps_ttm")),
                    "total_mv": _to_float(row.get("total_mv")),
                    "circ_mv": _to_float(row.get("circ_mv")),
                }
            )
            fast.update(
                {
                    "close": _to_float(row.get("close")),
                    "turnover_rate": _to_float(row.get("turnover_rate")),
                    "turnover_rate_free": _to_float(row.get("turnover_rate_f")),
                    "trade_date": row.get("trade_date"),
                }
            )
    except Exception as exc:  # pragma: no cover
        logger.debug("Tushare daily_basic 查询失败：%s", exc)

    try:
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        daily_df = None
        if trade_date:
            daily_df = pro.daily(ts_code=ts_code, start_date=trade_date, end_date=trade_date, fields=fields)
        if daily_df is None or daily_df.empty:
            daily_df = pro.daily(ts_code=ts_code, limit=1, fields=fields)
        if daily_df is not None and not daily_df.empty:
            row = daily_df.iloc[0]
            fast.update(
                {
                    "open": _to_float(row.get("open")),
                    "high": _to_float(row.get("high")),
                    "low": _to_float(row.get("low")),
                    "close": _to_float(row.get("close")),
                    "pre_close": _to_float(row.get("pre_close")),
                    "change": _to_float(row.get("change")),
                    "pct_chg": _to_float(row.get("pct_chg")),
                    "volume": _to_float(row.get("vol")),
                    "amount": _to_float(row.get("amount")),
                    "trade_date": fast.get("trade_date") or row.get("trade_date"),
                }
            )
    except Exception as exc:  # pragma: no cover
        logger.debug("Tushare daily 查询失败：%s", exc)

    if not info and not fast:
        return {}
    return {
        "info": _sanitize_payload(info),
        "fast": _sanitize_payload(fast),
    }


_QUOTE_CACHE: Dict[str, Dict[str, Any]] = {}


def _sanitize_payload(value: Any) -> Any:
    """将复杂数据转换为可 JSON 序列化的基础类型。"""
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


def _clip_dataframe(
    df: pd.DataFrame,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
) -> pd.DataFrame:
    """根据起止时间截取数据。"""
    clipped = df
    if start_ts:
        clipped = clipped[clipped.index >= start_ts]
    if end_ts:
        clipped = clipped[clipped.index <= end_ts]
    return clipped


def _is_china_equity(ticker: str) -> bool:
    """判断是否为 A 股代码。"""
    symbol = ticker.strip().lower()
    if symbol.startswith(("sh", "sz", "bj")):
        return True
    if "." in symbol:
        base, suffix = symbol.split(".", 1)
        suffix = suffix.lower()
        if suffix in {"ss", "sh", "sz", "bj"}:
            return True
        if suffix == "cn":
            return True
        if suffix == "szse":
            return True
    if len(symbol) == 6 and symbol.isdigit():
        return True
    return False


def _is_us_equity(ticker: str) -> bool:
    """粗略判断是否为美股代码。"""
    symbol = ticker.strip().upper()
    if _is_china_equity(symbol):
        return False
    if symbol.endswith(('.HK', '.SS', '.SZ', '.BJ')):
        return False
    if symbol.isalpha() and 1 <= len(symbol) <= 5:
        return True
    if "." in symbol:
        suffix = symbol.split(".")[-1]
        if suffix in {"O", "N", "A", "K", "Q"}:
            return True
    return False


def _env_provider_list(*env_names: str) -> list[str]:
    providers: list[str] = []
    for name in env_names:
        value = os.getenv(name)
        if value:
            providers.append(value.strip().lower())
    return [p for p in providers if p]


@lru_cache(maxsize=1)
def _provider_registry() -> Dict[str, CandleProvider]:
    """缓存默认提供方实例，避免重复初始化。"""
    providers = list(default_providers())
    registry: Dict[str, CandleProvider] = {}
    for provider in providers:
        registry[provider.name] = provider
    return registry


def _resolve_providers(
    ticker: str,
    interval: str,
    requested: Optional[Sequence[str]],
) -> Sequence[CandleProvider]:
    """按优先级返回可用的数据源实例列表。"""
    registry = _provider_registry()
    ordered: list[CandleProvider] = []

    def _maybe_add(provider: CandleProvider) -> None:
        if provider.supports(interval) and provider not in ordered:
            ordered.append(provider)

    if requested:
        for name in requested:
            provider = registry.get(name)
            if provider is None:
                logger.warning("未识别的数据源：%s", name)
                continue
            _maybe_add(provider)
    else:
        ticker_upper = ticker.upper()
        if _is_china_equity(ticker):
            preferred = _env_provider_list("A_STOCK_PRIMARY", "A_STOCK_SECONDARY")
            fallback = ["tushare", "akshare", "yfinance", "akshare_us"]
        elif ticker_upper.endswith(".HK"):
            preferred = _env_provider_list("HK_STOCK_PRIMARY", "HK_STOCK_SECONDARY")
            fallback = ["yfinance", "akshare", "akshare_us", "tushare"]
        elif _is_us_equity(ticker):
            preferred = _env_provider_list("US_STOCK_PRIMARY", "US_STOCK_SECONDARY")
            fallback = ["yfinance", "akshare_us", "akshare", "tushare"]
        else:
            preferred = []
            fallback = ["yfinance", "akshare", "akshare_us", "tushare"]

        if not preferred:
            preferred = fallback

        for name in preferred:
            provider = registry.get(name)
            if provider:
                _maybe_add(provider)
            else:
                logger.debug("环境变量指定的数据源未注册：%s", name)
        for provider in registry.values():
            _maybe_add(provider)

    if not ordered:
        logger.info("无可用数据源，使用 yfinance 作为后备。")
        ordered.append(YFinanceProvider())

    return ordered
