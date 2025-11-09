"""
宏观与板块数据抓取模块。

功能点：
- 指数快照：优先使用 Tushare / yfinance 获取主要指数的行情变动。
- 板块排行：基于 Tushare 的行业归类统计。
- 市场宽度：统计涨跌家数、涨停/跌停等。

所有接口均为异步，内部通过 asyncio.to_thread 调用同步库，
默认带有 TTL 缓存以减少外部 API 请求频率。
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from copy import deepcopy

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from infra.cache_store import cache_manager

from .akshare_api import AkShareUnavailable, fetch_northbound_intraday
from .tushare_api import (
    TushareUnavailable,
    compute_industry_rankings,
    fetch_daily,
    fetch_moneyflow_hsgt,
    fetch_news as fetch_tushare_news,
    fetch_stock_basic,
    fetch_top_inst,
    fetch_top_list,
    fetch_index_daily as ts_fetch_index_daily,
    get_latest_trade_date,
    get_pro,
    select_leaders,
)

logger = logging.getLogger(__name__)


# 默认关注的全球主要指数（逻辑名称 -> yfinance 代码）
DEFAULT_INDICES: Dict[str, str] = {
    "sh000300": "000300.SS",  # 沪深300
    "sz399006": "399006.SZ",  # 创业板指
    "sp500": "^GSPC",  # 标普500
    "nasdaq": "^IXIC",  # 纳斯达克
    "dowjones": "^DJI",
    "hsci": "^HSI",  # 恒生指数
}


AK_INDEX_FALLBACKS: Dict[str, Dict[str, str]] = {
    "sh000300": {"method": "stock_zh_index_daily_em", "symbol": "sh000300"},
    "sz399006": {"method": "stock_zh_index_daily_em", "symbol": "sz399006"},
}

FINNHUB_INDEX_SYMBOLS: Dict[str, str] = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dowjones": "^DJI",
    "hsci": "^HSI",
}

TUSHARE_INDEX_CODES: Dict[str, str] = {
    "sh000300": "000300.SH",
    "sz399006": "399006.SZ",
}

GLOBAL_TUSHARE_CODES: Dict[str, str] = {
    "sp500": "SP500",
    "nasdaq": "IXIC",
    "dowjones": "DJI",
    "hsci": "HSI",
}


@dataclass
class _CacheEntry:
    payload: Any
    timestamp: float


_INDEX_CACHE: Dict[str, _CacheEntry] = {}
_SECTOR_CACHE: Dict[str, _CacheEntry] = {}
_BREADTH_CACHE: Optional[_CacheEntry] = None
_NORTHBOUND_CACHE: Optional[_CacheEntry] = None
_LHB_CACHE: Optional[_CacheEntry] = None
_NEWS_CACHE: Optional[_CacheEntry] = None
_DAILY_CACHE: Dict[str, _CacheEntry] = {}
_STOCK_BASIC_CACHE: Optional[_CacheEntry] = None
_MACRO_CACHE: Optional[_CacheEntry] = None

def _macro_cache_key() -> str:
    return "macro::snapshot"

MACRO_SNAPSHOT_TTL = int(os.getenv("MACRO_SNAPSHOT_TTL", "7200"))


def _get_from_cache(cache: Dict[str, _CacheEntry], key: str, ttl: int) -> Optional[Any]:
    entry = cache.get(key)
    if entry and time.time() - entry.timestamp < ttl:
        return entry.payload
    return None


def _set_cache(cache: Dict[str, _CacheEntry], key: str, payload: Any) -> None:
    cache[key] = _CacheEntry(payload=payload, timestamp=time.time())


def _get_daily_snapshot(trade_date: str, ttl_seconds: int = 600) -> Optional[pd.DataFrame]:
    entry = _DAILY_CACHE.get(trade_date)
    if entry and time.time() - entry.timestamp < ttl_seconds:
        return entry.payload.copy()
    try:
        df = fetch_daily(trade_date)
    except TushareUnavailable as exc:
        logger.warning("Tushare daily 数据不可用：%s", exc)
        return None
    if df is None or df.empty:
        return None
    payload = df.copy()
    _DAILY_CACHE[trade_date] = _CacheEntry(payload=payload, timestamp=time.time())
    return payload


def _get_stock_basic(ttl_seconds: int = 6 * 3600) -> Optional[pd.DataFrame]:
    global _STOCK_BASIC_CACHE
    if _STOCK_BASIC_CACHE and time.time() - _STOCK_BASIC_CACHE.timestamp < ttl_seconds:
        payload = _STOCK_BASIC_CACHE.payload
        return payload.copy() if isinstance(payload, pd.DataFrame) else payload
    try:
        df = fetch_stock_basic(fields="ts_code,name,industry")
    except TushareUnavailable as exc:
        logger.warning("Tushare stock_basic 不可用：%s", exc)
        return None
    if df is None or df.empty:
        return None
    payload = df.copy()
    _STOCK_BASIC_CACHE = _CacheEntry(payload=payload, timestamp=time.time())
    return payload


def _prepare_index_dataframe(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = [str(col[-1]) if isinstance(col, tuple) else str(col) for col in result.columns]

    rename_map = {
        "adj close": "Close",
        "close": "Close",
        "收盘": "Close",
        "收盘价": "Close",
        "open": "Open",
        "开盘": "Open",
        "high": "High",
        "最高": "High",
        "low": "Low",
        "最低": "Low",
        "volume": "Volume",
        "成交量": "Volume",
    }

    new_columns: Dict[str, str] = {}
    for col in result.columns:
        key = str(col).lower().strip()
        new_columns[col] = rename_map.get(key, str(col))
    result.rename(columns=new_columns, inplace=True)

    result = result.loc[:, ~result.columns.duplicated()]
    result.dropna(how="all", inplace=True)
    return result


async def get_index_snapshot(
    symbols: Optional[Dict[str, str]] = None,
    ttl_seconds: int = 1800,
    throttle_seconds: float = 1.5,
) -> Dict[str, Dict[str, float]]:
    """获取主要指数的价格、涨跌幅及成交量变化。"""

    mapping = symbols or DEFAULT_INDICES
    cache_key = "|".join(sorted(mapping.keys()))
    cached = _get_from_cache(_INDEX_CACHE, cache_key, ttl_seconds)
    if cached is not None:
        return cached

    snapshot: Dict[str, Dict[str, float]] = {}
    backup = cached  # 失败时使用旧数据

    for idx, (name, code) in enumerate(mapping.items()):
        df: Optional[pd.DataFrame] = None
        source_label = ""

        if name in TUSHARE_INDEX_CODES:
            df = await asyncio.to_thread(
                _fetch_index_from_tushare,
                TUSHARE_INDEX_CODES[name],
            )
            if df is not None and not df.empty:
                source_label = "tushare"

        if (df is None or df.empty) and name in GLOBAL_TUSHARE_CODES:
            df = await asyncio.to_thread(
                _fetch_global_index_from_tushare,
                GLOBAL_TUSHARE_CODES[name],
            )
            if df is not None and not df.empty:
                source_label = "tushare_global"

        if (df is None or df.empty) and code:
            try:
                df = await asyncio.to_thread(
                    yf.download,
                    code,
                    period="5d",
                    progress=False,
                    auto_adjust=False,
                )
                if df is not None and not df.empty:
                    source_label = "yfinance"
            except Exception as exc:  # pragma: no cover - 网络异常
                logger.warning("获取指数 %s 数据失败: %s", code, exc)

        if (df is None or df.empty) and name in FINNHUB_INDEX_SYMBOLS:
            df = await asyncio.to_thread(
                _fetch_index_from_finnhub,
                FINNHUB_INDEX_SYMBOLS[name],
            )
            if df is not None and not df.empty:
                source_label = "finnhub"

        if (df is None or df.empty) and name in ("sh000300", "sz399006"):
            df = await asyncio.to_thread(_fetch_index_from_akshare, name)
            if df is not None and not df.empty:
                source_label = "akshare"

        if df is None or df.empty:
            if idx < len(mapping) - 1 and throttle_seconds > 0:
                await asyncio.sleep(throttle_seconds)
            continue

        df = _prepare_index_dataframe(df)
        if df.empty or "Close" not in df.columns:
            if idx < len(mapping) - 1 and throttle_seconds > 0:
                await asyncio.sleep(throttle_seconds)
            continue

        df = df.tail(2).copy()
        close_obj = df["Close"]
        if isinstance(close_obj, pd.DataFrame):
            close_obj = close_obj.iloc[:, 0]
        close_series = pd.to_numeric(close_obj, errors="coerce")
        close_arr = close_series.to_numpy()
        close = float(close_arr[-1]) if close_arr.size else float("nan")
        prev_close = float(close_arr[-2]) if close_arr.size > 1 else float("nan")
        change_pct = float(((close - prev_close) / prev_close) * 100) if np.isfinite(prev_close) and prev_close not in (0, float("nan")) else 0.0

        if "Volume" in df.columns:
            volume_obj = df["Volume"]
            if isinstance(volume_obj, pd.DataFrame):
                volume_obj = volume_obj.iloc[:, 0]
            volume_series = pd.to_numeric(volume_obj, errors="coerce")
            volume_arr = volume_series.to_numpy()
        else:
            volume_arr = np.array([])
        volume = float(volume_arr[-1]) if volume_arr.size else float("nan")
        prev_volume = float(volume_arr[-2]) if volume_arr.size > 1 else float("nan")
        volume_change_pct = (
            float(((volume - prev_volume) / prev_volume) * 100)
            if np.isfinite(volume) and np.isfinite(prev_volume) and prev_volume != 0
            else 0.0
        )
        snapshot[name] = {
            "symbol": code,
            "close": round(close, 3),
            "change_pct": round(change_pct, 3),
            "volume": volume if np.isfinite(volume) else None,
            "volume_change_pct": round(volume_change_pct, 3),
            "source": source_label,
        }
        if idx < len(mapping) - 1 and throttle_seconds > 0:
            await asyncio.sleep(throttle_seconds)

    if snapshot:
        _set_cache(_INDEX_CACHE, cache_key, snapshot)
        return snapshot

    if backup:
        logger.info("指数抓取失败，回退至缓存数据。")
        _set_cache(_INDEX_CACHE, cache_key, backup)
        return backup

    return {}


async def get_sector_rankings(
    market: str = "cn",
    limit: int = 5,
    ttl_seconds: int = 1800,
) -> Dict[str, List[Dict[str, Any]]]:
    """获取板块涨跌排名，当前支持 A 股（依赖 Tushare）。"""

    cache_key = f"{market}:{limit}"
    cached = _get_from_cache(_SECTOR_CACHE, cache_key, ttl_seconds)
    if cached is not None:
        return cached

    rankings: Dict[str, List[Dict[str, Any]]] = {"top": [], "bottom": []}

    if market == "cn":
        trade_date = await asyncio.to_thread(get_latest_trade_date)
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")
        daily_df = await asyncio.to_thread(_get_daily_snapshot, trade_date)
        stock_basic = await asyncio.to_thread(_get_stock_basic)
        if daily_df is not None and stock_basic is not None:
            top_df, bottom_df = compute_industry_rankings(daily_df, stock_basic, top_n=limit)
            rankings["top"] = _convert_industry_rows(top_df, daily_df, stock_basic, top=True)
            rankings["bottom"] = _convert_industry_rows(bottom_df, daily_df, stock_basic, top=False)

    _set_cache(_SECTOR_CACHE, cache_key, rankings)
    return rankings


def _convert_industry_rows(
    rows: Optional[pd.DataFrame],
    daily_df: Optional[pd.DataFrame],
    stock_basic: Optional[pd.DataFrame],
    *,
    top: bool,
    leader_limit: int = 3,
) -> List[Dict[str, Any]]:
    if rows is None or rows.empty:
        return []
    if daily_df is None or daily_df.empty or stock_basic is None or stock_basic.empty:
        payload = []
        for _, row in rows.iterrows():
            name = row.get("industry")
            change = _safe_round(row.get("change_pct"))
            amount = _safe_round(row.get("amount"), digits=6)
            payload.append(
                {
                    "name": name,
                    "change_pct": change or 0.0,
                    "fund_flow": (amount * 1e3) if amount is not None else None,
                    "leaders": [],
                }
            )
        return payload

    items: List[Dict[str, Any]] = []
    for _, row in rows.iterrows():
        industry = row.get("industry")
        if not industry:
            continue
        change = _safe_round(row.get("change_pct")) or 0.0
        amount = _safe_round(row.get("amount"), digits=6)
        leaders_df = select_leaders(
            industry,
            daily_df,
            stock_basic,
            ascending=not top,
            limit=leader_limit,
        )
        leaders: List[Dict[str, Any]] = []
        if leaders_df is not None and not leaders_df.empty:
            for _, leader in leaders_df.iterrows():
                leaders.append(
                    {
                        "code": leader.get("ts_code"),
                        "name": leader.get("name"),
                        "change_pct": _safe_round(leader.get("pct_chg")),
                    }
                )
        items.append(
            {
                "name": industry,
                "change_pct": change,
                "fund_flow": (amount * 1e3) if amount is not None else None,
                "leaders": leaders,
            }
        )
    return items


async def get_market_breadth(
    ttl_seconds: int = 900,
) -> Dict[str, Any]:
    """统计市场宽度信息（涨跌家数、涨停跌停等）。"""

    global _BREADTH_CACHE
    if _BREADTH_CACHE and time.time() - _BREADTH_CACHE.timestamp < ttl_seconds:
        return _BREADTH_CACHE.payload

    breadth = {
        "advance": None,
        "decline": None,
        "limit_up": None,
        "limit_down": None,
    }

    trade_date = await asyncio.to_thread(get_latest_trade_date)
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    daily_df = await asyncio.to_thread(_get_daily_snapshot, trade_date)
    if (daily_df is None or daily_df.empty) and trade_date:
        # 尝试回退上一交易日
        prev_trade_date = await asyncio.to_thread(get_latest_trade_date, 1)
        if prev_trade_date:
            daily_df = await asyncio.to_thread(_get_daily_snapshot, prev_trade_date)

    if daily_df is not None and not daily_df.empty:
        pct_series = pd.to_numeric(daily_df.get("pct_chg"), errors="coerce")
        breadth["advance"] = int((pct_series > 0).sum())
        breadth["decline"] = int((pct_series < 0).sum())
        breadth["limit_up"] = int((pct_series >= 9.7).sum())
        breadth["limit_down"] = int((pct_series <= -9.7).sum())
    else:
        logger.info("未从 Tushare 获取到有效的日行情数据，市场宽度为空。")

    _BREADTH_CACHE = _CacheEntry(payload=breadth, timestamp=time.time())
    return breadth


async def get_macro_snapshot() -> Dict[str, Any]:
    """聚合宏观指数、板块与市场宽度为一体的概览。"""

    global _MACRO_CACHE
    if _MACRO_CACHE and time.time() - _MACRO_CACHE.timestamp < MACRO_SNAPSHOT_TTL:
        cached = _MACRO_CACHE.payload
        if isinstance(cached, dict):
            return deepcopy(cached)
        return cached
    redis_cached = cache_manager.load_json(_macro_cache_key())
    if redis_cached is not None:
        _MACRO_CACHE = _CacheEntry(payload=deepcopy(redis_cached), timestamp=time.time())
        return redis_cached

    indices, sectors, breadth, northbound, lhb, news = await asyncio.gather(
        get_index_snapshot(),
        get_sector_rankings(),
        get_market_breadth(),
        _get_northbound_flow(),
        _get_lhb_summary(),
        _get_news_highlights(),
    )

    sentiment = {
        "northbound_net": northbound,
    }
    adv = breadth.get("advance") if isinstance(breadth, dict) else None
    decl = breadth.get("decline") if isinstance(breadth, dict) else None
    if isinstance(adv, int) and isinstance(decl, int) and decl > 0:
        sentiment["advance_decline_ratio"] = round(adv / decl, 3)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "indices": indices,
        "sectors": sectors,
        "breadth": breadth,
        "sentiment": sentiment,
        "lhb": lhb,
        "news": news,
    }
    payload = deepcopy(result)
    _MACRO_CACHE = _CacheEntry(payload=payload, timestamp=time.time())
    cache_manager.store_json(_macro_cache_key(), payload, MACRO_SNAPSHOT_TTL)
    return result


def _fetch_index_from_akshare(name: str) -> Optional[pd.DataFrame]:
    fallback = AK_INDEX_FALLBACKS.get(name)
    if fallback is None:
        return None

    symbol = fallback.get("symbol")
    if not symbol:
        return None

    try:
        return fetch_cn_index_daily(symbol)
    except AkShareUnavailable:
        logger.info("未安装 AkShare，无法使用指数备援。")
    except Exception as exc:  # pragma: no cover
        logger.warning("AkShare 指数 %s 拉取失败: %s", symbol, exc)
    return None


def _fetch_global_index_from_tushare(code: str) -> Optional[pd.DataFrame]:
    try:
        pro = get_pro()
    except TushareUnavailable:
        return None
    try:
        df = pro.index_global(ts_code=code, limit=200)
    except Exception as exc:  # pragma: no cover - 网络异常
        logger.warning("Tushare index_global %s 拉取失败: %s", code, exc)
        return None
    if df is None or df.empty:
        return None
    data = df.copy()
    if "trade_date" not in data.columns:
        return None
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.dropna(subset=["trade_date"])
    if data.empty:
        return None
    data = data.sort_values("trade_date")
    data = data.set_index("trade_date")
    rename_map = {
        "close": "Close",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "vol": "Volume",
        "volume": "Volume",
    }
    available = {k: v for k, v in rename_map.items() if k in data.columns}
    if available:
        data = data.rename(columns=available)
    return data


def _find_column(columns: Iterable[Any], keywords: Sequence[str]) -> Optional[Any]:
    for col in columns:
        label = str(col)
        if any(keyword in label for keyword in keywords):
            return col
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        text = str(value).strip().replace("%", "").replace(",", "")
        if not text:
            return None
        try:
            num = float(text)
        except ValueError:
            return None
    if not math.isfinite(num):
        return None
    return num


def _safe_round(value: Any, digits: int = 3) -> Optional[float]:
    num = _as_float(value)
    if num is None:
        return None
    return round(num, digits)


async def _get_northbound_flow(ttl_seconds: int = 1800) -> Optional[float]:
    global _NORTHBOUND_CACHE
    if _NORTHBOUND_CACHE and time.time() - _NORTHBOUND_CACHE.timestamp < ttl_seconds:
        return _NORTHBOUND_CACHE.payload

    trade_date = await asyncio.to_thread(get_latest_trade_date)
    if trade_date:
        try:
            df = await asyncio.to_thread(fetch_moneyflow_hsgt, trade_date)
        except TushareUnavailable as exc:
            logger.info("Tushare 北向资金不可用：%s", exc)
        except Exception as exc:  # pragma: no cover
            logger.warning("获取北向资金数据失败: %s", exc)
        else:
            if df is not None and not df.empty:
                df = df.copy()
                if "north_money" in df.columns:
                    north_series = pd.to_numeric(df["north_money"], errors="coerce").dropna()
                    if not north_series.empty:
                        # north_money 单位：亿元
                        value = float(north_series.iloc[-1]) * 1e8
                        _NORTHBOUND_CACHE = _CacheEntry(payload=value, timestamp=time.time())
                        return value

    try:
        df = await asyncio.to_thread(fetch_northbound_intraday, "北向资金")
    except AkShareUnavailable:
        logger.info("未安装 AkShare，北向资金缺失。")
    except Exception as exc:  # pragma: no cover
        logger.warning("获取北向资金分时失败: %s", exc)
    else:
        if df is not None and not df.empty:
            data = df.copy()
            north_col = _find_column(data.columns, ["北向资金"])
            if north_col is None:
                north_col = _find_column(data.columns, ["净流入", "资金"])
            if north_col is not None:
                series = pd.to_numeric(data[north_col], errors="coerce").dropna()
                if not series.empty:
                    value = float(series.iloc[-1]) * 1e4
                    _NORTHBOUND_CACHE = _CacheEntry(payload=value, timestamp=time.time())
                    return value

    _NORTHBOUND_CACHE = _CacheEntry(payload=None, timestamp=time.time())
    return None


async def _get_lhb_summary(ttl_seconds: int = 3600, limit: int = 5) -> List[Dict[str, Any]]:
    global _LHB_CACHE
    if _LHB_CACHE and time.time() - _LHB_CACHE.timestamp < ttl_seconds:
        return _LHB_CACHE.payload

    trade_date = await asyncio.to_thread(get_latest_trade_date)
    candidates: List[Dict[str, Any]] = []

    if trade_date:
        for offset in range(5):
            date_obj = datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=offset)
            date = date_obj.strftime("%Y%m%d")
            try:
                df = await asyncio.to_thread(fetch_top_inst, date)
                if (df is None or df.empty) and offset == 0:
                    df = await asyncio.to_thread(fetch_top_list, date)
            except TushareUnavailable as exc:
                logger.info("Tushare 龙虎榜不可用：%s", exc)
                break
            except Exception:
                continue

            if df is None or df.empty:
                continue

            data = df.copy()
            net_col = _find_column(data.columns, ["net_buy", "净买"])
            buy_col = _find_column(data.columns, ["buy", "买入"])
            sell_col = _find_column(data.columns, ["sell", "卖出"])
            ts_col = _find_column(data.columns, ["ts_code", "代码"])
            name_col = _find_column(data.columns, ["name", "名称"])

            if net_col:
                data[net_col] = pd.to_numeric(data[net_col], errors="coerce")
                data = data.dropna(subset=[net_col])
                data = data.sort_values(by=net_col, ascending=False)

            for _, row in data.head(limit).iterrows():
                net_value = _as_float(row.get(net_col))
                buy_value = _as_float(row.get(buy_col))
                sell_value = _as_float(row.get(sell_col))
                candidates.append(
                    {
                        "code": row.get(ts_col),
                        "name": row.get(name_col),
                        "net_buy": (net_value * 1e4) if net_value is not None else None,
                        "buy_value": (buy_value * 1e4) if buy_value is not None else None,
                        "sell_value": (sell_value * 1e4) if sell_value is not None else None,
                        "date": date,
                    }
                )
            if candidates:
                break

    if not candidates and _LHB_CACHE:
        candidates = _LHB_CACHE.payload

    _LHB_CACHE = _CacheEntry(payload=candidates, timestamp=time.time())
    return candidates


async def _get_news_highlights(ttl_seconds: int = 1800, limit: int = 5) -> List[Dict[str, Any]]:
    global _NEWS_CACHE
    if _NEWS_CACHE and time.time() - _NEWS_CACHE.timestamp < ttl_seconds:
        return _NEWS_CACHE.payload

    news_list: List[Dict[str, Any]] = []
    trade_date = await asyncio.to_thread(get_latest_trade_date)
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    try:
        df = await asyncio.to_thread(fetch_tushare_news, trade_date, trade_date)
        if (df is None or df.empty) and trade_date:
            # 补充当天滚动新闻
            df = await asyncio.to_thread(fetch_tushare_news, trade_date, datetime.now().strftime("%Y%m%d"))
    except TushareUnavailable as exc:
        logger.info("Tushare 新闻接口不可用：%s", exc)
        df = None
    except Exception as exc:  # pragma: no cover
        logger.warning("获取新闻失败: %s", exc)
        df = None

    if df is not None and not df.empty:
        data = df.head(limit).copy()
        for _, row in data.iterrows():
            title = row.get("title")
            if not title:
                continue
            news_list.append(
                {
                    "title": title,
                    "summary": row.get("summary") or row.get("abstract") or row.get("content"),
                    "time": row.get("datetime") or row.get("time") or row.get("pub_time"),
                    "source": row.get("source") or row.get("media"),
                    "url": row.get("url"),
                }
            )

    if not news_list and _NEWS_CACHE:
        news_list = _NEWS_CACHE.payload

    _NEWS_CACHE = _CacheEntry(payload=news_list, timestamp=time.time())
    return news_list


def _fetch_index_from_finnhub(symbol: str) -> Optional[pd.DataFrame]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key or requests is None:
        return None

    end_ts = int(time.time())
    start_ts = end_ts - 3600 * 24 * 10
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/index/candle",
            params={
                "symbol": symbol,
                "resolution": "D",
                "from": start_ts,
                "to": end_ts,
                "token": api_key,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Finnhub 指数请求失败 %s: %s", symbol, resp.text)
            return None
        data = resp.json()
    except Exception as exc:  # pragma: no cover
        logger.warning("Finnhub 指数请求异常 %s: %s", symbol, exc)
        return None

    if data.get("s") != "ok":
        return None

    timestamps = data.get("t", [])
    if not timestamps:
        return None

    df = pd.DataFrame(
        {
            "Datetime": pd.to_datetime(timestamps, unit="s", utc=True),
            "Open": data.get("o", []),
            "High": data.get("h", []),
            "Low": data.get("l", []),
            "Close": data.get("c", []),
            "Volume": data.get("v", []),
        }
    )
    df.set_index("Datetime", inplace=True)
    df.sort_index(inplace=True)
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df = df.loc[:, ~df.columns.duplicated()]
    return df.tail(10)


def _fetch_index_from_tushare(ts_code: str) -> Optional[pd.DataFrame]:
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - pd.Timedelta(days=20)).strftime("%Y%m%d")
        df = ts_fetch_index_daily(ts_code, start_date, end_date)
    except TushareUnavailable:
        return None
    except Exception as exc:  # pragma: no cover
        logger.warning("Tushare 指数 %s 拉取失败: %s", ts_code, exc)
        return None
    if df is None or df.empty:
        return None
    data = df.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index)
    try:
        data.index = data.index.tz_localize("Asia/Shanghai", nonexistent="shift_forward", ambiguous="NaT").tz_convert("UTC")
    except TypeError:
        data.index = data.index.tz_convert("UTC")
    data = data.loc[:, ~data.columns.duplicated()]
    return data.tail(20)
