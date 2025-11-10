from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.schemas import AnalysisHistoryQuery, AnalysisHistoryRecord
from backend.app.services.history import history_store

router = APIRouter(prefix="/history", tags=["analysis-history"])


def _build_query(
    ticker: str | None = Query(None, description="股票代码"),
    timeframe: str | None = Query(None, description="时间周期"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
) -> AnalysisHistoryQuery:
    return AnalysisHistoryQuery(ticker=ticker, timeframe=timeframe, limit=limit, skip=offset)


@router.get("/analysis", response_model=list[AnalysisHistoryRecord])
async def list_analysis_history(params: AnalysisHistoryQuery = Depends(_build_query)) -> list[AnalysisHistoryRecord]:
    records = await history_store.query(params)
    return [record.model_dump(by_alias=True) for record in records]
