"""
每日自动报告调度器。

基于 APScheduler 安排定时任务，按日生成自选股批量报告，
并将结果持久化到 `reports/` 目录。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

from datahub.fetcher import get_candles_batch
from datahub.indicators import compute_all
from datahub.macro import get_macro_snapshot
from datahub.scanner import scan_opportunities
from datahub.watchlist import load_watchlist
from engine.analyzer import analyze_snapshot
from engine.macro_analyzer import summarize_for_report, summarize_macro
from engine.report import render, render_daily_report

logger = logging.getLogger(__name__)

REPORT_DIR = Path("reports")


async def generate_daily_report(timeframe: str = "1d") -> Dict[str, Any]:
    """执行一次批量分析并生成结构化报告。"""
    watchlist = load_watchlist()
    if not watchlist.symbols:
        logger.info("自选股列表为空，跳过报告生成。")
        return {}

    start_time = time.perf_counter()
    candles_map = await get_candles_batch(
        tickers=watchlist.symbols,
        interval=timeframe,
        use_cache=True,
        force_refresh=False,
    )

    results: Dict[str, Dict[str, Any]] = {}
    failed: List[str] = []
    latest_ts: Optional[datetime] = None

    for symbol in watchlist.symbols:
        df = candles_map.get(symbol)
        if df is None or df.empty:
            failed.append(symbol)
            continue
        try:
            features = compute_all(df)
            snapshot = analyze_snapshot(features)
            decision = snapshot["decision"]
            report_text = render(decision)
            as_of_raw = decision.get("as_of") or features["timestamp"]
            as_of_dt = datetime.fromisoformat(as_of_raw)
            results[symbol] = {
                "action": decision["action"],
                "confidence": float(decision["confidence"]),
                "entry": float(decision["entry"]),
                "stop": float(decision["stop"]),
                "targets": [float(t) for t in decision["targets"]],
                "rationale": decision["rationale"],
                "risk_notes": decision["risk_notes"],
                "report": report_text,
                "reference_price": float(decision["reference_price"]),
                "atr": float(decision["atr"]),
                "data_source": df.attrs.get("source"),
            }
            if latest_ts is None or as_of_dt > latest_ts:
                latest_ts = as_of_dt
        except Exception as exc:  # pragma: no cover - 意外计算错误
            logger.exception("生成 %s 报告失败：%s", symbol, exc)
            failed.append(symbol)

    if not results:
        logger.warning("所有股票分析均失败，未生成报告。")
        return {}

    macro_snapshot = await get_macro_snapshot()
    macro_summary = summarize_macro(macro_snapshot)
    macro_report = summarize_for_report(macro_summary)

    opportunity_payload = await scan_opportunities(direction="all", limit=10)

    overview = _build_overview(results)
    highlights = macro_summary.highlights + _pick_highlights(results)
    risk_notes = macro_summary.risks + _collect_risks(results)

    date_str = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    generated_at = datetime.now(timezone.utc)

    body_text = render_daily_report(
        date=date_str,
        overview=overview,
        highlights=highlights,
        risks=risk_notes,
        details={
            ticker: {
                "action": payload["action"],
                "confidence": payload["confidence"],
                "rationale": payload["rationale"],
                "risk_notes": payload["risk_notes"],
            }
            for ticker, payload in results.items()
        },
        macro=macro_report,
        opportunities=opportunity_payload.get("candidates", []),
    )

    payload = {
        "date": date_str,
        "generated_at": generated_at.isoformat(),
        "timeframe": timeframe,
        "market_overview": overview,
        "highlights": highlights,
        "risks": risk_notes,
        "results": results,
        "failed": failed,
        "latency_ms": int((time.perf_counter() - start_time) * 1000),
        "as_of": (latest_ts or generated_at).isoformat(),
        "macro": macro_report,
        "opportunities": opportunity_payload,
    }

    _persist_report(payload, body_text)
    logger.info("每日报告生成完成：%s（成功 %d，失败 %d）", date_str, len(results), len(failed))
    return payload


def start_scheduler(hour: int = 17, minute: int = 30, tz_name: str = "Asia/Shanghai") -> AsyncIOScheduler:
    """启动每日调度器，在指定时间生成报告。"""
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(tz_name))
    scheduler.add_job(
        generate_daily_report,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily_report_job",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.start()
    logger.info("已启动每日报告调度器，时间 %02d:%02d (%s)", hour, minute, tz_name)
    return scheduler


def _build_overview(results: Dict[str, Dict[str, Any]]) -> str:
    total = len(results)
    action_counts: Dict[str, int] = {"buy": 0, "sell": 0, "hold": 0}
    for payload in results.values():
        action = payload.get("action", "hold")
        if action not in action_counts:
            action_counts[action] = 0
        action_counts[action] += 1
    return (
        f"共分析 {total} 只股票："
        f"买入 {action_counts.get('buy', 0)}，"
        f"卖出 {action_counts.get('sell', 0)}，"
        f"观望 {action_counts.get('hold', 0)}。"
    )


def _pick_highlights(results: Dict[str, Dict[str, Any]], limit: int = 3) -> List[Dict[str, str]]:
    sorted_items = sorted(
        results.items(),
        key=lambda item: item[1].get("confidence", 0.0),
        reverse=True,
    )
    highlights: List[Dict[str, str]] = []
    for ticker, payload in sorted_items:
        if len(highlights) >= limit:
            break
        summary = f"{payload.get('action', 'hold')} · 置信度 {payload.get('confidence', 0.0):.0%}"
        rationale = payload.get("rationale", [])
        if rationale:
            summary += f" · {rationale[0]}"
        highlights.append({"ticker": ticker, "summary": summary})
    return highlights


def _collect_risks(results: Dict[str, Dict[str, Any]], limit: int = 5) -> List[str]:
    seen: set[str] = set()
    risks: List[str] = []
    for payload in results.values():
        for note in payload.get("risk_notes", []):
            if note not in seen:
                risks.append(note)
                seen.add(note)
            if len(risks) >= limit:
                return risks
    return risks


def _persist_report(payload: Dict[str, Any], body: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date = payload["date"]
    json_path = REPORT_DIR / f"{date}.json"
    txt_path = REPORT_DIR / f"{date}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(body, encoding="utf-8")


async def main() -> None:
    """用于脚本化运行生成报告。"""
    await generate_daily_report()


if __name__ == "__main__":
    asyncio.run(main())
