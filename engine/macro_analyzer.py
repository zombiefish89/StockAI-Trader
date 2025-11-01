"""
宏观板块数据的解析与摘要生成。

输入：datahub.macro 返回的原始快照
输出：供 API、报告和前端使用的结构化摘要
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class MacroSummary:
    overview: str
    indices: Dict[str, Dict[str, Any]]
    top_sectors: List[Dict[str, Any]]
    weak_sectors: List[Dict[str, Any]]
    breadth: Dict[str, Any]
    highlights: List[str]
    risks: List[str]


def summarize_macro(snapshot: Dict[str, Any]) -> MacroSummary:
    indices = snapshot.get("indices", {})
    sectors = snapshot.get("sectors", {})
    breadth = snapshot.get("breadth", {})

    overview = _build_overview(indices)
    top_sectors = sectors.get("top", []) or []
    weak_sectors = sectors.get("bottom", []) or []
    highlights = _build_highlights(indices, top_sectors)
    risks = _build_risks(indices, weak_sectors, breadth)

    return MacroSummary(
        overview=overview,
        indices=indices,
        top_sectors=top_sectors,
        weak_sectors=weak_sectors,
        breadth=breadth,
        highlights=highlights,
        risks=risks,
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
) -> List[str]:
    highlights: List[str] = []
    for sector in top_sectors[:3]:
        name = sector.get("name")
        change = sector.get("change_pct", 0.0)
        flow = sector.get("fund_flow")
        text = f"{name} 领涨 {change:.2f}%"
        if flow is not None:
            text += f" · 主力净流入 {flow/1e8:.2f} 亿"
        highlights.append(text)

    for idx, payload in indices.items():
        change = payload.get("change_pct", 0.0)
        if change >= 1.5:
            highlights.append(f"{idx} 强势上涨 {change:.2f}%")
    return highlights


def _build_risks(
    indices: Dict[str, Dict[str, Any]],
    weak_sectors: List[Dict[str, Any]],
    breadth: Dict[str, Any],
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
    }

