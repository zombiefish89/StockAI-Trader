"""机会筛选规则模块。"""

from __future__ import annotations

from typing import Dict


DEFAULT_THRESHOLDS = {
    "long": {"min_score": 0.4, "min_confidence": 0.55},
    "short": {"max_score": -0.4, "min_confidence": 0.55},
}


def is_candidate(decision: Dict[str, float], direction: str = "long") -> bool:
    """根据方向判断是否满足机会条件。"""

    thresholds = DEFAULT_THRESHOLDS.get(direction, {})
    score = float(decision.get("scores", {}).get("total", 0.0))
    confidence = float(decision.get("confidence", 0.0))

    if direction == "long":
        return score >= thresholds.get("min_score", 0.0) and confidence >= thresholds.get("min_confidence", 0.0)
    if direction == "short":
        return score <= thresholds.get("max_score", 0.0) and confidence >= thresholds.get("min_confidence", 0.0)
    if direction == "all":
        return confidence >= 0.5 and abs(score) >= 0.35
    return False

