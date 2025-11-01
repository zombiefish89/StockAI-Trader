"""将信号得分转换为可执行建议的规则引擎。"""

from __future__ import annotations

from typing import Any, Dict, List


def generate_decision(
    scores,
    price_info: Dict[str, Any],
    features: Dict[str, Any],
) -> Dict[str, Any]:
    """把打分结果转为具体的交易立场。"""
    total = scores.total
    price = price_info["price"]
    atr = price_info["atr"]

    if total > 0.4:
        action = "buy"
    elif total < -0.4:
        action = "sell"
    else:
        action = "hold"

    entry, stop, targets = _compute_trade_levels(action, price_info)
    confidence = max(min(abs(total) + 0.3, 0.95), 0.1)

    rationale = _build_rationale(action, scores, features)
    risk_notes = _build_risks(action, features)

    decision = {
        "action": action,
        "entry": entry,
        "stop": stop,
        "targets": targets,
        "confidence": round(confidence, 2),
        "scores": {
            "trend": scores.trend,
            "momentum": scores.momentum,
            "revert": scores.revert,
            "total": scores.total,
        },
        "signals": scores.breakdown,
        "rationale": rationale,
        "risk_notes": risk_notes,
        "as_of": price_info.get("timestamp"),
        "reference_price": round(price, 2),
        "atr": round(atr, 2),
    }
    return decision


def _compute_trade_levels(action: str, price_info: Dict[str, Any]) -> tuple[float, float, List[float]]:
    price = price_info["price"]
    atr = price_info["atr"]
    ema20 = price_info.get("ema20", price)
    recent_high = price_info.get("recent_high", price)
    recent_low = price_info.get("recent_low", price)

    if atr <= 0:
        atr = max(price * 0.01, 0.5)

    if action == "buy":
        entry = round(min(price, ema20), 2)
        stop = round(entry - 1.5 * atr, 2)
        target1 = round(entry + 1.5 * atr, 2)
        target2 = round(max(recent_high, target1 + atr), 2)
        targets = [target1, target2]
    elif action == "sell":
        entry = round(max(price, ema20), 2)
        stop = round(entry + 1.5 * atr, 2)
        target1 = round(entry - 1.5 * atr, 2)
        target2 = round(min(recent_low, target1 - atr), 2)
        targets = [target1, target2]
    else:
        entry = round(price, 2)
        stop = round(price - 2 * atr, 2)
        targets = [round(price + atr, 2)]

    return entry, stop, targets


def _build_rationale(action: str, scores: ScoreResult, features: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    breakdown = scores.breakdown

    if breakdown["trend"].get("ema_alignment") == "bullish":
        reasons.append("均线多头排列，趋势偏多")
    elif breakdown["trend"].get("ema_alignment") == "bearish":
        reasons.append("均线空头排列，趋势承压")

    adx = breakdown["trend"].get("adx")
    if adx is not None:
        if adx >= 25:
            reasons.append(f"ADX {adx:.1f}，趋势强度充足")
        elif adx <= 18:
            reasons.append(f"ADX {adx:.1f}，趋势力度不足")

    macd_cross = breakdown["momentum"].get("macd_cross")
    if macd_cross == "bullish":
        reasons.append("MACD 金叉，动量向上")
    elif macd_cross == "bearish":
        reasons.append("MACD 死叉，动量走弱")

    rsi = breakdown["momentum"].get("rsi")
    if rsi is not None:
        reasons.append(f"RSI 位于 {rsi:.1f}")

    bb_pos = breakdown["revert"].get("bb_position")
    if bb_pos is not None:
        reasons.append(f"价格位于布林带分位 {bb_pos:.2f}")

    if not reasons:
        reasons.append("行情信号中性，建议观望或轻仓应对")

    if action == "hold" and scores.total > -0.1:
        reasons.insert(0, "综合信号尚未形成明确方向")

    return reasons


def _build_risks(action: str, features: Dict[str, Any]) -> List[str]:
    risks: List[str] = []
    rsi = features.get("rsi")
    if rsi is not None and rsi > 70:
        risks.append("RSI 超买，短线易回调")
    if rsi is not None and rsi < 30:
        risks.append("RSI 超卖，易出现反弹")

    bb_pos = features.get("bb_position")
    if bb_pos is not None and bb_pos > 0.95:
        risks.append("价格逼近布林带上轨，注意冲高回落风险")
    if bb_pos is not None and bb_pos < 0.1:
        risks.append("价格接近布林带下轨，警惕加速下跌")

    kdj_j = features.get("kdj_j")
    if kdj_j is not None and kdj_j > 110:
        risks.append("KDJ J 值极高，动量透支")
    if kdj_j is not None and kdj_j < 80:
        risks.append("KDJ J 值偏低，反弹或继续下探不确定")

    if action == "buy" and features.get("ema_trend_down"):
        risks.append("均线仍空头排列，反弹失败需果断止损")
    if action == "sell" and features.get("ema_trend_up"):
        risks.append("大趋势仍向上，做空须严格止损")

    return risks
