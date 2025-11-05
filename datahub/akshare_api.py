"""
AkShare 适配模块。

该模块将常用的 AkShare 接口包装为统一的调用入口，负责：
- 延迟加载 AkShare，避免在未安装时直接报错；
- 对行情数据做字段重命名、类型转换与时区归一化；
- 对百分比、资金流等字段做容错转换；
- 为上层模块提供语义化的方法，避免重复编写列名匹配逻辑。
"""

from __future__ import annotations

import logging
from functools import lru_cache
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
from requests import exceptions as req_exc

logger = logging.getLogger(__name__)

_PROXY_DISABLED = False


class AkShareUnavailable(RuntimeError):
    """在未安装或加载失败时抛出的异常。"""


@lru_cache(maxsize=1)
def _load_akshare():
    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise AkShareUnavailable("AkShare 未安装，请先 pip install akshare。") from exc
    # 显式禁用 AkShare 使用的全局代理，避免受系统代理干扰。
    try:  # pragma: no cover - 属性兼容处理
        setattr(ak, "proxies", None)
    except Exception:
        pass
    try:
        setattr(ak, "request_proxies", None)
    except Exception:
        pass
    return ak


def is_available() -> bool:
    """返回当前环境是否可以使用 AkShare。"""
    try:
        _load_akshare()
        return True
    except AkShareUnavailable:
        return False


def _call(names: Sequence[str] | str, *args, **kwargs) -> Any:
    """
    依次尝试调用给定名称的 AkShare 函数。

    参数可以是字符串或字符串序列，方便做接口名称的兼容处理。
    """
    ak = _load_akshare()
    if isinstance(names, str):
        candidate_names = [names]
    else:
        candidate_names = list(names)

    last_error: Optional[Exception] = None
    for name in candidate_names:
        func = getattr(ak, name, None)
        if func is None:
            continue
        for attempt in range(1, 4):
            try:
                return func(*args, **kwargs)
            except (req_exc.ProxyError, req_exc.ConnectionError, req_exc.ReadTimeout) as exc:
                last_error = exc
                logger.warning(
                    "AkShare.%s 调用失败(%s/3): %s",
                    name,
                    attempt,
                    exc,
                )
                if attempt == 1 and _maybe_disable_proxy():
                    logger.info("检测到代理配置，已尝试禁用后再次请求。")
                    continue
                time.sleep(min(1.5 * attempt, 5))
                continue
            except Exception as exc:  # pragma: no cover - 外部接口报错
                last_error = exc
                logger.warning("AkShare.%s 调用失败: %s", name, exc)
                break
    if last_error:
        raise last_error
    raise AttributeError(f"AkShare 缺少接口：{candidate_names}")


def _maybe_disable_proxy() -> bool:
    """
    如果系统存在 HTTP(S)_PROXY 环境变量，尝试移除以避免无效代理导致的连接失败。
    """
    global _PROXY_DISABLED
    if _PROXY_DISABLED:
        return False
    keys = [
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "socks_proxy",
        "SOCKS_PROXY",
    ]
    removed = False
    for key in keys:
        if key in os.environ:
            os.environ.pop(key, None)
            removed = True
    # 确保 requests 明确不会走代理
    os.environ.setdefault("NO_PROXY", "*")
    if removed:
        _PROXY_DISABLED = True
        return True
    return False


def _normalize_ohlcv(
    df: Optional[pd.DataFrame],
    rename_map: Dict[str, str],
    tz: Optional[str],
) -> pd.DataFrame:
    """统一将行情数据转换为 UTC 时间索引的 OHLCV 结构。"""
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()
    # 某些接口返回多重索引，需要先扁平化
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [str(col[-1]) if isinstance(col, tuple) else str(col) for col in data.columns]

    available_map = {src: dst for src, dst in rename_map.items() if src in data.columns}
    if available_map:
        data.rename(columns=available_map, inplace=True)

    if "Datetime" not in data.columns:
        # 若 Datetime 不在列中，尝试从索引恢复
        index_name = str(data.index.name or "").lower()
        if index_name in {"date", "datetime", "日期", "交易日期"}:
            data = data.reset_index()
            data.rename(columns={data.columns[0]: "Datetime"}, inplace=True)
        else:
            possible_cols = [col for col in data.columns if str(col).lower() in {"date", "datetime", "日期"}]
            if possible_cols:
                data.rename(columns={possible_cols[0]: "Datetime"}, inplace=True)

    if "Datetime" not in data.columns:
        raise ValueError("行情数据缺少 Datetime 列，无法标准化。")

    data["Datetime"] = pd.to_datetime(data["Datetime"], errors="coerce")
    data = data.dropna(subset=["Datetime"])

    if data.empty:
        return pd.DataFrame()

    dt_series = data["Datetime"]
    if getattr(dt_series.dt, "tz", None) is None:
        target_tz = tz or "UTC"
        data["Datetime"] = dt_series.dt.tz_localize(
            target_tz,
            nonexistent="shift_forward",
            ambiguous="NaT",
        )
    if tz is not None:
        data["Datetime"] = data["Datetime"].dt.tz_convert("UTC")
    else:
        data["Datetime"] = data["Datetime"].dt.tz_convert("UTC")

    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in numeric_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")

    data = data.dropna(subset=["Datetime"])
    data = data.set_index("Datetime")
    data = data.loc[:, ~data.columns.duplicated()]
    data.sort_index(inplace=True)
    data = data[~data.index.duplicated(keep="last")]
    return data


