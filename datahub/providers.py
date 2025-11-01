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

logger = logging.getLogger(__name__)


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

        logger.info("使用 yfinance 拉取 %s/%s", ticker, interval)
        df = yf.download(ticker, **kwargs)
        if df is None:
            return pd.DataFrame()
        return df


class AkShareProvider(CandleProvider):
    """AkShare 免费行情数据，适合 A 股日内与日线。"""

    name = "akshare"
    _MINUTE_MAP = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}
    _SUPPORTED = set(_MINUTE_MAP.keys()) | {"1d"}

    def __init__(self) -> None:
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:  # pragma: no cover - 需额外依赖
            raise ProviderError("缺少 akshare，请安装后再启用该数据源。") from exc
        self._ak = ak

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
        if interval == "1d":
            df = self._ak.stock_zh_a_daily(symbol=symbol, adjust="")  # 原始数据
            if df is None or df.empty:
                raise ProviderError("AkShare 未返回日线数据。")
            df.rename(
                columns={
                    "date": "Datetime",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
                inplace=True,
            )
            df["Datetime"] = pd.to_datetime(df["Datetime"])
        else:
            period = self._MINUTE_MAP[interval]
            df = self._ak.stock_zh_a_minute(symbol=symbol, period=period)
            if df is None or df.empty:
                raise ProviderError("AkShare 未返回分钟级行情。")
            df.rename(
                columns={
                    "day": "Datetime",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                },
                inplace=True,
            )
            df["Datetime"] = pd.to_datetime(df["Datetime"])

        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(subset=["Datetime"], inplace=True)
        df["Datetime"] = df["Datetime"].dt.tz_localize("Asia/Shanghai").dt.tz_convert("UTC")
        df.set_index("Datetime", inplace=True)
        df.sort_index(inplace=True)

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
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:  # pragma: no cover - 需额外依赖
            raise ProviderError("缺少 akshare，请安装后再启用该数据源。") from exc
        self._ak = ak

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
        df = self._ak.stock_us_daily(symbol=symbol, adjust="")
        if df is None or df.empty:
            raise ProviderError("AkShare US 未返回日线数据。")

        df.rename(
            columns={
                "日期": "Datetime",
                "开盘": "Open",
                "最高": "High",
                "最低": "Low",
                "收盘": "Close",
                "成交量": "Volume",
            },
            inplace=True,
        )
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(subset=["Datetime"], inplace=True)
        df["Datetime"] = df["Datetime"].dt.tz_localize("America/New_York").dt.tz_convert("UTC")
        df.set_index("Datetime", inplace=True)
        df.sort_index(inplace=True)

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
    akshare = load_akshare_provider()
    if akshare is not None:
        providers.append(akshare)
    akshare_us = load_akshare_us_provider()
    if akshare_us is not None:
        providers.append(akshare_us)
    providers.append(YFinanceProvider())
    return providers
