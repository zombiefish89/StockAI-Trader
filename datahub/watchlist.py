"""
自选股列表管理工具。

默认采用 JSON 文件持久化，可轻易替换为 SQLite 等其他存储。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

WATCHLIST_PATH = Path("data/watchlist.json")


@dataclass
class Watchlist:
    """自选股列表的数据表示。"""

    symbols: List[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        if not symbol:
            return
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            self.updated_at = datetime.now(timezone.utc)

    def remove(self, symbol: str) -> None:
        norm = symbol.strip().upper()
        if norm in self.symbols:
            self.symbols = [item for item in self.symbols if item != norm]
            self.updated_at = datetime.now(timezone.utc)

    def extend(self, symbols: Iterable[str]) -> None:
        for symbol in symbols:
            self.add(symbol)

    def to_dict(self) -> dict:
        return {
            "symbols": self.symbols,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Watchlist":
        symbols = data.get("symbols") or []
        updated_raw = data.get("updated_at")
        if updated_raw:
            updated_at = datetime.fromisoformat(updated_raw)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
        else:
            updated_at = datetime.now(timezone.utc)
        return cls(symbols=list(symbols), updated_at=updated_at)


def load_watchlist(path: Path | None = None) -> Watchlist:
    """读取自选股列表，若不存在则返回空列表。"""
    target = path or WATCHLIST_PATH
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        return Watchlist()
    data = json.loads(target.read_text(encoding="utf-8"))
    return Watchlist.from_dict(data)


def save_watchlist(watchlist: Watchlist, path: Path | None = None) -> None:
    """保存自选股列表到文件。"""
    target = path or WATCHLIST_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(watchlist.to_dict(), ensure_ascii=False, indent=2)
    target.write_text(payload, encoding="utf-8")
