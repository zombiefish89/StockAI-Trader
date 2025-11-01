"""分析结果文本化渲染工具。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def render(decision: Dict[str, object]) -> str:
    """将结构化分析结果输出为简洁的中文描述。"""
    action = decision.get("action", "hold")
    action_map = {
        "buy": "建议逢低布局，多头为主",
        "sell": "建议逢高减仓，回避风险",
        "hold": "信号中性，建议观望",
    }

    entry = decision.get("entry")
    stop = decision.get("stop")
    targets = decision.get("targets", [])
    confidence = decision.get("confidence")

    lines: List[str] = []
    lines.append(f"【操作建议】{action_map.get(action, '观望为主')}（置信度 {confidence:.0%}）")

    if entry and stop:
        targets_text = " / ".join(f"{t:.2f}" for t in targets) if targets else "—"
        lines.append(f"入场参考：{entry:.2f}，止损：{stop:.2f}，目标区间：{targets_text}")

    rationale = decision.get("rationale", [])
    if rationale:
        lines.append("【核心逻辑】")
        for reason in rationale:
            lines.append(f"- {reason}")

    risks = decision.get("risk_notes", [])
    if risks:
        lines.append("【风险提示】")
        for risk in risks:
            lines.append(f"- {risk}")

    return "\n".join(lines)


def render_daily_report(
    date: str,
    overview: str,
    highlights: List[Any],
    risks: List[str],
    details: Dict[str, Dict[str, Any]],
    macro: Optional[Dict[str, Any]] = None,
    opportunities: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """根据批量分析结果输出每日报告文本。"""

    lines: List[str] = []
    lines.append(f"【日期】{date}")
    lines.append(f"【市场概览】{overview or '今日暂无整体概览信息'}")

    if highlights:
        lines.append("【重点关注】")
        for item in highlights:
            if isinstance(item, str):
                lines.append(f"- {item}")
            else:
                ticker = item.get("ticker", "-")
                summary = item.get("summary", "")
                lines.append(f"- {ticker}: {summary}")

    if risks:
        lines.append("【潜在风险】")
        for note in risks:
            lines.append(f"- {note}")

    if macro:
        lines.append("【宏观概览】")
        overview_text = macro.get("overview")
        if overview_text:
            lines.append(f"- {overview_text}")
        top_sectors = macro.get("top_sectors", []) or []
        if top_sectors:
            lines.append("- 领涨板块：" + "；".join(
                f"{item.get('name')}({item.get('change_pct', 0):.2f}%)" for item in top_sectors[:3]
            ))
        weak_sectors = macro.get("weak_sectors", []) or []
        if weak_sectors:
            lines.append("- 领跌板块：" + "；".join(
                f"{item.get('name')}({item.get('change_pct', 0):.2f}%)" for item in weak_sectors[:3]
            ))
        breadth = macro.get("breadth", {}) or {}
        adv = breadth.get("advance")
        decl = breadth.get("decline")
        if adv is not None and decl is not None:
            lines.append(f"- 涨跌家数：{adv} / {decl}")

    lines.append("【个股详情】")
    for ticker, payload in details.items():
        action = payload.get("action", "hold")
        confidence = payload.get("confidence", 0.0)
        rationale = payload.get("rationale", [])
        risk_notes = payload.get("risk_notes", [])
        lines.append(
            f"◼ {ticker} | {action} | 置信度 {confidence:.0%}"
        )
        for reason in rationale:
            lines.append(f"  · 理由：{reason}")
        for risk in risk_notes:
            lines.append(f"  · 风险：{risk}")

    if opportunities:
        lines.append("【机会扫描】")
        for opp in opportunities[:5]:
            ticker = opp.get("ticker")
            action = opp.get("action")
            score = opp.get("score", 0.0)
            summary = opp.get("rationale", [])
            first = summary[0] if summary else "信号触发"
            lines.append(f"- {ticker} | {action} | 得分 {score:.2f} · {first}")

    return "\n".join(lines)
