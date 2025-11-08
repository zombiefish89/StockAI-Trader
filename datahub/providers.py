"""
行情数据提供方适配器集合。

通过统一的接口封装 yfinance 与 AkShare 等来源，便于在
分析层依据市场类型切换或组合不同数据源。
"""

from __future__ import annotations

import abc
import logging
import os
from datetime import datetime
from typing import Dict, Iterable, Optional

import pandas as pd
import yfinance as yf

from .akshare_api import (
    AkShareUnavailable,
    fetch_a_stock_daily,
    fetch_a_stock_minute,
    fetch_us_stock_daily,
    is_available as akshare_is_available,
)
from .tushare_api import (
    TushareUnavailable,
    fetch_pro_bar,
    to_ts_code,
)

logger = logging.getLogger(__name__)


def normalize_yfinance_symbol(ticker: str) -> str:
    """将常见 A 股/港股代码转换为 yfinance 可识别的格式。"""
    if not ticker:
        return ticker
    symbol = ticker.strip()
    upper = symbol.upper()

    if "." in upper:
        base, suffix = upper.split(".", 1)
        suffix = suffix.upper()
        if suffix in {"SS", "SH"}:
            return f"{base}.SS"
        if suffix in {"SZ"}:
            return f"{base}.SZ"
        if suffix in {"BJ"}:
            return f"{base}.BJ"
        if suffix in {"HK"}:
            return f"{base}.HK"
        return upper

    if upper.startswith("SH") and len(upper) >= 8:
        return f"{upper[-6:]}.SS"
    if upper.startswith("SZ") and len(upper) >= 8:
        return f"{upper[-6:]}.SZ"
    if upper.startswith("BJ") and len(upper) >= 8:
        return f"{upper[-6:]}.BJ"

    if len(upper) == 6 and upper.isdigit():
        prefix = upper[0]
        if prefix in {"6", "9", "5"}:
            return f"{upper}.SS"
        if prefix in {"0", "2", "3"}:
            return f"{upper}.SZ"
        if prefix in {"4", "8"}:
            return f"{upper}.BJ"
    return upper


class ProviderError(RuntimeError):
    """数据提供方抛出的统一异常。"""


class CandleProvider(abc.ABC):
    """行情 K 线提供方的抽象基类。"""

    name: str

    @abc.abstractmethod
    def supports(self, interval: str) -> bool:
        """返回是否支持指定周期。"""

    @abc.abstractmethod
    def fetch_candles(
        self,
        ticker: str,
        start: Optional[datetime],
        end: Optional[datetime],
        interval: str,
    ) -> pd.DataFrame:
        """抓取指定区间的 K 线数据。"""


class YFinanceProvider(CandleProvider):
    """yfinance 提供的免费行情源。"""

    name = "yfinance"

    def supports(self, interval: str) -> bool:  # noqa: D401 - 简洁注释已足够
        return True

    def fetch_candles(
        self,
        ticker: str,
        start: Optional[datetime],
        end: Optional[datetime],
        interval: str,
    ) -> pd.DataFrame:
        kwargs: Dict[str, object] = {
            "interval": interval,
            "auto_adjust": False,
            "progress": False,
            "threads": False,
        }
        if start:
            kwargs["start"] = start
        if end:
            kwargs["end"] = end

        symbol = normalize_yfinance_symbol(ticker)
        logger.info("使用 yfinance 拉取 %s/%s", symbol, interval)
        df = yf.download(symbol, **kwargs)
        if df is None:
            return pd.DataFrame()
        return df


class TushareProvider(CandleProvider):
    """Tushare Pro 行情源，覆盖 A 股日线与分钟级数据。"""

    name = "tushare"
    _FREQ_MAP = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "60m": "60min",
        "1h": "60min",
        "1d": "D",
    }
    _SUPPORTED = set(_FREQ_MAP.keys())

    def __init__(self) -> None:
        try:
            from .tushare_api import get_ts  # noqa: F401

            get_ts()
        except TushareUnavailable as exc:
            raise ProviderError(str(exc)) from exc

    def supports(self, interval: str) -> bool:
        return interval in self._SUPPORTED

    def fetch_candles(
        self,
        ticker: str,
        start: Optional[datetime],
        end: Optional[datetime],
        interval: str,
    ) -> pd.DataFrame:
        ts_code = to_ts_code(ticker)
        freq = self._FREQ_MAP[interval]
        df = fetch_pro_bar(
            ts_code=ts_code,
            freq=freq,
            start=start,
            end=end,
            asset="E",
        )
        if df.empty:
            raise ProviderError("Tushare 返回的数据为空。")

        if start:
            df = df[df.index >= start]
        if end:
            df = df[df.index <= end]

        if df.empty:
            raise ProviderError("Tushare 数据为空。")

        try:
            df.index = df.index.tz_localize("Asia/Shanghai", nonexistent="shift_forward", ambiguous="NaT").tz_convert("UTC")
        except TypeError:
            df.index = df.index.tz_convert("UTC")

        columns = ["Open", "High", "Low", "Close", "Volume"]
        existing = [col for col in columns if col in df.columns]
        return df[existing]


