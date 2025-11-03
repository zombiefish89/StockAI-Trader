"""
宏观与板块数据抓取模块。

功能点：
- 指数快照：基于 yfinance 获取主要指数的行情变动。
- 板块排行：优先使用 AkShare，如不可用则返回空列表。
- 市场宽度：统计涨跌家数、涨停/跌停等，需 AkShare 支持。

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

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .akshare_api import (
    AkShareUnavailable,
    fetch_cn_index_daily,
    fetch_hsgt_board_rank,
    fetch_lhb_summary,
    fetch_market_spot,
    fetch_northbound_intraday,
    fetch_sector_flow_detail,
    fetch_sector_fund_flow,
    fetch_stock_news,
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


def _get_from_cache(cache: Dict[str, _CacheEntry], key: str, ttl: int) -> Optional[Any]:
    entry = cache.get(key)
    if entry and time.time() - entry.timestamp < ttl:
        return entry.payload
    return None


def _set_cache(cache: Dict[str, _CacheEntry], key: str, payload: Any) -> None:
    cache[key] = _CacheEntry(payload=payload, timestamp=time.time())


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
        source_label = "yfinance"
        try:
            df = await asyncio.to_thread(
                yf.download,
                code,
                period="5d",
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:  # pragma: no cover - 网络异常
            logger.warning("获取指数 %s 数据失败: %s", code, exc)
        if idx < len(mapping) - 1 and throttle_seconds > 0:
            await asyncio.sleep(throttle_seconds)

        if df is None or df.empty:
            df = await asyncio.to_thread(_fetch_index_from_akshare, name)
            if df is not None and not df.empty:
                source_label = "akshare"
        if (df is None or df.empty) and name in FINNHUB_INDEX_SYMBOLS:
            df = await asyncio.to_thread(
                _fetch_index_from_finnhub,
                FINNHUB_INDEX_SYMBOLS[name],
            )
            if df is not None and not df.empty:
                source_label = "finnhub"
        if (df is None or df.empty) and name in TUSHARE_INDEX_CODES:
            df = await asyncio.to_thread(
                _fetch_index_from_tushare,
                TUSHARE_INDEX_CODES[name],
            )
            if df is not None and not df.empty:
                source_label = "tushare"

        if df is None or df.empty:
            continue

        df = _prepare_index_dataframe(df)
        if df.empty or "Close" not in df.columns:
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
    """获取板块涨跌排名，当前支持 A 股（依赖 AkShare）。"""

    cache_key = f"{market}:{limit}"
    cached = _get_from_cache(_SECTOR_CACHE, cache_key, ttl_seconds)
    if cached is not None:
        return cached

    rankings: Dict[str, List[Dict[str, Any]]] = {"top": [], "bottom": []}

    if market == "cn":
        try:
            df = await asyncio.to_thread(fetch_sector_fund_flow, "今日")
        except AkShareUnavailable:
            logger.info("未安装 AkShare，无法获取 A 股板块排行。")
        except Exception as exc:  # pragma: no cover - 网络异常
            logger.warning("获取板块排行失败: %s", exc)
        else:
            if df is not None and not df.empty and "change_pct" in df.columns:
                data = df.copy()
                data["change_pct"] = pd.to_numeric(data["change_pct"], errors="coerce")
                data = data.dropna(subset=["change_pct"])
                if not data.empty:
                    top_records = (
                        data.sort_values(by="change_pct", ascending=False)
                        .head(limit)
                        .to_dict("records")
                    )
                    bottom_records = (
                        data.sort_values(by="change_pct", ascending=True)
                        .head(limit)
                        .to_dict("records")
                    )
                    rankings["top"] = await _build_sector_entries(top_records, top=True)
                    rankings["bottom"] = await _build_sector_entries(bottom_records, top=False)

        if not rankings["top"]:
            try:
                board_df = await asyncio.to_thread(
                    fetch_hsgt_board_rank,
                    "北向资金增持行业板块排行",
                    "今日",
                )
            except AkShareUnavailable:
                pass
            except Exception as exc:  # pragma: no cover
                logger.debug("北向板块排行获取失败: %s", exc)
            else:
                if board_df is not None and not board_df.empty:
                    data = board_df.copy()
                    name_col = _find_column(data.columns, ["名称"])
                    pct_col = _find_column(data.columns, ["最新涨跌幅"])
                    net_col = _find_column(data.columns, ["北向资金今日增持估计-市值"])
                    if name_col and (pct_col or net_col):
                        if pct_col:
                            data[pct_col] = pd.to_numeric(data[pct_col], errors="coerce")
                        if net_col:
                            data[net_col] = pd.to_numeric(data[net_col], errors="coerce")
                        data = data.dropna(subset=[name_col])
                        data_top = data.head(limit)
                        data_bottom = data.tail(limit)

                        def _convert_board(records: pd.DataFrame, reverse: bool) -> List[Dict[str, Any]]:
                            items: List[Dict[str, Any]] = []
                            sorted_df = records
                            if pct_col:
                                sorted_df = sorted_df.sort_values(by=pct_col, ascending=reverse)
                            for _, row in sorted_df.iterrows():
                                name = row.get(name_col)
                                if not name:
                                    continue
                                change_value = row.get(pct_col)
                                net_value = row.get(net_col)
                                net_converted = (
                                    float(net_value) if isinstance(net_value, (int, float)) else _as_float(net_value)
                                )
                                if net_converted is not None:
                                    net_converted = net_converted  # 单位为元，无需转换
                                items.append(
                                    {
                                        "name": name,
                                        "change_pct": float(change_value) if isinstance(change_value, (int, float)) else (_as_float(change_value) or 0.0),
                                        "fund_flow": net_converted,
                                        "leaders": [],
                                    }
                                )
                            return items

                        rankings["top"] = _convert_board(data_top, reverse=False)
                        rankings["bottom"] = _convert_board(data_bottom, reverse=True)

    _set_cache(_SECTOR_CACHE, cache_key, rankings)
    return rankings


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

    try:
        df = await asyncio.to_thread(fetch_market_spot)
    except AkShareUnavailable:
        logger.info("未安装 AkShare，市场宽度指标缺失。")
    except Exception as exc:  # pragma: no cover
        logger.warning("获取市场宽度失败: %s", exc)
        if _BREADTH_CACHE:
            logger.info("宽度获取失败，使用缓存数据。")
            return _BREADTH_CACHE.payload
    else:
        if df is not None and not df.empty:
            data = df.copy()
            change_col = _find_column(data.columns, ["涨跌幅", "涨幅", "change"])
            if change_col:
                change_series = pd.to_numeric(data[change_col], errors="coerce")
                breadth["advance"] = int((change_series > 0).sum())
                breadth["decline"] = int((change_series < 0).sum())
                breadth["limit_up"] = int((change_series >= 9.8).sum())
                breadth["limit_down"] = int((change_series <= -9.8).sum())

    _BREADTH_CACHE = _CacheEntry(payload=breadth, timestamp=time.time())
    return breadth


async def get_macro_snapshot() -> Dict[str, Any]:
    """聚合宏观指数、板块与市场宽度为一体的概览。"""

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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "indices": indices,
        "sectors": sectors,
        "breadth": breadth,
        "sentiment": sentiment,
        "lhb": lhb,
        "news": news,
    }


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


async def _build_sector_entries(
    records: List[Dict[str, Any]],
    *,
    top: bool,
    leader_limit: int = 3,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for record in records:
        entry = await _build_sector_entry(record, top=top, leader_limit=leader_limit)
        if entry:
            items.append(entry)
    return items


async def _build_sector_entry(
    record: Dict[str, Any],
    *,
    top: bool,
    leader_limit: int,
) -> Optional[Dict[str, Any]]:
    name = record.get("name") or record.get("code")
    if not name:
        return None

    change = _safe_round(record.get("change_pct"))
    fund_flow = _safe_round(record.get("main_net"), digits=2)
    leaders = await _load_sector_leaders(str(name), top=top, limit=leader_limit)

    item: Dict[str, Any] = {
        "name": str(name),
        "change_pct": change if change is not None else 0.0,
        "fund_flow": fund_flow,
        "leaders": leaders,
    }
    code = record.get("code")
    if code:
        item["code"] = code
    return item


async def _load_sector_leaders(name: str, top: bool, limit: int) -> List[Dict[str, Any]]:
    try:
        df = await asyncio.to_thread(fetch_sector_flow_detail, name)
    except AkShareUnavailable:
        return []
    except Exception as exc:  # pragma: no cover - 第三方接口异常
        logger.debug("获取板块龙头失败 %s: %s", name, exc)
        return []

    if df is None or df.empty:
        return []

    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = ["_".join(str(part) for part in col if part) for col in data.columns]

    if "change_pct" in data.columns:
        data["change_pct"] = pd.to_numeric(data["change_pct"], errors="coerce")
        data = data.dropna(subset=["change_pct"])
        data = data.sort_values(by="change_pct", ascending=not top)

    records = data.head(limit).to_dict("records")
    leaders: List[Dict[str, Any]] = []
    for record in records:
        leaders.append(
            {
                "code": record.get("code"),
                "name": record.get("name"),
                "change_pct": _safe_round(record.get("change_pct")),
                "main_net": _safe_round(record.get("main_net"), digits=2),
                "main_ratio": _safe_round(record.get("main_ratio")),
            }
        )
    return leaders


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

    try:
        df = await asyncio.to_thread(fetch_northbound_intraday, "北向资金")
    except AkShareUnavailable:
        logger.info("未安装 AkShare，北向资金缺失。")
        _NORTHBOUND_CACHE = _CacheEntry(payload=None, timestamp=time.time())
        return None
    except Exception as exc:  # pragma: no cover
        logger.warning("获取北向资金数据失败: %s", exc)
    else:
        if df is not None and not df.empty:
            data = df.copy()
            north_col = _find_column(data.columns, ["北向资金"])
            if north_col is None:
                north_col = _find_column(data.columns, ["净流入", "资金"])
            if north_col is not None:
                series = pd.to_numeric(data[north_col], errors="coerce").dropna()
                if not series.empty:
                    # 转换为人民币，原始数值单位为万元
                    value = float(series.iloc[-1]) * 1e4
                    _NORTHBOUND_CACHE = _CacheEntry(payload=value, timestamp=time.time())
                    return value

    _NORTHBOUND_CACHE = _CacheEntry(payload=None, timestamp=time.time())
    return None


async def _get_lhb_summary(ttl_seconds: int = 3600, limit: int = 5) -> List[Dict[str, Any]]:
    global _LHB_CACHE
    if _LHB_CACHE and time.time() - _LHB_CACHE.timestamp < ttl_seconds:
        return _LHB_CACHE.payload

    data: List[Dict[str, Any]] = []
    for offset in range(5):  # 尝试最近五个交易日
        date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = await asyncio.to_thread(fetch_lhb_summary, date)
        except AkShareUnavailable:
            _LHB_CACHE = _CacheEntry(payload=[], timestamp=time.time())
            return []
        except Exception:
            continue
        if df is not None and not df.empty:
            df = df.copy()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ["_".join(str(part) for part in col if part) for col in df.columns]
            code_col = _find_column(df.columns, ["代码"])
            name_col = _find_column(df.columns, ["简称", "名称"])
            net_col = _find_column(df.columns, ["净买额", "净买入"])
            buy_col = _find_column(df.columns, ["买入金额"])
            sell_col = _find_column(df.columns, ["卖出金额"])
            times_col = _find_column(df.columns, ["上榜次数"])
            change_col = _find_column(df.columns, ["涨跌幅"])

            sort_col = net_col or times_col
            if sort_col:
                df[sort_col] = pd.to_numeric(df[sort_col], errors="coerce")
                df = df.dropna(subset=[sort_col])
                df = df.sort_values(by=sort_col, ascending=False)

            rows = df.head(limit).to_dict("records")
            for row in rows:
                data.append(
                    {
                        "code": row.get(code_col),
                        "name": row.get(name_col),
                        "net_buy": _as_float(row.get(net_col)),
                        "buy_value": _as_float(row.get(buy_col)),
                        "sell_value": _as_float(row.get(sell_col)),
                        "times": int(_as_float(row.get(times_col)) or 0) if times_col else None,
                        "change_pct": _safe_round(row.get(change_col)),
                        "date": date,
                    }
                )
            break

    if not data and _LHB_CACHE:
        data = _LHB_CACHE.payload

    _LHB_CACHE = _CacheEntry(payload=data, timestamp=time.time())
    return data


async def _get_news_highlights(ttl_seconds: int = 1800, limit: int = 5) -> List[Dict[str, Any]]:
    global _NEWS_CACHE
    if _NEWS_CACHE and time.time() - _NEWS_CACHE.timestamp < ttl_seconds:
        return _NEWS_CACHE.payload

    news_list: List[Dict[str, Any]] = []
    try:
        df = await asyncio.to_thread(fetch_stock_news, 1)
    except AkShareUnavailable:
        _NEWS_CACHE = _CacheEntry(payload=[], timestamp=time.time())
        return []
    except Exception as exc:  # pragma: no cover
        logger.warning("获取新闻失败: %s", exc)
    else:
        if df is not None and not df.empty:
            data = df.head(limit).copy()
            for _, row in data.iterrows():
                title = row.get("title") or row.get("新闻标题") or row.get("标题")
                if not title:
                    continue
                news_list.append(
                    {
                        "title": title,
                        "summary": row.get("summary") or row.get("digest") or row.get("内容摘要") or row.get("摘要"),
                        "time": row.get("datetime") or row.get("time") or row.get("publish_time") or row.get("发布时间"),
                        "source": row.get("source") or row.get("媒体") or row.get("来源"),
                        "url": row.get("url") or row.get("链接"),
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
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        return None
    try:
        import tushare as ts  # type: ignore
    except ImportError:
        logger.info("未安装 tushare，无法使用备援。")
        return None

    ts.set_token(token)
    pro = ts.pro_api()
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - pd.Timedelta(days=20)).strftime("%Y%m%d")
        df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    except Exception as exc:  # pragma: no cover
        logger.warning("Tushare 指数 %s 拉取失败: %s", ts_code, exc)
        return None

    if df is None or df.empty:
        return None

    df = df.copy()
    df.rename(
        columns={
            "trade_date": "Datetime",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
        },
        inplace=True,
    )
    df["Datetime"] = pd.to_datetime(df["Datetime"], format="%Y%m%d", utc=True)
    df.set_index("Datetime", inplace=True)
    df.sort_index(inplace=True)
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return df
