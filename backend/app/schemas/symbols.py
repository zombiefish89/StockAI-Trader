from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SymbolInfo(BaseModel):
    ticker: str = Field(..., description="规范化后的股票代码，例如 600519.SH 或 AAPL")
    displayName: str = Field(..., description="用于展示的名称，优先中文名")
    nameCn: Optional[str] = Field(None, description="中文全称")
    nameEn: Optional[str] = Field(None, description="英文全称")
    market: Optional[str] = Field(None, description="市场标识，如 cn/us/hk")
    exchange: Optional[str] = Field(None, description="交易所代码")
    aliases: List[str] = Field(default_factory=list, description="可选的别名或缩写")
    score: Optional[float] = Field(None, description="搜索得分，越高越相关")


class SymbolSearchResponse(BaseModel):
    query: str
    limit: int
    source: Literal["mongo", "snapshot", "empty"]
    items: List[SymbolInfo] = Field(default_factory=list)
