from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.schemas.report import StockAIReport
from backend.app.services.analyze import analyze_stock

router = APIRouter()


class AnalyzePayload(BaseModel):
    ticker: str = Field(..., description="股票代码，例如 AAPL、300014.SZ")
    timeframe: str = Field(
        "1d",
        description="分析时间周期，例如 1m/5m/15m/1h/4h/1d",
    )


@router.post("/analyze", response_model=StockAIReport)
async def analyze_entry(payload: AnalyzePayload) -> StockAIReport:
    ticker = payload.ticker.strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker 不能为空")
    report = await analyze_stock(ticker=ticker, timeframe=payload.timeframe)
    return report
