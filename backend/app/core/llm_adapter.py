from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from llm import LLMClient, LLMError, LLMNotConfigured  # type: ignore

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are StockAI's structured analysis engine. "
    "Always first reason carefully, then output results exactly in the requested XML-style "
    "sections. Do not add extra commentary."
)

USER_PROMPT_TEMPLATE = """\
你是一名严谨的证券分析师，需要根据下方上下文生成可执行的个股分析。

输出必须严格遵循以下格式：
<analysis>
一、大盘环境判断
- 根据 macro 中的指数/板块/情绪数据，明确描述当前市场环境、重要指数、成交/情绪变化。
- 如数据缺失需标注“[缺]”并说明影响。

二、个股基本面与技术面分析
- 基本面：估值、业绩、增长、行业地位，引用 fundamentals 中的营收/净利/ROE/增速等指标。
- 技术/资金面：趋势、动量、量能、重要价位、资金流。
- 如数据缺失需标注“[缺]”并说明。

三、风险考量
- 罗列与本标的相关的主要风险、触发条件及应对建议。
- 至少给出两条风险，不得省略。
</analysis>

<json>
{{
  "ticker": "{ticker}",
  "timeframe": "{timeframe}",
  "asOf": "<ISO8601 时间，例如 2024-05-05T12:00:00Z>",
  "verdict": {{
    "decision": "HOLD|BUY|BUY_THE_DIP|TRIM|SELL",
    "confidence": 0.67,
    "headline": "<一句话结论>",
    "thesis": "<简洁阐述结论的核心理由>"
  }},
  "metadata": {{
    "dataSource": "<行情数据源或 null>",
    "modelVersion": "<模型版本或 null>",
    "latencyMs": null
  }},
  "plan": {{
    "size": "<仓位建议，如 轻仓/中仓/空仓>",
    "entry": 23.45,
    "entryRange": {{"min": 22.8, "max": 23.6, "note": "<补充说明或 null>"}},
    "trigger": "<触发条件或 null>",
    "stop": 21.9,
    "stopNote": "<止损说明或 null>",
    "targets": [24.8, 26.2],
    "targetNote": "<止盈说明或 null>",
    "notes": "<额外执行要点或 null>"
  }} 或 null,
  "scenarios": [
    {{"name": "牛市演绎", "probability": 0.4, "trigger": "<触发条件>", "target": 26.5, "action": "加仓观察"}},
    {{"name": "中性主线", "probability": 0.45, "trigger": "<触发条件>", "target": 24.0, "action": "维持轻仓"}},
    {{"name": "下行风险", "probability": 0.15, "trigger": "<触发条件>", "target": 21.5, "action": "及时止损"}}
  ],
  "riskNotes": [
    "<风险提示一>",
    "<风险提示二>"
  ],
  "analysisNarrative": null
}}
</json>

严格要求：
- <analysis> 与 <json> 必须同时出现，且顺序一致；不得输出其它段落。
- JSON 中所有键必须存在；如无数据填 null 或 []。
- 置信度范围 0~1；若置信度 <0.55，entry 需为 null，并说明区间/触发。
- decision 只能取指定枚举；如不确定，用 HOLD。
- targets、target/probability 需为数值；概率可用 0~1 或百分比（模型会自动归一化）。
- 风险列表至少 2 条，需具体、可执行。
- 任何引用都必须来自上下文；如缺数据需明确说明。

上下文 JSON 包含：
- quote：基础行情与估值信息；
- indicators：本地计算的 EMA/MACD/RSI/支撑阻力 等技术指标；
- macro：宏观概览（指数、板块、情绪、新闻）；
- fundamentals：财务指标（营收、净利、增速、ROE 等）。
请充分利用可用数据，缺失时明确标注 “[缺]”。

上下文数据（JSON）：
{context}
"""

ANALYSIS_PATTERN = re.compile(r"<analysis>(.*?)</analysis>", re.IGNORECASE | re.DOTALL)
JSON_PATTERN = re.compile(r"<json>(.*?)</json>", re.IGNORECASE | re.DOTALL)


