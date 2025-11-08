from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import logging

from backend.app.core.llm_adapter import generate_report_json
from backend.app.core.normalize import normalize_report
from backend.app.schemas.report import StockAIReport
from datahub.fetcher import get_quote_summary, get_latest_candles  # type: ignore
from datahub.indicators import compute_all  # type: ignore
from datahub.macro import get_macro_snapshot  # type: ignore
from datahub.tushare_api import (  # type: ignore
    TushareUnavailable,
    get_pro,
    to_ts_code,
)
from engine.features import summarize_indicators  # type: ignore
from engine.macro_analyzer import summarize_for_report, summarize_macro  # type: ignore

import pandas as pd

logger = logging.getLogger(__name__)


async def _fetch_snapshot(ticker: str, timeframe: str) -> Dict[str, Any]:
    quote: Optional[Dict[str, Any]] = None
    indicators_payload: Optional[Dict[str, Any]] = None
    candles = None
    try:
        quote = await get_quote_summary(ticker)
    except Exception as exc:
        logger.warning("获取报价信息失败：%s -> %s", ticker, exc)
        quote = None

    try:
        candles = await get_latest_candles(ticker=ticker, interval=timeframe)
        if candles is not None and not getattr(candles, "empty", True):
            features = compute_all(candles)
            indicators_payload = summarize_indicators(features)
        else:
            logger.warning("指标计算失败：%s/%s 无行情数据", ticker, timeframe)
    except Exception as exc:
        logger.exception("指标计算异常：%s/%s -> %s", ticker, timeframe, exc)
        indicators_payload = None

    macro_summary: Optional[Dict[str, Any]] = None
    try:
        macro_snapshot = await get_macro_snapshot()
        macro_summary_raw = summarize_macro(macro_snapshot)
        macro_summary = summarize_for_report(macro_summary_raw)
    except Exception:
        macro_summary = None

    fundamentals = await _fetch_fundamentals(ticker)

    data_source = quote.get("source") if isinstance(quote, dict) else None
    if indicators_payload is None:
        logger.warning("Indicators 缺失：ticker=%s timeframe=%s data_source=%s", ticker, timeframe, data_source)

    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "quote": quote,
        "indicators": indicators_payload,
        "dataSource": data_source,
        "macro": macro_summary,
        "fundamentals": fundamentals,
    }


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calc_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round((current - previous) / abs(previous), 4)


async def _fetch_fundamentals(ticker: str) -> Dict[str, Any]:
    try:
        pro = get_pro()
    except TushareUnavailable:
        return {}

    ts_code = to_ts_code(ticker)

    def _query() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        indicator_df = pro.fina_indicator(ts_code=ts_code, limit=1)
        income_df = pro.income(ts_code=ts_code, limit=4, fields="ts_code,end_date,total_revenue,n_income")
        return indicator_df, income_df

    indicator_df, income_df = await asyncio.to_thread(_query)

    fundamentals: Dict[str, Any] = {}

    if indicator_df is not None and not indicator_df.empty:
        row = indicator_df.iloc[0]
        fundamentals.update(
            {
                "ann_date": row.get("ann_date") or row.get("end_date"),
                "roe": _to_float(row.get("roe")),
                "netprofit_margin": _to_float(row.get("netprofit_margin")),
                "grossprofit_margin": _to_float(row.get("grossprofit_margin")),
                "q_profit_yoy": _to_float(row.get("q_profit_yoy")),
                "q_sales_yoy": _to_float(row.get("q_sales_yoy")),
            }
        )

    if income_df is not None and not income_df.empty:
        data = income_df.copy()
        if "end_date" in data.columns:
            data["end_date"] = pd.to_datetime(data["end_date"])
            data = data.sort_values("end_date", ascending=False)
        latest = data.iloc[0]
        fundamentals.update(
            {
                "total_revenue": _to_float(latest.get("total_revenue")),
                "net_income": _to_float(latest.get("n_income")),
            }
        )
        if len(data) > 1:
            previous = data.iloc[1]
            fundamentals["revenue_yoy"] = _calc_growth(
                _to_float(latest.get("total_revenue")),
                _to_float(previous.get("total_revenue")),
            )
            fundamentals["net_income_yoy"] = _calc_growth(
                _to_float(latest.get("n_income")),
                _to_float(previous.get("n_income")),
            )

    return fundamentals


async def analyze_stock(ticker: str, timeframe: str = "1d") -> StockAIReport:
    ticker = ticker.upper()
    start_time = time.perf_counter()

    context = await _fetch_snapshot(ticker, timeframe)

    raw_payload = await generate_report_json(
        ticker=ticker,
        timeframe=timeframe,
        context=context,
    )

    normalized = normalize_report(raw_payload)

    latency = int((time.perf_counter() - start_time) * 1000)
    metadata = normalized.metadata.model_copy(update={"latencyMs": latency})

    return normalized.model_copy(
        update={
            "asOf": normalized.asOf if isinstance(normalized.asOf, datetime) else datetime.now(timezone.utc),
            "metadata": metadata,
        }
    )
