"""
Tushare Pro 接口适配工具。

封装常用查询（行情、行业、资金流、龙虎榜等），统一处理 token 与字段转换，
供行情 provider 与宏观模块复用。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from threading import Lock
from typing import Iterable, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class TushareUnavailable(RuntimeError):
    """在未配置或初始化失败时抛出的异常。"""


_TOKEN_POOL: Optional[List[str]] = None
_TOKEN_INDEX = 0
_ACTIVE_CLIENT: Optional[Tuple["ts", "pro"]] = None  # type: ignore[name-defined]
_TOKEN_LOCK = Lock()
_RATE_LIMIT_KEYWORDS = (
    "最多访问",
    "频率",
    "超出",
    "limit",
    "too many",
    "rate",
    "800",
)


def _mask_token(token: str) -> str:
    if len(token) <= 6:
        return "***"
    return f"{token[:3]}***{token[-3:]}"


def _load_token_pool() -> List[str]:
    global _TOKEN_POOL
    if _TOKEN_POOL is not None:
        return _TOKEN_POOL

    pool_raw = os.getenv("TUSHARE_TOKEN_POOL", "")
    tokens: List[str] = []
    if pool_raw:
        tokens.extend(part.strip() for part in pool_raw.split(",") if part.strip())
    single = os.getenv("TUSHARE_TOKEN")
    if single:
        tokens.append(single.strip())

    seen = set()
    deduped: List[str] = []
    for item in tokens:
        if item and item not in seen:
            deduped.append(item)
            seen.add(item)
    _TOKEN_POOL = deduped
    return _TOKEN_POOL


def _init_client(token: str) -> Tuple["ts", "pro"]:  # type: ignore[name-defined]
    try:
        import tushare as ts  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise TushareUnavailable("缺少 tushare 库，请安装后再启用。") from exc

    ts.set_token(token)
    pro = ts.pro_api(token)
    return ts, pro


def _rotate_token(reason: str | None = None) -> bool:
    tokens = _load_token_pool()
    if len(tokens) <= 1:
        return False
    global _TOKEN_INDEX, _ACTIVE_CLIENT
    with _TOKEN_LOCK:
        _TOKEN_INDEX = (_TOKEN_INDEX + 1) % len(tokens)
        _ACTIVE_CLIENT = None
    if reason:
        logger.warning("Tushare token 切换：%s", reason)
    return True


def _load_client() -> Tuple["ts", "pro"]:  # type: ignore[name-defined]
    global _ACTIVE_CLIENT
    if _ACTIVE_CLIENT is not None:
        return _ACTIVE_CLIENT

    tokens = _load_token_pool()
    if not tokens:
        raise TushareUnavailable("未配置 TUSHARE_TOKEN 或 TUSHARE_TOKEN_POOL，无法使用 Tushare 接口。")

    last_error: Optional[Exception] = None
    attempts = len(tokens)
    for _ in range(attempts):
        token = tokens[_TOKEN_INDEX]
        try:
            client = _init_client(token)
            _ACTIVE_CLIENT = client
            logger.info("Tushare token 已就绪：%s", _mask_token(token))
            return client
        except Exception as exc:
            last_error = exc
            logger.warning("Tushare token 初始化失败（%s）：%s", _mask_token(token), exc)
            if not _rotate_token(str(exc)):
                break
    raise TushareUnavailable("所有 Tushare token 初始化失败，请检查配置。") from last_error


def _should_rotate(message: str) -> bool:
    normalized = message.lower()
    for keyword in _RATE_LIMIT_KEYWORDS:
        if keyword.isascii():
            if keyword in normalized:
                return True
        elif keyword in message:
            return True
    return False


def _handle_tushare_error(exc: Exception, context: str) -> None:
    message = str(exc)
    logger.warning("%s：%s", context, message)
    if _should_rotate(message):
        rotated = _rotate_token(message)
        if rotated:
            logger.info("检测到 Tushare 限流，已切换到下一个 token。")


def get_ts() -> "ts":  # type: ignore[name-defined]
    ts, _ = _load_client()
    return ts


def get_pro() -> "pro":  # type: ignore[name-defined]
    _, pro = _load_client()
    return pro


def to_ts_code(symbol: str) -> str:
    """将各类 A 股代码（600519.SS、SH600519、600519）转换为 Tushare 格式。"""
    raw = symbol.strip().upper()
    if raw.endswith(".SZ") or raw.endswith(".SS") or raw.endswith(".SH"):
        base, suffix = raw.split(".", 1)
        if suffix in {"SS"}:
            suffix = "SH"
        return f"{base}.{suffix}"
    if raw.startswith(("SH", "SZ")) and len(raw) >= 8:
        return f"{raw[-6:]}.{raw[:2]}"
    if raw.isdigit() and len(raw) == 6:
        prefix = raw[0]
        if prefix in {"0", "2", "3"}:
            return f"{raw}.SZ"
        if prefix in {"6", "9"}:
            return f"{raw}.SH"
        if prefix in {"4", "8"}:
            return f"{raw}.BJ"
    return raw


def _to_trade_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime("%Y%m%d")


def _parse_datetime(value: str) -> datetime:
    if " " in value:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return datetime.strptime(value, "%Y%m%d")


def fetch_pro_bar(
    ts_code: str,
    freq: str,
    start: Optional[datetime],
    end: Optional[datetime],
    asset: str = "E",
) -> pd.DataFrame:
    """调用 ts.pro_bar，返回统一格式 DataFrame。"""
    ts_client, _ = _load_client()
    start_date = _to_trade_date(start)
    end_date = _to_trade_date(end)
    try:
        df = ts_client.pro_bar(
            ts_code=ts_code,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            asset=asset,
        )
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare pro_bar 请求失败：{ts_code}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()
    datetime_col = None
    for candidate in ("trade_time", "datetime", "trade_dt"):
        if candidate in data.columns:
            datetime_col = candidate
            break
    if datetime_col is None and "trade_date" in data.columns:
        datetime_col = "trade_date"
    if datetime_col is None:
        logger.warning("Tushare 返回缺少时间列：%s", data.columns.tolist())
        return pd.DataFrame()

    data["Datetime"] = pd.to_datetime(data[datetime_col])
    data.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
            "amount": "Amount",
        },
        inplace=True,
    )
    data = data.dropna(subset=["Datetime"])
    data = data.sort_values("Datetime")
    data = data.set_index("Datetime")
    numeric_cols = ["Open", "High", "Low", "Close", "Volume", "Amount"]
    for col in numeric_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def fetch_daily(trade_date: str) -> pd.DataFrame:
    pro = get_pro()
    try:
        df = pro.daily(trade_date=trade_date)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare daily 请求失败：{trade_date}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], format="%Y%m%d")
    return data


def fetch_daily_basic(trade_date: str, fields: Optional[str] = None) -> pd.DataFrame:
    pro = get_pro()
    kwargs = {"trade_date": trade_date}
    if fields:
        kwargs["fields"] = fields
    try:
        df = pro.daily_basic(**kwargs)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare daily_basic 请求失败：{trade_date}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def fetch_stock_basic(fields: Optional[str] = None) -> pd.DataFrame:
    pro = get_pro()
    kwargs = {"exchange": "", "list_status": "L"}
    if fields:
        kwargs["fields"] = fields
    try:
        df = pro.stock_basic(**kwargs)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, "Tushare stock_basic 请求失败")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def fetch_moneyflow_hsgt(trade_date: str) -> pd.DataFrame:
    pro = get_pro()
    try:
        df = pro.moneyflow_hsgt(trade_date=trade_date)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare moneyflow_hsgt 请求失败：{trade_date}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def fetch_top_list(trade_date: str) -> pd.DataFrame:
    pro = get_pro()
    try:
        df = pro.top_list(trade_date=trade_date)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare top_list 请求失败：{trade_date}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def fetch_top_inst(trade_date: str) -> pd.DataFrame:
    pro = get_pro()
    try:
        df = pro.top_inst(trade_date=trade_date)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare top_inst 请求失败：{trade_date}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def fetch_index_basic(market: str = "SSE") -> pd.DataFrame:
    pro = get_pro()
    try:
        df = pro.index_basic(market=market)
    except Exception as exc:  # pragma: no cover - 接口异常
        _handle_tushare_error(exc, f"Tushare index_basic 请求失败：{market}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()


def fetch_index_daily(ts_code: str, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    pro = get_pro()
    df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], format="%Y%m%d")
    data.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
        },
        inplace=True,
    )
    data = data.sort_values("trade_date").set_index("trade_date")
    return data


def get_latest_trade_date(offset: int = 0) -> Optional[str]:
    pro = get_pro()
    today = datetime.now()
    end_date = today.strftime("%Y%m%d")
    start_date = (today - timedelta(days=15)).strftime("%Y%m%d")
    df = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
    if df is None or df.empty:
        return None
    df = df.sort_values("cal_date")
    if offset >= len(df):
        return df.iloc[-1]["cal_date"]
    return df.iloc[-1 - offset]["cal_date"]


def compute_industry_rankings(daily_df: pd.DataFrame, stock_basic: pd.DataFrame, top_n: int = 5) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """根据当日行情与 stock_basic 中的行业字段计算行业涨跌排行。"""
    if daily_df.empty or stock_basic.empty:
        return pd.DataFrame(), pd.DataFrame()
    merged = daily_df.merge(
        stock_basic[["ts_code", "name", "industry"]],
        on="ts_code",
        how="left",
        suffixes=("", "_basic"),
    )
    merged = merged.dropna(subset=["industry"])
    if merged.empty:
        return pd.DataFrame(), pd.DataFrame()

    grouped = merged.groupby("industry").agg(
        change_pct=("pct_chg", "mean"),
        amount=("amount", "sum"),
    )
    grouped = grouped.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False)

    top = grouped.head(top_n).reset_index()
    bottom = grouped.tail(top_n).reset_index()
    return top, bottom


def select_leaders(
    industry: str,
    daily_df: pd.DataFrame,
    stock_basic: pd.DataFrame,
    ascending: bool,
    limit: int = 3,
) -> pd.DataFrame:
    if daily_df.empty or stock_basic.empty:
        return pd.DataFrame()
    merged = daily_df.merge(
        stock_basic[["ts_code", "name", "industry"]],
        on="ts_code",
        how="left",
    )
    subset = merged[merged["industry"] == industry].copy()
    if subset.empty:
        return pd.DataFrame()
    subset = subset.sort_values("pct_chg", ascending=ascending)
    return subset.head(limit)[["ts_code", "name", "pct_chg"]]


def format_trade_dates(
    start: Optional[datetime],
    end: Optional[datetime],
) -> Tuple[Optional[str], Optional[str]]:
    return _to_trade_date(start), _to_trade_date(end)


def fetch_news(start_date: str, end_date: str) -> pd.DataFrame:
    pro = get_pro()
    try:
        df = pro.news(start_date=start_date, end_date=end_date)
    except Exception as exc:  # pragma: no cover
        logger.debug("Tushare news 拉取失败：%s", exc)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df.copy()
