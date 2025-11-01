"""StockAI Trader MVP 的 FastAPI 入口。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from datahub.fetcher import get_candles_batch, get_latest_candles, get_quote_summary
from datahub.indicators import compute_all
from datahub.macro import get_macro_snapshot
from datahub.scanner import scan_opportunities
from datahub.watchlist import Watchlist, load_watchlist, save_watchlist
from engine.analyzer import analyze_snapshot
from engine.macro_analyzer import summarize_for_report, summarize_macro
from engine.report import render as render_report


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
    data_source: Optional[str] = Field(None, description="行情数据来源")


class WatchlistRequest(BaseModel):
    symbols: List[str] = Field(..., description="自选股列表，元素为股票代码")


class WatchlistResponseModel(BaseModel):
    symbols: List[str]
    updated_at: datetime


class WatchlistModifyRequest(BaseModel):
    symbol: str = Field(..., description="需要操作的股票代码")


class BatchAnalysisRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="需要分析的股票列表，不提供则使用当前自选股")
    timeframe: str = Field("1d", description="分析周期")
    start: Optional[datetime] = Field(None, description="可选，起始日期时间")
    end: Optional[datetime] = Field(None, description="可选，结束日期时间")
    force_refresh: bool = Field(False, description="是否忽略缓存强制刷新数据")


class BatchAnalysisResponse(BaseModel):
    as_of: datetime
    timeframe: str
    results: Dict[str, AnalysisResponse]
    failed: List[str] = Field(default_factory=list)
    latency_ms: int
    macro: Optional[Dict[str, Any]] = None
    opportunities: Optional[Dict[str, Any]] = None


class MacroSectorItem(BaseModel):
    name: str
    change_pct: float
    fund_flow: Optional[float] = None


class MacroOverviewResponse(BaseModel):
    generated_at: datetime
    overview: str
    highlights: List[str]
    risks: List[str]
    indices: Dict[str, Dict[str, Any]]
    top_sectors: List[MacroSectorItem]
    weak_sectors: List[MacroSectorItem]
    breadth: Dict[str, Any]


class OpportunityRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="股票池，缺省时使用自选/默认池")
    timeframe: str = Field("1d", description="分析周期")
    direction: Literal["long", "short", "all"] = Field("long", description="机会方向")
    limit: int = Field(10, ge=1, le=50, description="返回候选数量")


class OpportunityCandidate(BaseModel):
    ticker: str
    action: str
    score: float
    confidence: float
    rationale: List[str]
    risk_notes: List[str]
    data_source: Optional[str] = None
    reference_price: Optional[float] = None


class OpportunityResponse(BaseModel):
    generated_at: datetime
    direction: str
    timeframe: str
    candidates: List[OpportunityCandidate]


class ReportSummary(BaseModel):
    date: str
    generated_at: datetime
    as_of: datetime
    timeframe: str
    market_overview: str
    highlights: List[Any] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    failed: List[str] = Field(default_factory=list)
    latency_ms: int = 0
    macro: Optional[Dict[str, Any]] = None
    opportunities: Optional[Dict[str, Any]] = None


class ReportDetail(ReportSummary):
    results: Dict[str, Any]


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

REPORT_DIR = Path("reports")
DEFAULT_REPORT_LIMIT = 10


@app.get("/healthz")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


def _normalize_symbols(symbols: Optional[List[str]]) -> List[str]:
    if not symbols:
        return []
    cleaned: List[str] = []
    for symbol in symbols:
        norm = symbol.strip().upper()
        if norm and norm not in cleaned:
            cleaned.append(norm)
    return cleaned


def _list_report_files(limit: int) -> List[Path]:
    if not REPORT_DIR.exists():
        return []
    files = [path for path in REPORT_DIR.glob("*.json") if path.is_file()]
    files.sort(key=lambda p: p.stem, reverse=True)
    return files[:limit]


def _load_report(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - 极少触发
        raise HTTPException(status_code=404, detail="报告不存在") from exc


def _parse_datetime(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_report(data: Dict[str, Any]) -> ReportDetail:
    generated_at = _parse_datetime(data.get("generated_at"))
    as_of = _parse_datetime(data.get("as_of"))
    return ReportDetail(
        date=data.get("date", generated_at.date().isoformat()),
        generated_at=generated_at,
        as_of=as_of,
        timeframe=data.get("timeframe", "1d"),
        market_overview=data.get("market_overview", ""),
        highlights=data.get("highlights", []),
        risks=data.get("risks", []),
        failed=data.get("failed", []),
        latency_ms=data.get("latency_ms", 0),
        macro=data.get("macro"),
        opportunities=data.get("opportunities"),
        results=data.get("results", {}),
    )


def _to_sector_items(items: List[Dict[str, Any]]) -> List[MacroSectorItem]:
    sector_items: List[MacroSectorItem] = []
    for item in items:
        sector_items.append(
            MacroSectorItem(
                name=str(item.get("name", "")),
                change_pct=float(item.get("change_pct", 0.0)),
                fund_flow=item.get("fund_flow"),
            )
        )
    return sector_items


async def _run_single_analysis(
    ticker: str,
    timeframe: str,
    start: Optional[datetime],
    end: Optional[datetime],
    force_refresh: bool = False,
    include_quote: bool = True,
) -> AnalysisResponse:
    start_time = time.perf_counter()
    candles = await get_latest_candles(
        ticker=ticker,
        start=start,
        end=end,
        interval=timeframe,
        force_refresh=force_refresh,
    )

    if candles.empty:
        raise HTTPException(status_code=404, detail=f"未找到 {ticker} 的行情数据")

    features = compute_all(candles)
    snapshot = analyze_snapshot(features)
    decision = snapshot["decision"]

    as_of = decision.get("as_of") or features["timestamp"]
    as_of_dt = datetime.fromisoformat(as_of)

    report_text = render_report(decision)

    quote_snapshot = None
    if include_quote:
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
        data_source=candles.attrs.get("source"),
    )


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    ticker = request.ticker.upper()
    return await _run_single_analysis(
        ticker=ticker,
        timeframe=request.timeframe,
        start=request.start,
        end=request.end,
        force_refresh=request.force_refresh,
        include_quote=True,
    )


@app.get("/watchlist", response_model=WatchlistResponseModel)
async def get_watchlist() -> WatchlistResponseModel:
    watchlist = load_watchlist()
    return WatchlistResponseModel(
        symbols=watchlist.symbols,
        updated_at=watchlist.updated_at,
    )


@app.post("/watchlist", response_model=WatchlistResponseModel)
async def update_watchlist(payload: WatchlistRequest) -> WatchlistResponseModel:
    symbols = _normalize_symbols(payload.symbols)
    watchlist = Watchlist()
    watchlist.extend(symbols)
    save_watchlist(watchlist)
    return WatchlistResponseModel(
        symbols=watchlist.symbols,
        updated_at=watchlist.updated_at,
    )


@app.post("/watchlist/add", response_model=WatchlistResponseModel)
async def add_watchlist_symbol(payload: WatchlistModifyRequest) -> WatchlistResponseModel:
    watchlist = load_watchlist()
    watchlist.add(payload.symbol)
    save_watchlist(watchlist)
    return WatchlistResponseModel(
        symbols=watchlist.symbols,
        updated_at=watchlist.updated_at,
    )


@app.post("/watchlist/remove", response_model=WatchlistResponseModel)
async def remove_watchlist_symbol(payload: WatchlistModifyRequest) -> WatchlistResponseModel:
    watchlist = load_watchlist()
    watchlist.remove(payload.symbol.upper())
    save_watchlist(watchlist)
    return WatchlistResponseModel(
        symbols=watchlist.symbols,
        updated_at=watchlist.updated_at,
    )


@app.post("/watchlist/analyze", response_model=BatchAnalysisResponse)
async def analyze_watchlist(payload: BatchAnalysisRequest) -> BatchAnalysisResponse:
    start_time = time.perf_counter()
    symbols = _normalize_symbols(payload.tickers)
    if not symbols:
        stored = load_watchlist()
        symbols = stored.symbols
        if not symbols:
            raise HTTPException(status_code=400, detail="自选股列表为空，请先添加股票。")

    candles_map = await get_candles_batch(
        tickers=symbols,
        start=payload.start,
        end=payload.end,
        interval=payload.timeframe,
        force_refresh=payload.force_refresh,
    )

    results: Dict[str, AnalysisResponse] = {}
    failed: List[str] = []
    latest_timestamp: Optional[datetime] = None

    for symbol in symbols:
        df = candles_map.get(symbol)
        if df is None or df.empty:
            failed.append(symbol)
            continue
        ticker_start = time.perf_counter()
        try:
            features = compute_all(df)
            snapshot = analyze_snapshot(features)
            decision = snapshot["decision"]
            as_of_raw = decision.get("as_of") or features["timestamp"]
            as_of_dt = datetime.fromisoformat(as_of_raw)
            report_text = render_report(decision)
            response = AnalysisResponse(
                ticker=symbol,
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
                latency_ms=int((time.perf_counter() - ticker_start) * 1000),
                quote_snapshot=None,
                data_source=df.attrs.get("source"),
            )
            results[symbol] = response
            if latest_timestamp is None or as_of_dt > latest_timestamp:
                latest_timestamp = as_of_dt
        except Exception as exc:
            failed.append(symbol)
            continue

    if not results:
        raise HTTPException(status_code=502, detail="批量分析失败，请稍后重试。")

    macro_snapshot = await get_macro_snapshot()
    macro_summary = summarize_macro(macro_snapshot)
    macro_report = summarize_for_report(macro_summary)

    opportunity_payload = await scan_opportunities(
        tickers=symbols,
        timeframe=payload.timeframe,
        direction="all",
        limit=10,
        force_refresh=payload.force_refresh,
    )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    as_of_value = latest_timestamp or datetime.now(timezone.utc)

    return BatchAnalysisResponse(
        as_of=as_of_value,
        timeframe=payload.timeframe,
        results=results,
        failed=failed,
        latency_ms=latency_ms,
        macro=macro_report,
        opportunities=opportunity_payload,
    )


@app.get("/macro/overview", response_model=MacroOverviewResponse)
async def macro_overview() -> MacroOverviewResponse:
    snapshot = await get_macro_snapshot()
    summary = summarize_macro(snapshot)
    report = summarize_for_report(summary)
    generated_raw = snapshot.get("generated_at")
    generated_at = datetime.fromisoformat(generated_raw) if generated_raw else datetime.now(timezone.utc)
    top_items = _to_sector_items(report.get("top_sectors", []))
    weak_items = _to_sector_items(report.get("weak_sectors", []))
    return MacroOverviewResponse(
        generated_at=generated_at,
        overview=report.get("overview", ""),
        highlights=report.get("highlights", []),
        risks=report.get("risks", []),
        indices=summary.indices,
        top_sectors=top_items,
        weak_sectors=weak_items,
        breadth=report.get("breadth", {}),
    )


@app.post("/scanner/opportunities", response_model=OpportunityResponse)
async def scan_opportunity_endpoint(payload: OpportunityRequest) -> OpportunityResponse:
    data = await scan_opportunities(
        tickers=payload.tickers,
        timeframe=payload.timeframe,
        direction=payload.direction,
        limit=payload.limit,
    )
    generated_raw = data.get("generated_at")
    generated_at = datetime.fromisoformat(generated_raw) if generated_raw else datetime.now(timezone.utc)
    candidates = [OpportunityCandidate(**item) for item in data.get("candidates", [])]
    return OpportunityResponse(
        generated_at=generated_at,
        direction=data.get("direction", payload.direction),
        timeframe=data.get("timeframe", payload.timeframe),
        candidates=candidates,
    )


@app.get("/reports/latest", response_model=ReportDetail)
async def get_latest_report() -> ReportDetail:
    files = _list_report_files(limit=1)
    if not files:
        raise HTTPException(status_code=404, detail="暂无报告")
    data = _load_report(files[0])
    return _parse_report(data)


@app.get("/reports", response_model=List[ReportSummary])
async def list_reports(limit: int = DEFAULT_REPORT_LIMIT) -> List[ReportSummary]:
    limit = max(1, min(limit, 50))
    files = _list_report_files(limit)
    summaries: List[ReportSummary] = []
    for path in files:
        detail = _parse_report(_load_report(path))
        summaries.append(
            ReportSummary(
                date=detail.date,
                generated_at=detail.generated_at,
                as_of=detail.as_of,
                timeframe=detail.timeframe,
                market_overview=detail.market_overview,
                highlights=detail.highlights,
                risks=detail.risks,
                failed=detail.failed,
                latency_ms=detail.latency_ms,
                macro=detail.macro,
                opportunities=detail.opportunities,
            )
        )
    return summaries


@app.get("/reports/{date}", response_model=ReportDetail)
async def get_report_by_date(date: str) -> ReportDetail:
    path = REPORT_DIR / f"{date}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")
    return _parse_report(_load_report(path))


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

app.add_api_route(
    "/api/watchlist",
    get_watchlist,
    methods=["GET"],
    response_model=WatchlistResponseModel,
)

app.add_api_route(
    "/api/watchlist",
    update_watchlist,
    methods=["POST"],
    response_model=WatchlistResponseModel,
)

app.add_api_route(
    "/api/watchlist/add",
    add_watchlist_symbol,
    methods=["POST"],
    response_model=WatchlistResponseModel,
)

app.add_api_route(
    "/api/watchlist/remove",
    remove_watchlist_symbol,
    methods=["POST"],
    response_model=WatchlistResponseModel,
)

app.add_api_route(
    "/api/watchlist/analyze",
    analyze_watchlist,
    methods=["POST"],
    response_model=BatchAnalysisResponse,
)

app.add_api_route(
    "/api/macro/overview",
    macro_overview,
    methods=["GET"],
    response_model=MacroOverviewResponse,
)

app.add_api_route(
    "/api/scanner/opportunities",
    scan_opportunity_endpoint,
    methods=["POST"],
    response_model=OpportunityResponse,
)

app.add_api_route(
    "/api/reports/latest",
    get_latest_report,
    methods=["GET"],
    response_model=ReportDetail,
)

app.add_api_route(
    "/api/reports",
    list_reports,
    methods=["GET"],
    response_model=List[ReportSummary],
)

app.add_api_route(
    "/api/reports/{date}",
    get_report_by_date,
    methods=["GET"],
    response_model=ReportDetail,
)