def _extract_sections(text: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not text:
        return None, None

    analysis_match = ANALYSIS_PATTERN.search(text)
    analysis_text = analysis_match.group(1).strip() if analysis_match else None

    json_match = JSON_PATTERN.search(text)
    json_payload: Optional[Dict[str, Any]] = None
    if json_match:
        candidate = json_match.group(1).strip()
        try:
            json_payload = json.loads(candidate)
        except json.JSONDecodeError:
            json_payload = None

    return analysis_text, json_payload


def _build_fallback_report(ticker: str, timeframe: str, context: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    headline = f"{ticker} 建议暂时观望"
    thesis = "缺乏充分的行情与指标支撑，建议保持观望，等待趋势与资金回暖。"
    analysis_text = (
        "一、大盘环境判断\n"
        "- 市场关键信息不足，需关注指数走势与成交量恢复。\n\n"
        "二、个股基本面与技术面分析\n"
        "- 数据不足，无法建立可靠的基本面与技术面结论。\n\n"
        "三、风险考量\n"
        "- 数据缺口可能导致判断偏差；建议获取更多行情与财务信息后再行动。"
    )
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "asOf": now.isoformat(),
        "verdict": {
            "decision": "HOLD",
            "confidence": 0.5,
            "headline": headline,
            "thesis": thesis,
        },
        "metadata": {
            "dataSource": context.get("dataSource"),
            "modelVersion": None,
            "latencyMs": None,
        },
        "plan": None,
        "scenarios": [
            {
                "name": "维持观望",
                "probability": 0.6,
                "trigger": "等待价格突破关键支撑/压力位",
                "target": None,
                "action": "保持现金或小仓位观望，关注量能变化。",
            }
        ],
        "riskNotes": [
            "数据不足导致判断不确定性较高。",
            "若后续出现放量下跌，需及时控制仓位。",
        ],
        "analysisNarrative": analysis_text,
    }


async def generate_report_json(
    ticker: str,
    timeframe: str,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        client = LLMClient.from_env()
    except (LLMNotConfigured, LLMError) as exc:
        logger.info("LLM 未配置或初始化失败，使用兜底模板：%s", exc)
        return _build_fallback_report(ticker, timeframe, context)

    prompt = USER_PROMPT_TEMPLATE.format(
        ticker=ticker,
        timeframe=timeframe,
        context=json.dumps(context, ensure_ascii=False, indent=2, default=str),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        raw_text = await asyncio.to_thread(client._chat, messages)  # type: ignore[attr-defined]
        analysis_text, json_payload = _extract_sections(raw_text)
        if not json_payload:
            raise ValueError("LLM response missing <json> section")

        json_payload.setdefault("ticker", ticker)
        json_payload.setdefault("timeframe", timeframe)
        json_payload.setdefault("asOf", datetime.now(timezone.utc).isoformat())
        metadata = json_payload.get("metadata") or {}
        if "dataSource" not in metadata:
            metadata["dataSource"] = context.get("dataSource")
        metadata.setdefault("modelVersion", None)
        metadata.setdefault("latencyMs", None)
        json_payload["metadata"] = metadata
        plan_value = json_payload.get("plan")
        if isinstance(plan_value, str) and plan_value.strip().lower() == "null":
            plan_value = None
        if plan_value is not None and not isinstance(plan_value, dict):
            plan_value = None
        json_payload["plan"] = plan_value

        scenarios_value = json_payload.get("scenarios")
        if isinstance(scenarios_value, dict):
            json_payload["scenarios"] = [scenarios_value]
        elif isinstance(scenarios_value, list):
            json_payload["scenarios"] = scenarios_value
        else:
            json_payload["scenarios"] = []

        risk_notes_value = json_payload.get("riskNotes")
        if isinstance(risk_notes_value, str):
            risk_notes_value = [risk_notes_value]
        if isinstance(risk_notes_value, list):
            json_payload["riskNotes"] = risk_notes_value
        else:
            json_payload["riskNotes"] = []

        fallback_analysis = json_payload.get("analysisNarrative")
        analysis_clean = (analysis_text or "").strip()
        if not analysis_clean and isinstance(fallback_analysis, str):
            candidate = fallback_analysis.strip()
            if candidate.lower() != "null":
                analysis_clean = candidate
        json_payload["analysisNarrative"] = analysis_clean

        return json_payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 输出解析失败，将使用兜底模板：%s", exc)
        return _build_fallback_report(ticker, timeframe, context)
