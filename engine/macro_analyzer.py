"""
宏观板块数据的解析与摘要生成。

输入：datahub.macro 返回的原始快照
输出：供 API、报告和前端使用的结构化摘要
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class MacroSummary:
    overview: str
    indices: Dict[str, Dict[str, Any]]
    top_sectors: List[Dict[str, Any]]
    weak_sectors: List[Dict[str, Any]]
    breadth: Dict[str, Any]
    sentiment: Dict[str, Any]
    highlights: List[str]
    risks: List[str]
    lhb: List[Dict[str, Any]]
    news: List[Dict[str, Any]]


def summarize_macro(snapshot: Dict[str, Any]) -> MacroSummary:
    indices = snapshot.get("indices", {})
    sectors = snapshot.get("sectors", {})
    breadth = snapshot.get("breadth", {})
    sentiment = snapshot.get("sentiment", {}) or {}
    lhb = snapshot.get("lhb") or []
    news = snapshot.get("news") or []

    overview = _build_overview(indices)
    top_sectors = sectors.get("top", []) or []
    weak_sectors = sectors.get("bottom", []) or []
    highlights = _build_highlights(indices, top_sectors, sentiment, lhb, news)
    risks = _build_risks(indices, weak_sectors, breadth, sentiment, lhb)

    return MacroSummary(
        overview=overview,
        indices=indices,
        top_sectors=top_sectors,
        weak_sectors=weak_sectors,
        breadth=breadth,
        sentiment=sentiment,
        highlights=highlights,
        risks=risks,
        lhb=lhb,
        news=news,
    )


def _build_overview(indices: Dict[str, Dict[str, Any]]) -> str:
    if not indices:
        return "指数数据暂不可用。"

    sorted_items = sorted(
        indices.items(),
        key=lambda item: abs(item[1].get("change_pct", 0.0)),
        reverse=True,
    )
    summary_parts = []
    for name, payload in sorted_items[:3]:
        change = payload.get("change_pct", 0.0)
        direction = "上涨" if change >= 0 else "下跌"
        summary_parts.append(f"{name} {direction} {abs(change):.2f}%")
    return "；".join(summary_parts)


def _build_highlights(
    indices: Dict[str, Dict[str, Any]],
    top_sectors: List[Dict[str, Any]],
    sentiment: Dict[str, Any],
    lhb: List[Dict[str, Any]],
    news: List[Dict[str, Any]],
) -> List[str]:
    highlights: List[str] = []
    for sector in top_sectors[:3]:
        name = sector.get("name")
        change = sector.get("change_pct", 0.0)
        flow = sector.get("fund_flow")
        text = f"{name} 领涨 {change:.2f}%"
        if flow is not None:
            text += f" · 主力净流入 {flow/1e8:.2f} 亿"
        leaders = sector.get("leaders") or []
        if leaders:
            leader_names = ", ".join(
                f"{item.get('name', item.get('code'))}({item.get('change_pct', 0):.2f}%)"
                for item in leaders[:2]
                if item
            )
            if leader_names:
                text += f" · 龙头：{leader_names}"
        highlights.append(text)

    for idx, payload in indices.items():
        change = payload.get("change_pct", 0.0)
        if change >= 1.5:
            highlights.append(f"{idx} 强势上涨 {change:.2f}%")

    northbound = sentiment.get("northbound_net")
    if isinstance(northbound, (int, float)) and northbound > 0:
        highlights.append(f"北向资金净流入 {northbound/1e8:.2f} 亿")
    ratio = sentiment.get("advance_decline_ratio")
    if isinstance(ratio, (int, float)) and ratio >= 1.5:
        highlights.append(f"涨跌比 {ratio:.2f}，市场情绪偏多")

    positive_lhb = [item for item in lhb if _to_float(item.get("net_buy")) and _to_float(item.get("net_buy")) > 0]
    if positive_lhb:
        best = max(positive_lhb, key=lambda item: _to_float(item.get("net_buy")) or 0.0)
        net_buy = _to_float(best.get("net_buy")) or 0.0
        name = best.get("name") or best.get("code")
        highlights.append(f"{name} 龙虎榜净买 {net_buy/1e8:.2f} 亿")

    if news:
        first = news[0]
        title = first.get("title")
        if title:
            highlights.append(f"新闻焦点：{title}")
    return highlights


def _build_risks(
    indices: Dict[str, Dict[str, Any]],
    weak_sectors: List[Dict[str, Any]],
    breadth: Dict[str, Any],
    sentiment: Dict[str, Any],
    lhb: List[Dict[str, Any]],
) -> List[str]:
    risks: List[str] = []
    for sector in weak_sectors[:3]:
        name = sector.get("name")
        change = sector.get("change_pct", 0.0)
        if change is not None:
            risks.append(f"{name} 领跌 {abs(change):.2f}%")

    for idx, payload in indices.items():
        change = payload.get("change_pct", 0.0)
        if change <= -1.5:
            risks.append(f"{idx} 较大回调 {abs(change):.2f}%")

    advance = breadth.get("advance")
    decline = breadth.get("decline")
    if isinstance(advance, int) and isinstance(decline, int) and advance < decline:
        ratio = advance / max(decline, 1)
        risks.append(f"市场宽度偏弱，涨跌比 {ratio:.2f}")

    northbound = sentiment.get("northbound_net")
    if isinstance(northbound, (int, float)) and northbound < 0:
        risks.append(f"北向资金净流出 {abs(northbound)/1e8:.2f} 亿")
    ratio = sentiment.get("advance_decline_ratio")
    if isinstance(ratio, (int, float)) and ratio < 1:
        risks.append(f"涨跌比 {ratio:.2f}，需防范情绪走弱")

    negative_lhb = [item for item in lhb if _to_float(item.get("net_buy")) and _to_float(item.get("net_buy")) < 0]
    if negative_lhb:
        worst = min(negative_lhb, key=lambda item: _to_float(item.get("net_buy")) or 0.0)
        net_buy = abs(_to_float(worst.get("net_buy")) or 0.0)
        name = worst.get("name") or worst.get("code")
        risks.append(f"{name} 龙虎榜净卖 {net_buy/1e8:.2f} 亿")

    return risks


def summarize_for_report(summary: MacroSummary) -> Dict[str, Any]:
    """将宏观摘要转换为适合报告使用的结构。"""
    return {
        "overview": summary.overview,
        "highlights": summary.highlights,
        "risks": summary.risks,
        "top_sectors": summary.top_sectors,
        "weak_sectors": summary.weak_sectors,
        "breadth": summary.breadth,
        "sentiment": summary.sentiment,
        "lhb": summary.lhb,
        "news": summary.news,
    }


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("%", "")
        if not text:
            return None
        try:
            num = float(text)
        except ValueError:
            return None
    if not math.isfinite(num):
        return None
    return num
