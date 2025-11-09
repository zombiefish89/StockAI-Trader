from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query

from backend.app.schemas.symbols import SymbolSearchResponse
from backend.app.services.symbols import search_symbols

router = APIRouter(prefix="/symbols", tags=["symbols"])


def _parse_markets(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None:
        return None
    items = [part.strip().lower() for part in raw.split(",")]
    cleaned = [item for item in items if item]
    return cleaned or None


@router.get("/search", response_model=SymbolSearchResponse)
async def symbol_search_endpoint(
    q: str = Query(..., min_length=1, description="股票代码 / 中文或英文关键字"),
    limit: int = Query(10, ge=1, le=50),
    markets: Optional[str] = Query(
        None,
        description="可选，限制搜索市场（例如 cn,us,hk）",
    ),
) -> SymbolSearchResponse:
    market_filters = _parse_markets(markets)
    return await search_symbols(query=q, limit=limit, markets=market_filters)
