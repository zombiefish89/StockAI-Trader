"""Analysis engine components for StockAI Trader."""

from .analyzer import ScoreResult, analyze_snapshot, build_price_info, score_signals  # noqa: F401
from .features import summarize_indicators  # noqa: F401
from .macro_analyzer import MacroSummary, summarize_for_report, summarize_macro  # noqa: F401
from .opportunity_filter import is_candidate  # noqa: F401
from .report import render, render_daily_report  # noqa: F401
from .rules import generate_decision  # noqa: F401

__all__ = [
    "MacroSummary",
    "ScoreResult",
    "build_price_info",
    "generate_decision",
    "analyze_snapshot",
    "is_candidate",
    "render",
    "render_daily_report",
    "summarize_for_report",
    "summarize_macro",
    "score_signals",
]
