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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

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


@dataclass
class _CacheEntry:
    payload: Any
    timestamp: float


_INDEX_CACHE: Dict[str, _CacheEntry] = {}
_SECTOR_CACHE: Dict[str, _CacheEntry] = {}
_BREADTH_CACHE: Optional[_CacheEntry] = None


def _get_from_cache(cache: Dict[str, _CacheEntry], key: str, ttl: int) -> Optional[Any]:
    entry = cache.get(key)
    if entry and time.time() - entry.timestamp < ttl:
        return entry.payload
    return None


def _set_cache(cache: Dict[str, _CacheEntry], key: str, payload: Any) -> None:
    cache[key] = _CacheEntry(payload=payload, timestamp=time.time())


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
            if df is None or df.empty:
                continue
        df = df.tail(2)
        close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2]) if len(df) > 1 else float("nan")
        change_pct = float(((close - prev_close) / prev_close) * 100) if np.isfinite(prev_close) else 0.0
        volume = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else float("nan")
        prev_volume = float(df["Volume"].iloc[-2]) if "Volume" in df.columns and len(df) > 1 else float("nan")
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
            import akshare as ak  # type: ignore

            df = await asyncio.to_thread(ak.stock_sector_fund_flow_rank, "今日")
            if df is not None and not df.empty:
                df = df.copy()
                name_col = None
                change_col = None
                flow_col = None
                for col in df.columns:
                    if change_col is None and "涨跌幅" in col:
                        change_col = col
                    if flow_col is None and "主力净流入" in col:
                        flow_col = col
                    if name_col is None and ("名称" in col or "板块" in col):
                        name_col = col

                if change_col is None:
                    logger.warning("板块数据缺少涨跌幅列，放弃处理。列：%s", df.columns.tolist())
                else:
                    df[change_col] = pd.to_numeric(df[change_col], errors="coerce")
                    df = df.dropna(subset=[change_col])
                    df = df.sort_values(by=change_col, ascending=False)
                    top = df.head(limit)
                    bottom = df.tail(limit)
                    rankings["top"] = [
                        {
                            "name": row.get(name_col) or row.get("行业名称") or row.get("板块名称"),
                            "change_pct": round(float(row.get(change_col, 0.0)), 3),
                            "fund_flow": float(row.get(flow_col, 0.0)) if flow_col else None,
                        }
                        for _, row in top.iterrows()
                        if (row.get(name_col) or row.get("行业名称"))
                    ]
                    rankings["bottom"] = [
                        {
                            "name": row.get(name_col) or row.get("行业名称") or row.get("板块名称"),
                            "change_pct": round(float(row.get(change_col, 0.0)), 3),
                            "fund_flow": float(row.get(flow_col, 0.0)) if flow_col else None,
                        }
                        for _, row in bottom.iterrows()
                        if (row.get(name_col) or row.get("行业名称"))
                    ]
        except ImportError:
            logger.info("未安装 akshare，无法获取 A 股板块排行。")
        except Exception as exc:  # pragma: no cover - 网络异常
            logger.warning("获取板块排行失败: %s", exc)

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
        import akshare as ak  # type: ignore

        df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        if df is not None and not df.empty:
            df = df.copy()
            change_col = next((c for c in df.columns if "涨跌幅" in c), None)
            if change_col:
                change_series = pd.to_numeric(df[change_col], errors="coerce")
                breadth["advance"] = int((change_series > 0).sum())
                breadth["decline"] = int((change_series < 0).sum())
            limit_col = change_col or "涨跌幅"
            if limit_col in df.columns:
                series = pd.to_numeric(df[limit_col], errors="coerce")
                breadth["limit_up"] = int((series >= 9.9).sum())
                breadth["limit_down"] = int((series <= -9.9).sum())
    except ImportError:
        logger.info("未安装 akshare，市场宽度指标缺失。")
    except Exception as exc:  # pragma: no cover
        logger.warning("获取市场宽度失败: %s", exc)
        if _BREADTH_CACHE:
            logger.info("宽度获取失败，使用缓存数据。")
            return _BREADTH_CACHE.payload

    _BREADTH_CACHE = _CacheEntry(payload=breadth, timestamp=time.time())
    return breadth


async def get_macro_snapshot() -> Dict[str, Any]:
    """聚合宏观指数、板块与市场宽度为一体的概览。"""

    indices, sectors, breadth = await asyncio.gather(
        get_index_snapshot(),
        get_sector_rankings(),
        get_market_breadth(),
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "indices": indices,
        "sectors": sectors,
        "breadth": breadth,
    }


def _fetch_index_from_akshare(name: str) -> Optional[pd.DataFrame]:
    fallback = AK_INDEX_FALLBACKS.get(name)
    if fallback is None:
        return None
    try:
        import akshare as ak  # type: ignore
    except ImportError:
        return None

    method = fallback.get("method")
    symbol = fallback.get("symbol")
    try:
        fetch_func = getattr(ak, method)
    except AttributeError:
        logger.warning("AkShare 不存在方法 %s", method)
        return None

    try:
        df = fetch_func(symbol=symbol)
    except TypeError:
        # 有的函数参数名不同，例如 stock_zh_index_daily_em(symbol="")
        try:
            df = fetch_func(symbol)
        except Exception as exc:  # pragma: no cover - akshare 调用异常
            logger.warning("AkShare 指数 %s 拉取失败: %s", symbol, exc)
            return None
    except Exception as exc:  # pragma: no cover - akshare 调用异常
        logger.warning("AkShare 指数 %s 拉取失败: %s", symbol, exc)
        return None

    if df is None or df.empty:
        return None

    df = df.copy()
    col_map = {
        "日期": "Datetime",
        "date": "Datetime",
        "收盘": "Close",
        "close": "Close",
        "开盘": "Open",
        "open": "Open",
        "最高": "High",
        "high": "High",
        "最低": "Low",
        "low": "Low",
        "成交量": "Volume",
        "volume": "Volume",
    }
    for src, dst in col_map.items():
        if src in df.columns:
            df.rename(columns={src: dst}, inplace=True)

    if "Datetime" not in df.columns or "Close" not in df.columns:
        logger.warning("AkShare 指数缺少必要列：%s", df.columns.tolist())
        return None

    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df.dropna(subset=["Datetime"])
    df.set_index("Datetime", inplace=True)
    if df.empty:
        return None

    # 默认按沪深时区本地化
    if df.index.tz is None:
        df.index = df.index.tz_localize("Asia/Shanghai", nonexistent="shift_forward", ambiguous="NaT")
    df.index = df.index.tz_convert("UTC")

    numeric_cols = [col for col in ["Open", "High", "Low", "Close", "Volume"] if col in df.columns]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return df
