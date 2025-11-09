from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from backend.app.schemas.report import (
    ScenarioRow,
    StockAIReport,
    TradingPlan,
    Verdict,
)

FINAL_VERDICTS: List[Verdict] = [
    Verdict.HOLD,
    Verdict.BUY_THE_DIP,
    Verdict.TRIM,
    Verdict.SELL,
]


def _round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _normalize_plan(plan: Optional[TradingPlan], confidence: float) -> Optional[TradingPlan]:
    if plan is None:
        return None

    data = plan.model_dump()
    data["entry"] = _round(data.get("entry"))
    data["stop"] = _round(data.get("stop"))

    targets = data.get("targets")
    if isinstance(targets, list):
        rounded_targets = [_round(val) for val in targets]
        data["targets"] = [val for val in rounded_targets if val is not None]

    entry_range = data.get("entryRange")
    if isinstance(entry_range, dict):
        entry_range["min"] = _round(entry_range.get("min"))
        entry_range["max"] = _round(entry_range.get("max"))
        data["entryRange"] = entry_range

    if confidence < 0.55:
        data["entry"] = None

    return TradingPlan.model_validate(data)


def _normalize_scenarios(rows: List[ScenarioRow]) -> List[ScenarioRow]:
    normalized: List[ScenarioRow] = []
    for row in rows:
        data = row.model_dump()
        probability = data.get("probability")
        if isinstance(probability, (int, float)):
            prob = float(probability)
            if prob > 1:
                prob = prob / 100.0
            data["probability"] = round(prob, 2)
        else:
            data["probability"] = None
        data["target"] = _round(data.get("target"))
        normalized.append(ScenarioRow.model_validate(data))
    return normalized


def normalize_report(payload: Dict[str, Any]) -> StockAIReport:
    base = StockAIReport.model_validate(payload)
    data = deepcopy(base).model_dump()

    verdict = base.verdict

    confidence = verdict.confidence
    if confidence is not None:
        confidence = max(0.0, min(1.0, float(confidence)))
        data["verdict"]["confidence"] = round(confidence, 4)

    plan = _normalize_plan(base.plan, confidence if confidence is not None else 0.0) if base.plan else None
    if verdict.decision == Verdict.HOLD:
        plan = None
    data["plan"] = plan.model_dump() if plan else None

    if data["verdict"]["decision"] not in {v.value for v in FINAL_VERDICTS}:
        data["verdict"]["decision"] = Verdict.BUY_THE_DIP.value

    data["scenarios"] = [row.model_dump() for row in _normalize_scenarios(base.scenarios)]

    risk_notes = base.riskNotes or []
    data["riskNotes"] = [note.strip() for note in risk_notes if isinstance(note, str) and note.strip()]

    narrative = (base.analysisNarrative or "").strip()
    if not narrative:
        narrative = "分析内容暂缺，请结合最新行情自行评估。"
    data["analysisNarrative"] = narrative

    return StockAIReport.model_validate(data)
