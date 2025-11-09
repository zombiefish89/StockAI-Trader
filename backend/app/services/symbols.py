from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:  # pragma: no cover - optional dependency
    from pymongo import MongoClient  # type: ignore
    from pymongo.collection import Collection  # type: ignore
    from pymongo.errors import PyMongoError  # type: ignore
except ImportError:  # pragma: no cover
    MongoClient = None  # type: ignore
    Collection = None  # type: ignore
    PyMongoError = Exception  # type: ignore

from backend.app.schemas.symbols import SymbolInfo, SymbolSearchResponse
PACKAGE_SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "assets" / "symbols_snapshot.json"

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOT_PATH = Path("data/symbols_snapshot.json")


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SymbolSearchService:
    """封装 Mongo / JSON 字典的股票名称搜索。"""

    def __init__(self) -> None:
        self.snapshot_path = Path(os.getenv("SYMBOL_SNAPSHOT_PATH", str(DEFAULT_SNAPSHOT_PATH)))
        mongo_enabled = _parse_bool(os.getenv("SYMBOLS_MONGO_ENABLED"), default=False)
        cache_mongo_enabled = _parse_bool(os.getenv("MONGO_ENABLED"), default=False)
        self.mongo_enabled = mongo_enabled or cache_mongo_enabled
        self.mongo_uri = os.getenv("SYMBOLS_MONGO_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))
        self.mongo_db = os.getenv("SYMBOLS_MONGO_DB", os.getenv("MONGO_DB", "stockai_cache"))
        self.mongo_collection = os.getenv("SYMBOLS_MONGO_COLLECTION", "symbols_lookup")
        self._collection: Optional[Collection] = None
        self._mongo_lock = Lock()
        self._snapshot_cache: Optional[List[Dict[str, Any]]] = None
        self._snapshot_mtime: Optional[float] = None
        self._snapshot_source: Optional[Path] = None
        self.max_limit = int(os.getenv("SYMBOLS_MAX_LIMIT", "50"))
        self._text_search_disabled = False

    def search(
        self,
        query: str,
        limit: int = 10,
        markets: Optional[Sequence[str]] = None,
    ) -> SymbolSearchResponse:
        sanitized = (query or "").strip()
        limit = max(1, min(limit, self.max_limit))
        normalized_markets = self._normalize_markets(markets)
        if not sanitized:
            return SymbolSearchResponse(query=sanitized, limit=limit, source="empty", items=[])

        mongo_items = self._search_mongo(sanitized, limit, normalized_markets)
        if mongo_items:
            return SymbolSearchResponse(query=sanitized, limit=limit, source="mongo", items=mongo_items)

        snapshot_items = self._search_snapshot(sanitized, limit, normalized_markets)
        source = "snapshot" if snapshot_items else "empty"
        return SymbolSearchResponse(query=sanitized, limit=limit, source=source, items=snapshot_items)

    def _normalize_markets(self, markets: Optional[Sequence[str]]) -> List[str]:
        if not markets:
            return []
        normalized = []
        for item in markets:
            if not item:
                continue
            normalized.append(item.strip().lower())
        return [m for m in normalized if m]

    def _get_collection(self) -> Optional[Collection]:
        if not self.mongo_enabled or MongoClient is None:
            return None
        if self._collection is not None:
            return self._collection
        with self._mongo_lock:
            if self._collection is not None:
                return self._collection
            try:
                client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=2000)  # type: ignore[arg-type]
                client.admin.command("ping")
                self._collection = client[self.mongo_db][self.mongo_collection]
            except Exception as exc:  # pragma: no cover - 网络异常等
                logger.warning("MongoDB 不可用，已退回本地快照：%s", exc)
                self._collection = None
        return self._collection

    def _search_mongo(
        self,
        query: str,
        limit: int,
        markets: Sequence[str],
    ) -> List[SymbolInfo]:
        collection = self._get_collection()
        if collection is None:
            return []

        filter_query: Dict[str, Any] = {}
        if markets:
            filter_query["market"] = {"$in": list(markets)}

        items: List[SymbolInfo] = []

        if not self._text_search_disabled:
            projection = {
                "_id": 0,
                "ticker": 1,
                "display_name": 1,
                "name_cn": 1,
                "name_en": 1,
                "market": 1,
                "exchange": 1,
                "aliases": 1,
                "score": {"$meta": "textScore"},
            }
            text_query = {"$text": {"$search": query}, **filter_query}
            try:
                cursor = collection.find(
                    text_query,
                    projection=projection,
                ).sort([("score", {"$meta": "textScore"}), ("rank", 1)]).limit(limit)
                for doc in cursor:
                    items.append(self._build_symbol_info(doc, doc.get("score")))
            except PyMongoError as exc:
                logger.debug("Mongo text search 失败：%s", exc)
                message = str(exc).lower()
                if "text index required" in message:
                    self._text_search_disabled = True
            except Exception as exc:  # pragma: no cover - 索引缺失等
                logger.debug("Mongo text search 异常：%s", exc)
                self._text_search_disabled = True

        if items:
            return items

        regex = re.compile(re.escape(query), re.IGNORECASE)
        fallback_filter = dict(filter_query)
        fallback_filter["$or"] = [
            {"ticker": regex},
            {"display_name": regex},
            {"name_cn": regex},
            {"name_en": regex},
            {"aliases": regex},
            {"pinyin_full": regex},
            {"pinyin_abbr": regex},
        ]
        projection = {
            "_id": 0,
            "ticker": 1,
            "display_name": 1,
            "name_cn": 1,
            "name_en": 1,
            "market": 1,
            "exchange": 1,
            "aliases": 1,
        }
        try:
            cursor = collection.find(fallback_filter, projection=projection).sort("rank", 1).limit(limit)
            for doc in cursor:
                items.append(self._build_symbol_info(doc, None))
        except PyMongoError as exc:  # pragma: no cover
            logger.debug("Mongo fallback 查询失败：%s", exc)
        return items

    def _build_symbol_info(self, doc: Dict[str, Any], score: Optional[float]) -> SymbolInfo:
        ticker = str(doc.get("ticker") or doc.get("_id") or "").upper()
        display_name = (
            doc.get("display_name")
            or doc.get("name_cn")
            or doc.get("name_en")
            or ticker
        )
        aliases = self._normalize_list(doc.get("aliases"))
        return SymbolInfo(
            ticker=ticker,
            displayName=display_name,
            nameCn=doc.get("name_cn"),
            nameEn=doc.get("name_en"),
            market=doc.get("market"),
            exchange=doc.get("exchange"),
            aliases=aliases,
            score=score,
        )

    def _normalize_list(self, value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        results: List[str] = []
        for item in value:
            if not item:
                continue
            results.append(str(item))
        return results

    def _resolve_snapshot_path(self) -> Optional[Path]:
        primary = Path(self.snapshot_path)
        candidates = [primary]
        packaged = PACKAGE_SNAPSHOT_PATH
        if packaged != primary:
            candidates.append(packaged)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _load_snapshot(self) -> List[Dict[str, Any]]:
        path = self._resolve_snapshot_path()
        if path is None:
            return []
        mtime = path.stat().st_mtime
        if (
            self._snapshot_cache is not None
            and self._snapshot_mtime == mtime
            and self._snapshot_source == path
        ):
            return self._snapshot_cache
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                self._snapshot_cache = payload
            elif isinstance(payload, dict):
                self._snapshot_cache = payload.get("items", [])
            else:
                self._snapshot_cache = []
        except Exception as exc:  # pragma: no cover - 非法 JSON
            logger.warning("symbols_snapshot 解析失败：%s", exc)
            self._snapshot_cache = []
        self._snapshot_mtime = mtime
        self._snapshot_source = path
        return self._snapshot_cache or []

    def _search_snapshot(
        self,
        query: str,
        limit: int,
        markets: Sequence[str],
    ) -> List[SymbolInfo]:
        data = self._load_snapshot()
        if not data:
            return []
        normalized_query = query.lower()
        matches: List[tuple[float, Dict[str, Any]]] = []

        for doc in data:
            market = str(doc.get("market") or "").lower()
            if markets and market not in markets:
                continue
            score = self._score_snapshot(doc, normalized_query)
            if score <= 0:
                continue
            matches.append((score, doc))

        matches.sort(key=lambda item: item[0], reverse=True)
        limited = matches[:limit]
        return [self._build_symbol_info(doc, score) for score, doc in limited]

    def _score_snapshot(self, doc: Dict[str, Any], query: str) -> float:
        candidates = [
            str(doc.get("ticker") or "").lower(),
            str(doc.get("display_name") or "").lower(),
            str(doc.get("name_cn") or "").lower(),
            str(doc.get("name_en") or "").lower(),
        ]
        aliases = [str(item).lower() for item in doc.get("aliases", []) if item]
        candidates.extend(aliases)
        score = 0.0
        for candidate in candidates:
            if not candidate:
                continue
            if candidate == query:
                return 100.0
            if candidate.startswith(query):
                score = max(score, 80.0)
            elif query in candidate:
                score = max(score, 60.0)
        return score


_SERVICE: Optional[SymbolSearchService] = None


def get_symbol_service() -> SymbolSearchService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SymbolSearchService()
    return _SERVICE


async def search_symbols(
    query: str,
    limit: int = 10,
    markets: Optional[Sequence[str]] = None,
) -> SymbolSearchResponse:
    service = get_symbol_service()
    return await asyncio.to_thread(service.search, query, limit, markets)
