"""
机会扫描器数据模块。

基于批量行情与分析结果，筛选做多/做空机会。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .fetcher import get_candles_batch
from .indicators import compute_all
from .watchlist import Watchlist, load_watchlist
from engine.analyzer import analyze_snapshot
from engine.opportunity_filter import is_candidate

DEFAULT_LONG_POOL = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
]


async def scan_opportunities(
    tickers: Optional[List[str]] = None,
    timeframe: str = "1d",
    direction: str = "long",
    limit: int = 10,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """扫描潜在交易机会。"""

    symbols = _resolve_symbols(tickers)
    if not symbols:
        return {
            "generated_at": None,
            "direction": direction,
            "timeframe": timeframe,
            "candidates": [],
        }

    candles_map = await get_candles_batch(
        tickers=symbols,
        interval=timeframe,
        force_refresh=force_refresh,
    )

    candidates: List[Dict[str, Any]] = []
    for symbol in symbols:
        df = candles_map.get(symbol)
        if df is None or df.empty:
            continue
        try:
            features = compute_all(df)
            snapshot = analyze_snapshot(features)
            decision = snapshot["decision"]
            scores = decision.get("scores", {})
            action = decision.get("action", "hold")

            decision_payload = {
                "scores": scores,
                "confidence": decision.get("confidence", 0.0),
                "action": action,
            }

            if not _direction_match(action, direction):
                continue

            if not is_candidate(decision_payload, direction=direction):
                continue

            candidates.append(
                {
                    "ticker": symbol,
                    "action": action,
                    "score": float(scores.get("total", 0.0)),
                    "confidence": float(decision.get("confidence", 0.0)),
                    "rationale": decision.get("rationale", []),
                    "risk_notes": decision.get("risk_notes", []),
                    "data_source": df.attrs.get("source"),
                    "reference_price": decision.get("reference_price"),
                }
            )
        except Exception:
            continue

    candidates.sort(key=lambda item: abs(item.get("score", 0.0)), reverse=True)
    if limit:
        candidates = candidates[:limit]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "direction": direction,
        "timeframe": timeframe,
        "candidates": candidates,
    }


def _direction_match(action: str, direction: str) -> bool:
    if direction == "all":
        return action in {"buy", "sell"}
    if direction == "long":
        return action == "buy"
    if direction == "short":
        return action == "sell"
    return False


def _resolve_symbols(tickers: Optional[List[str]]) -> List[str]:
    if tickers:
        return sorted({symbol.strip().upper() for symbol in tickers if symbol.strip()})

    watchlist: Watchlist = load_watchlist()
    if watchlist.symbols:
        return watchlist.symbols

    return DEFAULT_LONG_POOL
