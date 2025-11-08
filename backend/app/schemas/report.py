from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    HOLD = "HOLD"
    BUY = "BUY"
    BUY_THE_DIP = "BUY_THE_DIP"
    TRIM = "TRIM"
    SELL = "SELL"


class VerdictInfo(BaseModel):
    decision: Verdict
    confidence: float = Field(..., ge=0.0, le=1.0)
    headline: str
    thesis: str


class ReportMetadata(BaseModel):
    dataSource: Optional[str] = None
    modelVersion: Optional[str] = None
    latencyMs: Optional[int] = None


class PlanRange(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    note: Optional[str] = None


class TradingPlan(BaseModel):
    size: Optional[str] = None
    entry: Optional[float] = None
    entryRange: Optional[PlanRange] = None
    trigger: Optional[str] = None
    stop: Optional[float] = None
    stopNote: Optional[str] = None
    targets: Optional[List[float]] = None
    targetNote: Optional[str] = None
    notes: Optional[str] = None


class ScenarioRow(BaseModel):
    name: str
    probability: Optional[float] = None
    trigger: Optional[str] = None
    target: Optional[float] = None
    action: Optional[str] = None


class StockAIReport(BaseModel):
    ticker: str
    timeframe: str
    asOf: datetime
    verdict: VerdictInfo
    metadata: ReportMetadata = Field(default_factory=ReportMetadata)
    plan: Optional[TradingPlan] = None
    scenarios: List[ScenarioRow] = Field(default_factory=list)
    riskNotes: List[str] = Field(default_factory=list)
    analysisNarrative: str
