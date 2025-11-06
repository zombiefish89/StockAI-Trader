"""
行情特征摘要工具。

将 compute_all 产出的指标进行整理，供 LLM 等上层模块引用，
避免直接暴露最终决策结果，保留更多原始信号信息。
"""

from __future__ import annotations

from typing import Any, Dict


def summarize_indicators(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 compute_all 的结果中提取适合 LLM 消费的信号。

    返回结构示例：
    {
        "price": {...},
        "trend": {...},
        "momentum": {...},
        "volatility": {...},
        "volume": {...},
        "pattern_flags": [...],
    }
    """

    def _section(name: str, keys: Dict[str, str]) -> Dict[str, Any]:
        section: Dict[str, Any] = {}
        source = features.get(name, {})
        if isinstance(source, dict):
            for out_key, src_key in keys.items():
                value = source.get(src_key)
                if value is not None:
                    section[out_key] = value
        return section

    price = _section(
        "price",
        {
            "close": "close",
            "high": "high",
            "low": "low",
            "open": "open",
            "change_pct_1d": "change_pct_1d",
            "change_pct_5d": "change_pct_5d",
        },
    )

    trend = _section(
        "trend",
        {
            "sma_5": "sma_5",
            "sma_20": "sma_20",
            "sma_50": "sma_50",
            "ema_12": "ema_12",
            "ema_26": "ema_26",
            "macd": "macd",
            "macd_signal": "macd_signal",
            "adx": "adx",
            "trend_score": "trend_score",
        },
    )

    momentum = _section(
        "momentum",
        {
            "rsi_6": "rsi_6",
            "rsi_14": "rsi_14",
            "stoch_k": "stoch_k",
            "stoch_d": "stoch_d",
            "cci": "cci",
            "momentum_score": "momentum_score",
        },
    )

    volatility = _section(
        "volatility",
        {
            "atr": "atr",
            "atr_percent": "atr_percent",
            "bollinger_upper": "bollinger_upper",
            "bollinger_middle": "bollinger_middle",
            "bollinger_lower": "bollinger_lower",
            "volatility_score": "volatility_score",
        },
    )

    volume = _section(
        "volume",
        {
            "volume": "volume",
            "volume_avg_5d": "volume_avg_5d",
            "volume_avg_20d": "volume_avg_20d",
            "volume_score": "volume_score",
        },
    )

    pattern_flags = []
    pattern_source = features.get("patterns")
    if isinstance(pattern_source, dict):
        for key, value in pattern_source.items():
            if value:
                pattern_flags.append(key)

    sentiment = _section(
        "sentiment",
        {
            "news_score": "news_score",
            "news_pos": "news_pos",
            "news_neg": "news_neg",
        },
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
