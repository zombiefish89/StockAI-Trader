"""FastAPI entrypoint for StockAI Trader MVP."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from datahub.fetcher import get_latest_candles, get_quote_summary
from datahub.indicators import compute_all
from engine.analyzer import build_price_info, score_signals
from engine.report import render as render_report
from engine.rules import generate_decision


class AnalysisRequest(BaseModel):
    ticker: str = Field(..., description="股票代码，例如 AAPL 或 600519.SS")
    timeframe: str = Field("1d", description="分析时间粒度，比如 1m / 5m / 1h / 1d")
    start: Optional[datetime] = Field(None, description="可选，起始日期时间")
    end: Optional[datetime] = Field(None, description="可选，结束日期时间")
    force_refresh: bool = Field(False, description="是否忽略缓存强制刷新数据")


class AnalysisResponse(BaseModel):
    ticker: str
    as_of: datetime
    action: str
    entry: float
    stop: float
    targets: List[float]
    confidence: float
    signals: Dict[str, Any]
    scores: Dict[str, float]
    rationale: List[str]
    risk_notes: List[str]
    report: str
    reference_price: float
    atr: float
    latency_ms: int
    quote_snapshot: Dict[str, Any] | None = None


app = FastAPI(
    title="StockAI Trader API",
    version="1.0.0",
    description="AI 股票助手 v1.0 分析接口",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    start_time = time.perf_counter()
    ticker = request.ticker.upper()

    candles = await get_latest_candles(
        ticker=ticker,
        start=request.start,
        end=request.end,
        interval=request.timeframe,
        force_refresh=request.force_refresh,
    )

    if candles.empty:
        raise HTTPException(status_code=404, detail=f"未找到 {ticker} 的行情数据")

    features = compute_all(candles)
    scores = score_signals(features)
    price_info = build_price_info(features)
    decision = generate_decision(scores, price_info, features)

    as_of = decision.get("as_of") or features["timestamp"]
    as_of_dt = datetime.fromisoformat(as_of)

    report_text = render_report(decision)

    quote_snapshot = None
    try:
        quote_snapshot = await get_quote_summary(ticker)
    except Exception:
        quote_snapshot = None

    latency_ms = int((time.perf_counter() - start_time) * 1000)

    return AnalysisResponse(
        ticker=ticker,
        as_of=as_of_dt,
        action=decision["action"],
        entry=float(decision["entry"]),
        stop=float(decision["stop"]),
        targets=[float(t) for t in decision["targets"]],
        confidence=float(decision["confidence"]),
        signals=decision["signals"],
        scores=decision["scores"],
        rationale=decision["rationale"],
        risk_notes=decision["risk_notes"],
        report=report_text,
        reference_price=float(decision["reference_price"]),
        atr=float(decision["atr"]),
        latency_ms=latency_ms,
        quote_snapshot=quote_snapshot,
    )


app.add_api_route(
    "/api/analyze",
    analyze,
    methods=["POST"],
    response_model=AnalysisResponse,
)

app.add_api_route(
    "/api/healthz",
    health_check,
    methods=["GET"],
    response_model=Dict[str, str],
)
