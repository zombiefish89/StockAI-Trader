"""
行情特征摘要工具。

将 compute_all 产出的指标进行整理，供 LLM 等上层模块引用，
避免直接暴露最终决策结果，保留更多原始信号信息。
"""

from __future__ import annotations

from typing import Any, Dict


def summarize_indicators(features: Dict[str, Any]) -> Dict[str, Any]:
    """提取适合 LLM 消费的关键指标。"""

    def _compact(data: Dict[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in data.items() if value is not None}

    price = _compact(
        {
            "close": features.get("price"),
            "open": features.get("open"),
            "high": features.get("high"),
            "low": features.get("low"),
            "volume": features.get("volume"),
            "recent_high": features.get("recent_high"),
            "recent_low": features.get("recent_low"),
        }
    )

    trend = _compact(
        {
            "ema20": features.get("ema20"),
            "ema50": features.get("ema50"),
            "ema200": features.get("ema200"),
            "ema_trend_up": features.get("ema_trend_up"),
            "ema_trend_down": features.get("ema_trend_down"),
            "macd_line": features.get("macd_line"),
            "macd_signal": features.get("macd_signal"),
            "macd_hist": features.get("macd_hist"),
            "macd_cross": features.get("macd_cross"),
            "adx": features.get("adx"),
        }
    )

    momentum = _compact(
        {
            "rsi": features.get("rsi"),
            "rsi_zscore": features.get("rsi_zscore"),
            "stoch_rsi": features.get("stoch_rsi"),
            "kdj_k": features.get("kdj_k"),
            "kdj_d": features.get("kdj_d"),
            "kdj_j": features.get("kdj_j"),
        }
    )

    volatility = _compact(
        {
            "atr": features.get("atr"),
            "atr_percent": features.get("atr_percent"),
            "bollinger_upper": features.get("bb_upper"),
            "bollinger_middle": features.get("bb_middle"),
            "bollinger_lower": features.get("bb_lower"),
            "bollinger_position": features.get("bb_position"),
        }
    )

    volume = _compact(
        {
            "volume": features.get("volume"),
            "volume_avg_5d": features.get("volume_avg_5d"),
            "volume_avg_20d": features.get("volume_avg_20d"),
            "volume_score": features.get("volume_score"),
        }
    )

    pattern_flags = []
    pattern_source = features.get("patterns")
    if isinstance(pattern_source, dict):
        for key, value in pattern_source.items():
            if value:
                pattern_flags.append(key)

    sentiment = _compact(
        {
            "news_score": features.get("news_score"),
            "news_pos": features.get("news_pos"),
            "news_neg": features.get("news_neg"),
        }
    )

    return {
        "price": price,
        "trend": trend,
        "momentum": momentum,
        "volatility": volatility,
        "volume": volume,
        "pattern_flags": pattern_flags,
        "sentiment": sentiment,
    }