def load_tushare_provider() -> Optional[TushareProvider]:
    """构造 Tushare 行情提供方。"""
    if os.getenv("TUSHARE_DISABLE") == "1":
        return None
    try:
        return TushareProvider()
    except ProviderError as exc:
        logger.warning("Tushare 初始化失败：%s", exc)
        return None


class AkShareProvider(CandleProvider):
    """AkShare 免费行情数据，适合 A 股日内与日线。"""

    name = "akshare"
    _MINUTE_MAP = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}
    _SUPPORTED = set(_MINUTE_MAP.keys()) | {"1d"}

    def __init__(self) -> None:
        if not akshare_is_available():
            raise ProviderError("缺少 akshare，请安装后再启用该数据源。")

    def supports(self, interval: str) -> bool:
        return interval in self._SUPPORTED

    def fetch_candles(
        self,
        ticker: str,
        start: Optional[datetime],
        end: Optional[datetime],
        interval: str,
    ) -> pd.DataFrame:
        symbol = self._transform_symbol(ticker)
        try:
            if interval == "1d":
                df = fetch_a_stock_daily(symbol)
            else:
                period = self._MINUTE_MAP[interval]
                df = fetch_a_stock_minute(symbol, period)
        except AkShareUnavailable as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:
            raise ProviderError(f"AkShare 获取 {symbol}/{interval} 失败：{exc}") from exc

        if df is None or df.empty:
            raise ProviderError("AkShare 返回的数据为空。")

        if start:
            df = df[df.index >= start]
        if end:
            df = df[df.index <= end]

        if df.empty:
            raise ProviderError("AkShare 数据为空。")
        return df

    @staticmethod
    def _transform_symbol(ticker: str) -> str:
        symbol = ticker.lower()
        if symbol.startswith(("sh", "sz", "bj")):
            return symbol
        if "." in symbol:
            base, suffix = symbol.split(".", 1)
            suffix = suffix.lower()
            if suffix in {"ss", "sh"}:
                return f"sh{base}"
            if suffix in {"sz"}:
                return f"sz{base}"
            if suffix in {"bj"}:
                return f"bj{base}"
        if len(symbol) == 6 and symbol.isdigit():
            if symbol.startswith(("5", "6", "9")):
                return f"sh{symbol}"
            return f"sz{symbol}"
        raise ProviderError("AkShare 仅支持 A 股代码，例如 sh600519 或 600519。")


def load_akshare_provider() -> Optional[AkShareProvider]:
    """若安装了 akshare，则构造 AkShare 提供方实例。"""
    if os.getenv("AKSHARE_DISABLE") == "1":
        return None
    try:
        return AkShareProvider()
    except ProviderError as exc:
        logger.warning("AkShare 初始化失败：%s", exc)
        return None


class AkShareUSProvider(CandleProvider):
    """AkShare 美股行情数据，作为 yfinance 的备用。"""

    name = "akshare_us"
    _SUPPORTED = {"1d"}

    def __init__(self) -> None:
        if not akshare_is_available():
            raise ProviderError("缺少 akshare，请安装后再启用该数据源。")

    def supports(self, interval: str) -> bool:
        return interval in self._SUPPORTED

    def fetch_candles(
        self,
        ticker: str,
        start: Optional[datetime],
        end: Optional[datetime],
        interval: str,
    ) -> pd.DataFrame:
        symbol = ticker.upper()
        logger.info("使用 AkShare US 拉取 %s/%s", symbol, interval)
        try:
            df = fetch_us_stock_daily(symbol)
        except AkShareUnavailable as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:
            raise ProviderError(f"AkShare US 获取 {symbol} 行情失败：{exc}") from exc

        if df is None or df.empty:
            raise ProviderError("AkShare US 未返回日线数据。")

        if start:
            df = df[df.index >= start]
        if end:
            df = df[df.index <= end]

        if df.empty:
            raise ProviderError("AkShare US 数据为空。")
        return df


def load_akshare_us_provider() -> Optional[AkShareUSProvider]:
    """若安装了 akshare，则构造 AkShare 美股提供方实例。"""
    if os.getenv("AKSHARE_DISABLE_US") == "1":
        return None
    try:
        return AkShareUSProvider()
    except ProviderError as exc:
        logger.warning("AkShare US 初始化失败：%s", exc)
        return None


def default_providers() -> Iterable[CandleProvider]:
    """返回默认启用的提供方列表，按优先级排序。"""
    providers: list[CandleProvider] = []
    tushare = load_tushare_provider()
    if tushare is not None:
        providers.append(tushare)
    akshare = load_akshare_provider()
    if akshare is not None:
        providers.append(akshare)
    akshare_us = load_akshare_us_provider()
    if akshare_us is not None:
        providers.append(akshare_us)
    providers.append(YFinanceProvider())
    return providers
