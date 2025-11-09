from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.report import StockAIReport


class AnalysisHistoryRecord(BaseModel):
    id: str = Field(..., alias="_id")
    ticker: str
    timeframe: str
    asOf: datetime
    createdAt: datetime = Field(..., alias="created_at")
    report: StockAIReport
    context: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


class AnalysisHistoryQuery(BaseModel):
    ticker: Optional[str] = None
    timeframe: Optional[str] = None
    limit: int = Field(20, ge=1, le=100)
    skip: int = Field(0, ge=0)
