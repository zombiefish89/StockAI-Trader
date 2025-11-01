"""Indicator computation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorSnapshot:
    features: Dict[str, Any]


def compute_all(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        raise ValueError("No data available for indicator computation.")

    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data.get("Volume", pd.Series(np.nan, index=data.index))

    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema200 = _ema(close, 200)

    atr = _atr(high, low, close, period=14)
    adx = _adx(high, low, close, period=14)

    macd_line, macd_signal = _macd(close)
    macd_hist = macd_line - macd_signal
    macd_cross = _macd_cross(macd_line, macd_signal)

    rsi = _rsi(close, period=14)
    rsi_zscore = _zscore(rsi, window=100)

    stoch_rsi = _stoch_rsi(rsi, period=14)

    k_value, d_value, j_value = _kdj(high, low, close)

    bb_mavg, bb_upper, bb_lower, bb_pos = _bollinger(close, period=20)

    anchored_vwap = _anchored_vwap(close, volume)

    latest_idx = close.index[-1]
    timestamp = latest_idx if isinstance(latest_idx, datetime) else datetime.now(timezone.utc)

    features: Dict[str, Any] = {
        "price": float(close.iloc[-1]),
        "open": float(data["Open"].iloc[-1]),
        "high": float(high.iloc[-1]),
        "low": float(low.iloc[-1]),
        "volume": float(volume.iloc[-1]) if not np.isnan(volume.iloc[-1]) else None,
        "ema20": float(ema20.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "ema200": float(ema200.iloc[-1]),
        "ema_trend_up": bool(ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]),
        "ema_trend_down": bool(ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "adx": float(adx.iloc[-1]),
        "macd_line": float(macd_line.iloc[-1]),
        "macd_signal": float(macd_signal.iloc[-1]),
        "macd_hist": float(macd_hist.iloc[-1]),
        "macd_cross": macd_cross,
        "rsi": float(rsi.iloc[-1]),
        "rsi_zscore": float(rsi_zscore.iloc[-1]),
        "stoch_rsi": float(stoch_rsi.iloc[-1]),
        "kdj_k": float(k_value.iloc[-1]),
        "kdj_d": float(d_value.iloc[-1]),
        "kdj_j": float(j_value.iloc[-1]),
        "bb_middle": float(bb_mavg.iloc[-1]),
        "bb_upper": float(bb_upper.iloc[-1]),
        "bb_lower": float(bb_lower.iloc[-1]),
        "bb_position": float(bb_pos.iloc[-1]),
        "anchored_vwap": float(anchored_vwap),
        "recent_high": float(close.tail(20).max()),
        "recent_low": float(close.tail(20).min()),
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
    }
    return features


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.rolling(period).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = low.shift(1) - low

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0).fillna(0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0).fillna(0.0)

    tr = _true_range(high, low, close)
    atr = tr.rolling(period).sum().replace(0, np.nan)

    plus_di = 100 * (plus_dm.rolling(period).sum() / atr).fillna(0.0)
    minus_di = 100 * (minus_dm.rolling(period).sum() / atr).fillna(0.0)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.rolling(period).mean()
    return adx.fillna(method="bfill")


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series]:
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    macd_signal = _ema(macd_line, signal)
    return macd_line, macd_signal


def _macd_cross(macd_line: pd.Series, macd_signal: pd.Series) -> str | None:
    if len(macd_line) < 2:
        return None
    prev_diff = macd_line.iloc[-2] - macd_signal.iloc[-2]
    curr_diff = macd_line.iloc[-1] - macd_signal.iloc[-1]
    if prev_diff <= 0 < curr_diff:
        return "bullish"
    if prev_diff >= 0 > curr_diff:
        return "bearish"
    return None


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(method="bfill")


def _zscore(series: pd.Series, window: int) -> pd.Series:
    rolling_mean = series.rolling(window=window, min_periods=window // 2).mean()
    rolling_std = series.rolling(window=window, min_periods=window // 2).std(ddof=0)
    zscore = (series - rolling_mean) / rolling_std.replace(0, np.nan)
    return zscore.fillna(0.0)


def _stoch_rsi(rsi: pd.Series, period: int = 14) -> pd.Series:
    rsi_min = rsi.rolling(period).min()
    rsi_max = rsi.rolling(period).max()
    stoch = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    return stoch.clip(0, 1).fillna(0.5)


def _kdj(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    low_min = low.rolling(window=window).min()
    high_max = high.rolling(window=window).max()
    rsv = ((close - low_min) / (high_max - low_min).replace(0, np.nan)) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d
    return k.fillna(50), d.fillna(50), j.fillna(50)


def _bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    mavg = series.rolling(period).mean()
    std = series.rolling(period).std(ddof=0)
    upper = mavg + num_std * std
    lower = mavg - num_std * std
    position = (series - lower) / (upper - lower).replace(0, np.nan)
    return mavg, upper, lower, position.clip(0, 1).fillna(0.5)


def _anchored_vwap(price: pd.Series, volume: pd.Series) -> float:
    if volume.isna().all():
        return float(price.iloc[-1])
    last_ts = price.index[-1]
    month_start = last_ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    mask = price.index >= month_start
    price_slice = price.loc[mask]
    volume_slice = volume.loc[mask]
    cum_vol = volume_slice.cumsum()
    cum_pv = (price_slice * volume_slice).cumsum()
    valid = cum_vol.replace(0, np.nan)
    vwap_series = cum_pv / valid
    return float(vwap_series.iloc[-1])
