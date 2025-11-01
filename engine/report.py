"""Textual report rendering utilities."""

from __future__ import annotations

from typing import Dict, List


def render(decision: Dict[str, object]) -> str:
    """Render analysis result into a concise Chinese narrative."""
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