def fetch_a_stock_daily(symbol: str, adjust: str = "") -> pd.DataFrame:
    return _normalize_ohlcv(
        _call("stock_zh_a_daily", symbol=symbol, adjust=adjust),
        rename_map={
            "date": "Datetime",
            "日期": "Datetime",
            "open": "Open",
            "开盘": "Open",
            "high": "High",
            "最高": "High",
            "low": "Low",
            "最低": "Low",
            "close": "Close",
            "收盘": "Close",
            "volume": "Volume",
            "成交量": "Volume",
        },
        tz="Asia/Shanghai",
    )


def fetch_a_stock_minute(symbol: str, period: str) -> pd.DataFrame:
    return _normalize_ohlcv(
        _call("stock_zh_a_minute", symbol=symbol, period=period),
        rename_map={
            "time": "Datetime",
            "day": "Datetime",
            "日期": "Datetime",
            "open": "Open",
            "开盘": "Open",
            "high": "High",
            "最高": "High",
            "low": "Low",
            "最低": "Low",
            "close": "Close",
            "收盘": "Close",
            "volume": "Volume",
            "成交量": "Volume",
        },
        tz="Asia/Shanghai",
    )


def fetch_us_stock_daily(symbol: str) -> pd.DataFrame:
    return _normalize_ohlcv(
        _call("stock_us_daily", symbol=symbol, adjust=""),
        rename_map={
            "日期": "Datetime",
            "date": "Datetime",
            "开盘": "Open",
            "open": "Open",
            "最高": "High",
            "high": "High",
            "最低": "Low",
            "low": "Low",
            "收盘": "Close",
            "close": "Close",
            "成交量": "Volume",
            "volume": "Volume",
        },
        tz="America/New_York",
    )


def fetch_cn_index_daily(symbol: str) -> pd.DataFrame:
    """
    使用 stock_zh_index_daily_em 获取指数日线。
    symbol 例如 sh000300、sz399006。
    """
    return _normalize_ohlcv(
        _call("stock_zh_index_daily_em", symbol=symbol),
        rename_map={
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
        },
        tz="Asia/Shanghai",
    )


def fetch_sector_fund_flow(period: str = "今日") -> pd.DataFrame:
    """
    行业资金流排行，默认 period=今日。
    返回字段统一命名：name, change_pct, main_net, super_net, large_net, medium_net, small_net。
    """
    df = _call("stock_sector_fund_flow_rank", period)
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()
    rename_map = {
        "行业名称": "name",
        "行业代码": "code",
        "板块名称": "name",
        "板块代码": "code",
        "今日涨跌幅": "change_pct",
        "涨跌幅": "change_pct",
        "今日主力净流入-净额": "main_net",
        "今日超大单净流入-净额": "super_net",
        "今日大单净流入-净额": "large_net",
        "今日中单净流入-净额": "medium_net",
        "今日小单净流入-净额": "small_net",
        "今日主力净流入-净占比": "main_ratio",
        "今日超大单净流入-净占比": "super_ratio",
    }
    available = {src: dst for src, dst in rename_map.items() if src in data.columns}
    if available:
        data.rename(columns=available, inplace=True)

    if "change_pct" in data.columns:
        data["change_pct"] = data["change_pct"].apply(_to_float)
    for col in ["main_net", "super_net", "large_net", "medium_net", "small_net", "main_ratio", "super_ratio"]:
        if col in data.columns:
            data[col] = data[col].apply(_to_float)

    return data


def fetch_sector_flow_detail(symbol: str) -> pd.DataFrame:
    """
    行业/概念龙头个股详情。
    返回字段：code, name, change_pct, main_net, main_ratio。
    """
    df = _call("stock_sector_fund_flow_rank_detail", symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    rename_map = {
        "股票代码": "code",
        "证券代码": "code",
        "股票简称": "name",
        "证券简称": "name",
        "涨跌幅": "change_pct",
        "今日主力净流入-净额": "main_net",
        "今日主力净流入-净占比": "main_ratio",
    }
    available = {src: dst for src, dst in rename_map.items() if src in data.columns}
    if available:
        data.rename(columns=available, inplace=True)
    if "change_pct" in data.columns:
        data["change_pct"] = data["change_pct"].apply(_to_float)
    for col in ["main_net", "main_ratio"]:
        if col in data.columns:
            data[col] = data[col].apply(_to_float)
    return data


def fetch_market_spot() -> pd.DataFrame:
    """
    返回 A 股实时行情快照，可用于统计涨跌家数。
    """
    df = _call("stock_zh_a_spot_em")
    return df.copy() if df is not None else pd.DataFrame()


def fetch_northbound_intraday(symbol: str = "北向资金") -> pd.DataFrame:
    """
    沪深港通分时资金数据。

    symbol 取值 “北向资金” / “南向资金”，单位为万元。
    """
    df = _call("stock_hsgt_fund_min_em", symbol=symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    return data


def fetch_lhb_summary(date: str) -> pd.DataFrame:
    """
    龙虎榜个股统计。
    date 形如 20240101。
    """
    df = _call("stock_lhb_ggtj_em", date)
    return df.copy() if df is not None else pd.DataFrame()


def fetch_stock_news(page: int = 1) -> pd.DataFrame:
    df = _call("stock_news_em", page)
    return df.copy() if df is not None else pd.DataFrame()


def _to_float(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("%", "").replace(",", "")
        if not text:
            return float("nan")
        try:
            return float(text)
        except ValueError:
            return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")
def fetch_hsgt_board_rank(symbol: str = "北向资金增持行业板块排行", indicator: str = "今日") -> pd.DataFrame:
    """
    北向资金增持板块排行数据。

    symbol: 行业/概念/地域排行
    indicator: 时间窗口，默认“今日”
    """
    df = _call("stock_hsgt_board_rank_em", symbol=symbol, indicator=indicator)
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()
