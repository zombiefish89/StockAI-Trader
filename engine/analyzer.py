"""Signal scoring logic assembling trend, momentum, and mean-reversion views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ScoreResult:
    trend: float
    momentum: float
    revert: float
    total: float
    breakdown: Dict[str, Any]


TREND_WEIGHT = 0.5
MOMENTUM_WEIGHT = 0.3
REVERT_WEIGHT = 0.2


def score_signals(features: Dict[str, Any]) -> ScoreResult:
    """Translate indicator features into weighted signal scores."""
    trend_score = 0.0
    trend_flags: Dict[str, Any] = {}

    if features.get("ema_trend_up"):
        trend_score += 0.6
        trend_flags["ema_alignment"] = "bullish"
    elif features.get("ema_trend_down"):
        trend_score -= 0.6
        trend_flags["ema_alignment"] = "bearish"

    adx = features.get("adx")
    if adx is not None:
        if adx >= 25:
            trend_score += 0.2
            trend_flags["adx"] = adx
        elif adx <= 18:
            trend_score -= 0.1
            trend_flags["adx"] = adx

    vwap = features.get("anchored_vwap")
    price = features.get("price")
    if vwap and price:
        if price >= vwap:
            trend_score += 0.1
            trend_flags["vwap_relation"] = "above"
        else:
            trend_score -= 0.1
            trend_flags["vwap_relation"] = "below"

    momentum_score = 0.0
    momentum_flags: Dict[str, Any] = {}
    macd_cross = features.get("macd_cross")
    macd_hist = features.get("macd_hist")
    if macd_cross == "bullish":
        momentum_score += 0.5
        momentum_flags["macd_cross"] = "bullish"
    elif macd_cross == "bearish":
        momentum_score -= 0.5
        momentum_flags["macd_cross"] = "bearish"
    elif macd_hist is not None:
        momentum_flags["macd_hist"] = macd_hist
        momentum_score += 0.2 if macd_hist > 0 else -0.2

    rsi = features.get("rsi")
    rsi_z = features.get("rsi_zscore")
    if rsi is not None:
        momentum_flags["rsi"] = rsi
        if 45 <= rsi <= 65:
            momentum_score += 0.2
        elif rsi > 70:
            momentum_score -= 0.2
        elif rsi < 35:
            momentum_score -= 0.1
    if rsi_z is not None:
        momentum_flags["rsi_zscore"] = rsi_z
        if abs(rsi_z) < 1.0:
            momentum_score += 0.1
        elif rsi_z > 2.0:
            momentum_score -= 0.1

    stoch_rsi = features.get("stoch_rsi")
    if stoch_rsi is not None:
        momentum_flags["stoch_rsi"] = stoch_rsi
        if 0.2 <= stoch_rsi <= 0.8:
            momentum_score += 0.1
        elif stoch_rsi > 0.85 or stoch_rsi < 0.15:
            momentum_score -= 0.1

    revert_score = 0.0
    revert_flags: Dict[str, Any] = {}
    bb_pos = features.get("bb_position")
    if bb_pos is not None:
        revert_flags["bb_position"] = bb_pos
        if 0.3 <= bb_pos <= 0.6:
            revert_score += 0.2
        elif bb_pos > 0.9:
            revert_score -= 0.2
    kdj_j = features.get("kdj_j")
    if kdj_j is not None:
        revert_flags["kdj_j"] = kdj_j
        if kdj_j < 90:
            revert_score += 0.1
        elif kdj_j > 110:
            revert_score -= 0.2

    atr = features.get("atr")
    if atr:
        revert_flags["atr"] = atr

    total = (
        TREND_WEIGHT * trend_score
        + MOMENTUM_WEIGHT * momentum_score
        + REVERT_WEIGHT * revert_score
    )

    return ScoreResult(
        trend=round(trend_score, 4),
        momentum=round(momentum_score, 4),
        revert=round(revert_score, 4),
        total=round(total, 4),
        breakdown={
            "trend": trend_flags,
            "momentum": momentum_flags,
            "revert": revert_flags,
        },
    )


def build_price_info(features: Dict[str, Any]) -> Dict[str, Any]:
    """Extract price context used by the rules engine."""
    atr = features.get("atr") or 0.0
    price = features.get("price") or 0.0
    fallback_atr = max(price * 0.01, 0.1)
    atr = atr if atr and atr > 0 else fallback_atr
    return {
        "price": price,
        "atr": atr,
        "recent_high": features.get("recent_high", price),
        "recent_low": features.get("recent_low", price),
        "ema20": features.get("ema20", price),
        "ema50": features.get("ema50", price),
        "timestamp": features.get("timestamp"),
    }

